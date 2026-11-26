"""Cloud entry point. Preview is default; delivery requires explicit enabling."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from zoneinfo import ZoneInfo

from .editor import EditorError, editor_to_digest, generate_editor
from .feeds import collect_sources
from .render import render_digest
from .smtp_delivery import DeliveryError, DeliveryUncertain, prepare_message, send_one
from .sources import enrich_articles
from .state_store import GitHubStateStore, LocalStateStore, StateError

ROOT = Path(__file__).resolve().parent.parent
FREE_MODEL = "gemini-3.5-flash-lite"


class ConfigurationError(RuntimeError):
    pass


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ConfigurationError("Expected a JSON object")
    return value


def recipients_from(value: str) -> list[str]:
    if not value or not value.strip():
        raise ConfigurationError("DIGEST_RECIPIENTS is missing")
    try:
        parsed = json.loads(value)
    except ValueError:
        parsed = re.split(r"[;,\s]+", value.strip())
    if not isinstance(parsed, list) or not parsed:
        raise ConfigurationError("Recipients must be a JSON list or comma-separated addresses")
    result: list[str] = []
    for address in parsed:
        if not isinstance(address, str) or any(ord(c) < 32 for c in address):
            raise ConfigurationError("Invalid recipient address")
        address = address.strip()
        if not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", address):
            raise ConfigurationError("Recipients must contain plain email addresses only")
        if address.casefold() not in {item.casefold() for item in result}:
            result.append(address)
    if len(result) > 100:
        raise ConfigurationError("More than 100 recipients requires a reviewed mailing setup")
    return result


def recipient_key(address: str) -> str:
    return hashlib.sha256(address.casefold().encode()).hexdigest()


def validate_config(config: dict) -> None:
    if config.get("sender"):
        recipients_from(json.dumps([config["sender"]]))
    if config.get("timezone") != "America/New_York" or config.get("language") != "en":
        raise ConfigurationError("This deployment expects the confirmed New York / English configuration")
    if config.get("model") != FREE_MODEL:
        raise ConfigurationError("Model is not the reviewed free-tier candidate; no alternate model will be used")
    for name, minimum, maximum in (("lookback_hours", 1, 168), ("max_items_per_source", 1, 100),
                                  ("max_source_characters", 1000, 200000), ("max_output_tokens", 128, 16384)):
        value = config.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise ConfigurationError(f"Invalid {name}")


def preflight(config: dict, mode: str, environment: dict) -> list[str]:
    if mode not in ("preview", "preview-email", "send", "smtp-test"):
        raise ConfigurationError("Unsupported run mode")
    validate_config(config)
    if mode == "send" and environment.get("DIGEST_ENABLED", "").lower() != "true":
        raise ConfigurationError("Delivery is disabled. Set repository variable DIGEST_ENABLED only after checking preview and SMTP")
    if mode in ("preview", "preview-email", "send"):
        if environment.get("GEMINI_FREE_TIER_CONFIRMED", "").lower() != "true":
            raise ConfigurationError("Confirm a Free-tier Gemini project without paid billing, then set GEMINI_FREE_TIER_CONFIRMED=true")
        if not environment.get("GEMINI_API_KEY"):
            raise ConfigurationError("GEMINI_API_KEY secret is missing")
    if mode in ("send", "smtp-test", "preview-email"):
        if not environment.get("SMTP_APP_PASSWORD"):
            raise ConfigurationError("SMTP_APP_PASSWORD secret is missing")
        sender = environment.get("SMTP_USERNAME") or config.get("sender")
        if not sender:
            raise ConfigurationError("SMTP_USERNAME secret is missing")
        recipients_from(json.dumps([sender]))
    if mode == "send":
        if not environment.get("GITHUB_TOKEN") or not environment.get("GITHUB_REPOSITORY"):
            raise ConfigurationError("Live delivery requires durable encrypted state in the intended GitHub repository")
        if not environment.get("STATE_ENCRYPTION_KEY"):
            raise ConfigurationError("STATE_ENCRYPTION_KEY secret is missing")
        subscribers = recipients_from(environment.get("DIGEST_RECIPIENTS", ""))
        try:
            internal = recipients_from(environment.get("DIGEST_INTERNAL_RECIPIENTS", ""))
        except ConfigurationError:
            raise ConfigurationError("DIGEST_INTERNAL_RECIPIENTS secret is missing or invalid") from None
        # Both groups are required. Reuse the same parser to deduplicate across
        # groups and apply its 100-recipient limit to the final combined list.
        return recipients_from(json.dumps(subscribers + internal))
    return []


def build_public_inputs(articles: list[dict], max_characters: int) -> tuple[list[dict], list[str]]:
    """Keep every source and divide the serialized context budget fairly.

    A source excerpt appears once, in content; summary is deliberately empty
    rather than duplicating the same text and consuming the budget twice.
    """
    if not articles:
        return [], []
    public, texts = [], []
    identifiers = set()
    for article in articles:
        canonical = article.get("id")
        if not isinstance(canonical, str) or not canonical or canonical in identifiers:
            raise ConfigurationError("Source records require distinct canonical article IDs")
        identifiers.add(canonical)
        selected = str(article.get("source_text") or article.get("body") or article.get("summary") or "")
        texts.append(selected)
        row = {key: article.get(key) for key in ("source", "title", "url", "published_at", "section", "content_scope")}
        row.update({"id": f"article_{len(public) + 1:04d}", "canonical_id": canonical,
                    "summary": "", "content": ""})
        public.append(row)
    encoded = lambda value: len(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
    remaining = max_characters - encoded(public)
    minimums = [text[:160] for text in texts]
    minimum_cost = sum(encoded(text) - 2 for text in minimums)
    if remaining < minimum_cost:
        raise ConfigurationError("Source context cap cannot represent every source; split the collection explicitly rather than dropping sources")
    for row, text in zip(public, minimums):
        row["content"] = text
    remaining -= minimum_cost
    pending = {index for index, text in enumerate(texts) if len(public[index]["content"]) < min(8000, len(text))}
    while pending and remaining > 0:
        share = remaining // len(pending)
        if share < 1:
            break
        progressed = False
        for index in sorted(pending):
            row, text = public[index], texts[index][:8000]
            before = encoded(row["content"])
            target = before + share
            low, high = len(row["content"]), len(text)
            while low < high:
                middle = (low + high + 1) // 2
                if encoded(text[:middle]) <= target:
                    low = middle
                else:
                    high = middle - 1
            row["content"] = text[:low]
            spent = encoded(row["content"]) - before
            remaining -= spent
            progressed = progressed or spent > 0
        pending = {index for index in pending if len(public[index]["content"]) < min(8000, len(texts[index]))}
        if not progressed:
            break
    warnings = ["Some source excerpts were shortened for this edition; consult the linked originals for full context."] if any(
        len(row["content"]) < len(text) for row, text in zip(public, texts)) else []
    return public, warnings


def edition_fingerprint(edition: dict) -> str:
    frozen = {key: edition.get(key) for key in ("edition_id", "date", "subject", "html", "text", "events")}
    return hashlib.sha256(json.dumps(frozen, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def validate_frozen_edition(edition: dict, date: str) -> None:
    if edition.get("date") != date or edition.get("edition_id") != "levyquant-morning-" + date:
        raise ConfigurationError("Stored edition does not belong to the current New York date")
    if not all(isinstance(edition.get(key), str) and edition[key].strip() for key in ("subject", "html", "text")):
        raise ConfigurationError("Stored edition is incomplete")
    if edition.get("content_sha256") != edition_fingerprint(edition):
        raise ConfigurationError("Stored edition content changed; delivery is blocked")
    if not isinstance(edition.get("deliveries"), dict):
        raise ConfigurationError("Stored delivery records are invalid")


def claim_run_date(store, environment: dict, date: str, now: datetime) -> None:
    """A GitHub re-run keeps its original run ID, including on later days."""
    run_id = environment.get("GITHUB_RUN_ID", "")
    if not re.fullmatch(r"[0-9]+", run_id):
        raise ConfigurationError("Live delivery requires the GitHub run identity")
    path = "runs/" + run_id + ".json"
    previous = store.load(path)
    if previous is not None:
        if previous.get("date") != date:
            raise ConfigurationError("This GitHub run belongs to another edition date; start a new run instead")
        return
    if environment.get("GITHUB_RUN_ATTEMPT", "1") != "1":
        raise ConfigurationError("The original run date is unavailable; start a new run instead of replaying an old run")
    store.save(path, {"date": date, "created_at": now.isoformat()})


def deliver_edition(store, path: str, edition: dict, recipients: list[str], *, sender: str,
                    password: str, execution_id: str, transport=None) -> dict:
    """Persist a claim before each attempt; do not replay ambiguous results."""
    if edition.get("mode") != "live" or edition.get("validated") is not True:
        raise ConfigurationError("Only a validated live edition may be delivered")
    current_date = datetime.now(timezone.utc).astimezone(ZoneInfo("America/New_York")).date().isoformat()
    validate_frozen_edition(edition, current_date)
    if path != "editions/" + current_date + ".json":
        raise ConfigurationError("Delivery state path does not match the current edition")
    transport = transport or send_one
    recipients = recipients_from(json.dumps(recipients))
    # Validate every envelope before a reservation or SMTP connection is made.
    messages = [(address, prepare_message(edition["subject"], edition["html"], edition["text"],
                                         sender, address, edition["edition_id"])) for address in recipients]
    delivery = edition.setdefault("deliveries", {})
    blocked = 0
    for address, message in messages:
        if datetime.now(timezone.utc).astimezone(ZoneInfo("America/New_York")).date().isoformat() != current_date:
            raise ConfigurationError("The New York edition date changed during delivery; further submissions are blocked")
        key = recipient_key(address)
        previous = delivery.get(key, {})
        if previous.get("status") == "accepted":
            continue
        if previous and not (previous.get("status") == "rejected" and previous.get("retry_safe") is True):
            blocked += 1
            continue
        reservation = {"status": "reserved", "execution_id": execution_id,
                       "message_id": message["Message-ID"],
                       "reserved_at": datetime.now(timezone.utc).isoformat()}
        delivery[key] = reservation
        store.save(path, edition)  # A failed acknowledgement stops before SMTP.
        try:
            receipt = transport(message, username=sender, password=password)
        except DeliveryUncertain as error:
            reservation.update({"status": "uncertain", "stage": error.stage, "smtp_code": error.smtp_code})
            store.save(path, edition)
            blocked += 1
        except DeliveryError as error:
            reservation.update({"status": "rejected", "retry_safe": error.retry_safe is True,
                                "stage": error.stage, "smtp_code": error.smtp_code})
            store.save(path, edition)
            blocked += 1
        else:
            if not isinstance(receipt, dict) or receipt.get("status") != "accepted":
                reservation["status"] = "uncertain"
                blocked += 1
            else:
                reservation.update({"status": "accepted", "accepted_at": datetime.now(timezone.utc).isoformat(),
                                    "smtp_code": receipt.get("smtp_code")})
            store.save(path, edition)
    result = {"recipient_count": len(recipients),
              "accepted": sum(delivery.get(recipient_key(a), {}).get("status") == "accepted" for a in recipients),
              "blocked_or_failed": blocked}
    return result


def run(config: dict, mode: str, environment: dict, output: Path) -> dict:
    config = dict(config)
    config["sender"] = environment.get("SMTP_USERNAME") or config.get("sender")
    recipients = preflight(config, mode, environment)
    now = datetime.now(timezone.utc)
    date = now.astimezone(ZoneInfo(config["timezone"])).date().isoformat()
    output.mkdir(parents=True, exist_ok=True)
    if mode == "smtp-test":
        sender = config["sender"]
        message = prepare_message("[TEST] LevyQuant cloud SMTP connection",
            "<p>LevyQuant cloud SMTP connection test. This is not a daily news digest.</p>",
            "LevyQuant cloud SMTP connection test. This is not a daily news digest.",
            sender, sender, "smtp-test-" + environment.get("GITHUB_RUN_ID", now.isoformat()))
        receipt = send_one(message, username=sender, password=environment["SMTP_APP_PASSWORD"])
        return {"mode": mode, "status": receipt["status"], "test_to_sender_only": True}

    if mode == "send":
        store = GitHubStateStore(environment["GITHUB_REPOSITORY"], environment["GITHUB_TOKEN"],
                                 encryption_key=environment["STATE_ENCRYPTION_KEY"])
        store.ensure_state_branch()
        claim_run_date(store, environment, date, now)
    else:
        store = LocalStateStore(output / "preview-state")
    edition_path = "editions/" + date + ".json"
    edition = store.load(edition_path)
    if edition is not None:
        validate_frozen_edition(edition, date)
        if edition.get("mode") != ("live" if mode == "send" else "preview"):
            raise ConfigurationError("Stored edition mode does not match this run")
    history = store.load("history.json") or {"events": []}
    if edition is None:
        sources = read_json(ROOT / config["source_manifest"])["sources"]
        articles, warnings = collect_sources(sources, since=now - timedelta(hours=config["lookback_hours"]),
                                            until=now, timeout=config["fetch_timeout_seconds"],
                                            max_per_source=config["max_items_per_source"])
        if not articles and len(warnings) >= len([s for s in sources if s.get("enabled", True)]):
            raise ConfigurationError("All configured sources are unavailable or unusable; no digest will be sent")
        previous_ids = {item.get("id") for item in history["events"]}
        articles = [article for article in articles if article["id"] not in previous_ids]
        articles, enrichment_warnings = enrich_articles(articles, timeout=config["fetch_timeout_seconds"],
                                                       max_articles=config["max_enriched_articles"])
        public, context_warnings = build_public_inputs(articles, config["max_source_characters"])
        # User-facing notices describe coverage. Detailed network failures stay
        # local to the private workflow output, without recipient names or keys.
        notices = list(config["coverage_notices"])
        if warnings or enrichment_warnings:
            notices.append("Some sources or linked pages could not be retrieved; available official excerpts were used.")
        notices.extend(context_warnings)
        prompt = (ROOT / "agent.prompt.md").read_text(encoding="utf-8")
        prompt += ("\nConfirmed runtime settings: write the full sectioned digest in English; retain original Chinese titles. "
                   "Combine reports on the same event across sections. Explain substantive updates to events in sent_history. "
                   "These inputs have no independently verified financial-number records or confirmed event-time records: "
                   "omit financial figures and calendar claims that require those records; never infer estimates or dates. "
                   "An abstract supports only a description of the authors' stated research, not a replication or investment conclusion.")
        if public:
            editor = generate_editor(public, api_key=environment["GEMINI_API_KEY"], model=config["model"],
                                     prompt=prompt, history=history["events"], max_output_tokens=config["max_output_tokens"])
            digest = editor_to_digest(editor, public, date=date, cutoff=now.isoformat(),
                                      language="en", mode="live", edition=config["edition"], coverage_warnings=notices)
            if not isinstance(digest, dict) or not isinstance(digest.get("sections"), list) or digest.get("mode") != "live":
                raise ConfigurationError("Editorial adapter returned an invalid digest contract")
            digest["title"] = config["title"]
        else:
            digest = {"title": config["title"], "edition": config["edition"], "date": date,
                      "cutoff": now.isoformat(), "language": "en", "mode": "live", "sections": [],
                      "coverage_warnings": notices + ["No new eligible items in the configured official sources for this edition."]}
        html, text = render_digest(digest, public)
        cited = {identifier for section in digest.get("sections", []) for item in section.get("items", [])
                 for identifier in item.get("source_ids", [])}
        events = [{"id": a["canonical_id"], "title": a["title"], "summary": (a["summary"] or a["content"])[:600], "date": date}
                  for a in public if a["id"] in cited]
        edition = {"edition_id": "levyquant-morning-" + date, "date": date,
                   "mode": "live" if mode == "send" else "preview", "validated": True,
                   "subject": "LevyQuant Daily News Digest — Morning Edition, " + date,
                   "html": html, "text": text, "events": events, "deliveries": {},
                   "created_at": now.isoformat(), "source_count": len(sources), "article_count": len(public),
                   "section_count": len(digest.get("sections", [])),
                   "warnings": warnings + enrichment_warnings}
        edition["content_sha256"] = edition_fingerprint(edition)
        store.save(edition_path, edition)
    (output / "email-preview.html").write_text(edition["html"], encoding="utf-8")
    (output / "email-preview.txt").write_text(edition["text"], encoding="utf-8")
    if mode == "preview":
        return {"mode": mode, "status": "preview_ready_no_mail_sent", "date": date,
                "article_count": edition["article_count"], "section_count": edition["section_count"]}
    if mode == "preview-email":
        sender = config["sender"]
        message = prepare_message("[PREVIEW] " + edition["subject"], edition["html"], edition["text"],
                                  sender, sender, "preview-" + environment.get("GITHUB_RUN_ID", now.isoformat()))
        receipt = send_one(message, username=sender, password=environment["SMTP_APP_PASSWORD"])
        return {"mode": mode, "status": "preview_email_" + receipt["status"], "date": date,
                "test_to_sender_only": True, "article_count": edition["article_count"],
                "section_count": edition["section_count"]}
    receipt = deliver_edition(store, edition_path, edition, recipients, sender=config["sender"],
                              password=environment["SMTP_APP_PASSWORD"],
                              execution_id=environment.get("GITHUB_RUN_ID", "manual"))
    # At least one durable acceptance is sufficient to remember that these
    # public stories have appeared; an incomplete edition remains frozen for reruns.
    if receipt["accepted"]:
        cutoff = (now - timedelta(days=config["history_days"])).date().isoformat()
        current = {item["id"]: item for item in history["events"] if item.get("date", "") >= cutoff}
        current.update({item["id"]: item for item in edition["events"]})
        history["events"] = list(current.values())[-1000:]
        store.save("history.json", history)
    status = "all_submissions_accepted" if receipt["accepted"] == len(recipients) else "delivery_needs_attention"
    return {"mode": mode, "status": status, "date": date, **receipt}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("preview", "preview-email", "send", "smtp-test"), default="preview")
    parser.add_argument("--config", type=Path, default=ROOT / "config/cloud.json")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs")
    args = parser.parse_args(argv)
    args.output.mkdir(parents=True, exist_ok=True)
    try:
        result = run(read_json(args.config), args.mode, dict(os.environ), args.output)
    except Exception as error:
        # Controlled module errors are scrubbed; avoid repr/tracebacks containing
        # request objects, HTTP headers, provider bodies or recipient addresses.
        known = isinstance(error, (ConfigurationError, EditorError, StateError))
        message = str(error) if known else "Execution failed; inspect configuration and provider availability."
        for key, value in os.environ.items():
            if value and re.search(r"TOKEN|PASSWORD|KEY|RECIPIENTS|USERNAME", key, re.I):
                message = message.replace(value, "[redacted]")
        message = re.sub(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+", "[email redacted]", message)
        message = re.sub(r"(?i)Bearer\s+\S+|(?:api[_ -]?key|token|password|authorization)\s*[:=]\s*\S+", "[credential redacted]", message)
        message = re.sub(r"https?://\S+", "[URL omitted]", message)
        message = " ".join(message.split())[:500]
        result = {"mode": args.mode, "status": "failed", "error_type": type(error).__name__, "message": message}
    (args.output / "run-summary.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    lines = ["# LevyQuant daily digest", "", *[f"- {key}: {value}" for key, value in result.items()]]
    (args.output / "run-summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 1 if result["status"] in ("failed", "delivery_needs_attention") else 0


if __name__ == "__main__":
    raise SystemExit(main())
