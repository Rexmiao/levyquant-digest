"""Cloud entry point. Preview is default; delivery requires explicit enabling."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import date as CalendarDate, datetime, timedelta, timezone
from html import escape
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from zoneinfo import ZoneInfo

from .editor import EditorError, editor_to_digest, generate_editor
from .delivery_reports import COUNT_FIELDS, ERROR_TYPES, RESULT_CODES, record_run_report, summarize_edition
from .feeds import DIAGNOSTIC_STATUSES, collect_sources
from .render import RECIPIENT_FOOTER_SLOT, _safe_url, render_digest
from .smtp_delivery import DeliveryError, DeliveryUncertain, prepare_message, send_one
from .archive import publish_edition
from .sources import enrich_articles
from .source_settings import (
    MOOMOO_SOURCE_ID, default_moomoo_queries, read_moomoo_settings, validate_moomoo_snapshot,
)
from .state_store import GitHubStateStore, LocalStateStore, StateError
from .state_store import StateConflict
from .subscriptions import REPOSITORY, SubscriptionService, validate_public_base_url

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


def _briefing_subject(date: str) -> str:
    months = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")
    try:
        moment = CalendarDate.fromisoformat(date)
        if moment.isoformat() != date:
            raise ValueError
    except (ValueError, TypeError):
        raise ConfigurationError("A valid briefing date is required") from None
    return f"LevyQuant Morning Briefing — {months[moment.month - 1]} {moment.day}, {moment.year}"


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
        validate_public_base_url(environment.get("DIGEST_PUBLIC_BASE_URL", ""))
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
        row.update({key: article[key] for key in ("media_type", "date_basis") if key in article})
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


def build_coverage_notices(base: list[str], cited_articles: list[dict], *,
                           source_gaps: bool = False, shortened: bool = False,
                           extra_notices: list[str] | None = None) -> list[str]:
    """Describe actual cited material once; retain real processing exceptions."""
    if not isinstance(base, list) or any(not isinstance(note, str) for note in base):
        raise ConfigurationError("Coverage notices must be a list of text")
    scopes = {article.get("content_scope") for article in cited_articles}
    limits = []
    if "rss_metadata_and_feed_excerpt" in scopes:
        limits.append("Publisher feed excerpts are used without reading linked article bodies.")
    if ("search_headline_and_link" in scopes
            or any(article.get("media_type") == "headline_only" for article in cited_articles)):
        limits.append("Search inputs provide headlines and links only.")
    if ("podcast_episode_description" in scopes
            or any(article.get("media_type") == "podcast" for article in cited_articles)):
        limits.append("Podcasts use episode descriptions; audio and transcripts were not reviewed.")
    if ("official_abstract" in scopes
            or any(article.get("section") == "quant_research" for article in cited_articles)):
        limits.append("Research summaries use abstracts or publication notices, not full-paper reviews or replications.")
    notices = list(base)
    if limits:
        notices.append(" ".join(limits))
    if source_gaps and shortened:
        notices.append("Some source items or dates were unavailable; some excerpts were shortened.")
    elif source_gaps:
        notices.append("Some source items or dates were unavailable.")
    elif shortened:
        notices.append("Some source excerpts were shortened; consult the linked originals for full context.")
    notices.extend(extra_notices or [])
    result, seen = [], set()
    for notice in notices:
        text = " ".join(notice.split())
        if text and text.casefold() not in seen:
            seen.add(text.casefold())
            result.append(text)
    return result


def source_diagnostics(sources: list[dict], reports: list[dict]) -> list[dict]:
    """Validate per-source collection outcomes and retain only public metadata."""
    if len(reports) != len(sources):
        raise ConfigurationError("Source diagnostics are incomplete; no digest will be sent")
    public = []
    for index, (source, report) in enumerate(zip(sources, reports)):
        enabled = bool(source.get("enabled", True))
        identifier = str(source.get("id") or f"source_{index + 1}")
        status = report.get("status") if isinstance(report, dict) else None
        if (status not in DIAGNOSTIC_STATUSES or report.get("enabled") is not enabled
                or report.get("id") != identifier or (status == "disabled") == enabled):
            raise ConfigurationError("Source diagnostics are invalid; no digest will be sent")
        counts = {key: report.get(key, 0) for key in (
            "parsed", "dated", "eligible", "selected", "unknown_dates", "future_dated")}
        if (any(type(value) is not int or value < 0 for value in counts.values())
                or not counts["selected"] <= counts["eligible"] <= counts["dated"] <= counts["parsed"]
                or counts["unknown_dates"] > counts["parsed"] or counts["future_dated"] > counts["dated"]):
            raise ConfigurationError("Source diagnostic counts are invalid; no digest will be sent")
        latest = report.get("latest_published")
        if latest is not None:
            try:
                moment = datetime.fromisoformat(latest) if isinstance(latest, str) else None
                if moment is None or moment.tzinfo is None or moment.utcoffset() is None:
                    raise ValueError
            except (ValueError, TypeError, OverflowError):
                raise ConfigurationError("Source diagnostic timestamps are invalid; no digest will be sent") from None
        public.append({"id": identifier,
                       "name": str(source.get("name") or source.get("id") or f"Source {index + 1}"),
                       "enabled": enabled, "status": status, **counts, "latest_published": latest})
    return public


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
                    password: str, execution_id: str, transport=None, subscription_service=None,
                    internal_recipients: list[str] | None = None) -> dict:
    """Reserve, recheck opt-outs, then submit once; preserve ambiguous outcomes."""
    if edition.get("mode") != "live" or edition.get("validated") is not True:
        raise ConfigurationError("Only a validated live edition may be delivered")
    current_date = datetime.now(timezone.utc).astimezone(ZoneInfo("America/New_York")).date().isoformat()
    validate_frozen_edition(edition, current_date)
    if path != "editions/" + current_date + ".json":
        raise ConfigurationError("Delivery state path does not match the current edition")
    transport = transport or send_one
    version = edition.get("copy_version", 1)
    if type(version) is not int or version not in (1, 2):
        raise ConfigurationError("Stored edition copy version is unsupported")
    if version == 2 and edition["html"].count(RECIPIENT_FOOTER_SLOT) != 1:
        raise ConfigurationError("The personalized footer slot is missing or duplicated")
    recipients = recipients_from(json.dumps(recipients))
    internal = recipients_from(json.dumps(internal_recipients)) if internal_recipients else []
    internal_keys = {address.casefold() for address in internal}
    delivery = edition.setdefault("deliveries", {})
    known_statuses = {"accepted", "rejected", "uncertain", "reserved", "skipped_unsubscribed"}
    if any(not isinstance(row, dict) or row.get("status") not in known_statuses for row in delivery.values()):
        raise ConfigurationError("Stored delivery status is unsupported; further submissions are blocked")
    planned = set(delivery) | {recipient_key(address) for address in recipients}
    if len(planned) > 100:
        raise ConfigurationError("More than 100 edition recipients requires a reviewed mailing setup")
    internal_hashes = {recipient_key(address) for address in internal}
    already_accepted = sum(row.get("status") == "accepted" for row in delivery.values())
    # Check all envelopes before any attempt; personalized headers are added
    # only for recipients still eligible in the loop below.
    messages = {address: prepare_message(edition["subject"], edition["html"], edition["text"],
                sender, address, edition["edition_id"]) for address in recipients}

    def persist():
        counts = {status: sum(delivery.get(key, {}).get("status") == status for key in planned)
                  for status in ("accepted", "rejected", "uncertain", "reserved", "skipped_unsubscribed")}
        counts.update(recipient_count=len(planned), pending=sum(key not in delivery for key in planned),
                      internal_count=len(planned & internal_hashes), already_accepted=already_accepted)
        edition["delivery_summary"] = counts
        store.save(path, edition)

    def allowed(address):
        if address.casefold() in internal_keys or subscription_service is None:
            return True
        result = subscription_service.is_delivery_allowed(address, internal)
        if type(result) is not bool:
            raise StateError("Delivery eligibility could not be verified")
        return result

    def skip(key):
        delivery[key] = {"status": "skipped_unsubscribed", "reason": "subscription_not_allowed",
                         "execution_id": execution_id, "skipped_at": datetime.now(timezone.utc).isoformat()}
        persist()

    persist()
    for address in recipients:
        if datetime.now(timezone.utc).astimezone(ZoneInfo("America/New_York")).date().isoformat() != current_date:
            raise ConfigurationError("The New York edition date changed during delivery; further submissions are blocked")
        key = recipient_key(address)
        previous = delivery.get(key, {})
        if previous.get("status") == "accepted":
            continue
        if previous.get("status") == "skipped_unsubscribed" and address.casefold() not in internal_keys:
            continue
        if previous.get("status") in ("reserved", "uncertain"):
            continue
        if not allowed(address):
            skip(key)
            continue
        if previous.get("status") == "rejected" and previous.get("retry_safe") is not True:
            continue
        message = messages[address]
        if version == 2:
            if address.casefold() in internal_keys:
                kind = "internal"
            elif subscription_service is None:
                raise StateError("The recipient authorization source could not be verified")
            else:
                kind = subscription_service.delivery_recipient_kind(address, internal)
            if kind == "blocked":
                skip(key)
                continue
            reasons = {"internal": "Operator archive copy",
                       "confirmed": "This briefing is sent because you confirmed a LevyQuant subscription.",
                       "authorized": "This briefing is sent to an address on LevyQuant’s authorized mailing list."}
            if not isinstance(kind, str) or kind not in reasons:
                raise StateError("The recipient authorization source could not be verified")
            reason = reasons[kind]
            personal = '<div data-digest-block="recipient" style="margin-top:12px;"><p style="margin:0 0 5px;">' + escape(reason) + '</p>'
            text_footer, one_click = "\n\n" + reason + "\n", None
            if kind != "internal":
                url = subscription_service.unsubscribe_url(address)
                if not _safe_url(url):
                    raise StateError("The recipient unsubscribe link could not be verified")
                one_click = subscription_service.one_click_unsubscribe_url(address)
                personal += '<p style="margin:0;"><a href="' + escape(url, quote=True) + '">Unsubscribe from LevyQuant</a></p>'
                text_footer += "Unsubscribe from LevyQuant:\n" + url + "\n"
            personal += '</div>'
            message = prepare_message(edition["subject"], edition["html"].replace(RECIPIENT_FOOTER_SLOT, personal),
                edition["text"].rstrip() + text_footer, sender, address, edition["edition_id"], unsubscribe_url=one_click)
        elif subscription_service is not None and address.casefold() not in internal_keys:
            url = subscription_service.unsubscribe_url(address)
            one_click = subscription_service.one_click_unsubscribe_url(address)
            footer = ('<hr><p style="font-size:12px;color:#5f6368;">'
                      '<a href="' + escape(url, quote=True) + '">Manage or unsubscribe from the mailing list</a></p>')
            html_body, text_body = edition["html"], edition["text"]
            closing = html_body.lower().rfind("</body>")
            html_body = html_body[:closing] + footer + html_body[closing:] if closing >= 0 else html_body + footer
            text_body += "\n\nManage or unsubscribe from the mailing list:\n" + url + "\n"
            message = prepare_message(edition["subject"], html_body, text_body, sender, address,
                                      edition["edition_id"], unsubscribe_url=one_click)
        reservation = {"status": "reserved", "execution_id": execution_id,
                       "message_id": message["Message-ID"],
                       "reserved_at": datetime.now(timezone.utc).isoformat()}
        delivery[key] = reservation
        persist()  # A failed acknowledgement stops before SMTP.
        if not allowed(address):
            skip(key)
            continue
        try:
            receipt = transport(message, username=sender, password=password)
        except DeliveryUncertain as error:
            reservation.update({"status": "uncertain", "stage": error.stage, "smtp_code": error.smtp_code})
            persist()
        except DeliveryError as error:
            reservation.update({"status": "rejected", "retry_safe": error.retry_safe is True,
                                "stage": error.stage, "smtp_code": error.smtp_code})
            persist()
        else:
            if not isinstance(receipt, dict) or receipt.get("status") != "accepted":
                reservation["status"] = "uncertain"
            else:
                reservation.update({"status": "accepted", "accepted_at": datetime.now(timezone.utc).isoformat(),
                                    "smtp_code": receipt.get("smtp_code")})
            persist()
    persist()
    summary = edition["delivery_summary"]
    return {**summary, "blocked_or_failed": sum(summary[key] for key in ("rejected", "uncertain", "reserved", "pending"))}


def publish_latest(store, edition: dict) -> None:
    """Publish only the unpersonalized public edition, with bounded CAS retries."""
    validate_frozen_edition(edition, edition.get("date"))
    if (edition.get("mode") != "live" or edition.get("validated") is not True
            or not any(isinstance(record, dict) and record.get("status") == "accepted"
                       for record in edition["deliveries"].values())):
        raise ConfigurationError("Only a validated live edition with accepted delivery can be published")
    value = {key: edition[key] for key in ("subject", "date", "html", "text")}
    publish_edition(store, value)
    for attempt in range(3):
        current = store.load("public/latest.json")
        if current == value or (isinstance(current, dict) and current.get("date", "") > value["date"]):
            return
        try:
            store.save("public/latest.json", value)
            return
        except StateConflict:
            if attempt == 2:
                raise


def run(config: dict, mode: str, environment: dict, output: Path, *, moomoo_settings=None) -> dict:
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

    subscription_service = None
    if mode == "send":
        store = GitHubStateStore(environment["GITHUB_REPOSITORY"], environment["GITHUB_TOKEN"],
                                 encryption_key=environment["STATE_ENCRYPTION_KEY"])
        store.ensure_state_branch()
        claim_run_date(store, environment, date, now)
        subscription_service = SubscriptionService(store, environment["STATE_ENCRYPTION_KEY"],
                                                   environment["DIGEST_PUBLIC_BASE_URL"], now=now)
        subscribers = recipients_from(environment["DIGEST_RECIPIENTS"])
        internal = recipients_from(environment["DIGEST_INTERNAL_RECIPIENTS"])
        eligible = subscription_service.delivery_recipients(subscribers, internal,
            include_public_subscribers=environment.get("SUBSCRIPTIONS_ENABLED", "").lower() == "true")
        # Retain legacy opt-outs as planned skips for an honest edition audit.
        recipients = recipients_from(json.dumps(internal + subscribers + eligible))
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
        sources = deepcopy(read_json(ROOT / config["source_manifest"])["sources"])
        snapshot = validate_moomoo_snapshot(moomoo_settings) if moomoo_settings is not None else None
        settings_revision = 0
        if any(source.get("id") == MOOMOO_SOURCE_ID for source in sources):
            defaults = default_moomoo_queries(sources)
            if mode == "send":
                settings = read_moomoo_settings(store, defaults)
            elif snapshot is not None:
                settings = snapshot
            else:
                remote_fields = ("GITHUB_REPOSITORY", "GITHUB_TOKEN", "STATE_ENCRYPTION_KEY")
                configured = [bool(environment.get(key)) for key in remote_fields]
                if any(configured) and not all(configured):
                    raise ConfigurationError("Shared Moomoo settings require complete remote state configuration")
                if all(configured):
                    settings_store = GitHubStateStore(environment["GITHUB_REPOSITORY"], environment["GITHUB_TOKEN"],
                                                     encryption_key=environment["STATE_ENCRYPTION_KEY"])
                    settings_store.ensure_state_branch()
                    settings = read_moomoo_settings(settings_store, defaults)
                else:
                    settings = {"queries": defaults, "revision": 0}
            settings_revision = settings["revision"]
            for source in sources:
                if source.get("id") == MOOMOO_SOURCE_ID:
                    source["queries"] = list(settings["queries"])
        elif snapshot is not None:
            raise ConfigurationError("The fixed Moomoo source is not configured")
        reports = []
        articles, warnings = collect_sources(sources, since=now - timedelta(hours=config["lookback_hours"]),
                                            until=now, timeout=config["fetch_timeout_seconds"],
                                            max_per_source=config["max_items_per_source"], diagnostics=reports)
        reports = source_diagnostics(sources, reports)
        enabled_reports = [report for report in reports if report["enabled"]]
        successful_sources = sum(report["status"] in {"ok", "no_new_items", "empty_feed"}
                                 for report in enabled_reports)
        if not enabled_reports or not successful_sources:
            raise ConfigurationError("All enabled sources are unavailable or unusable; no digest will be sent")
        previous_ids = {item.get("id") for item in history["events"]}
        articles = [article for article in articles if article["id"] not in previous_ids]
        articles, enrichment_warnings = enrich_articles(articles, timeout=config["fetch_timeout_seconds"],
                                                       max_articles=config["max_enriched_articles"])
        public, context_warnings = build_public_inputs(articles, config["max_source_characters"])
        # User-facing notices describe coverage. Detailed network failures stay
        # local to the private workflow output, without recipient names or keys.
        notices = list(config["coverage_notices"])
        prompt = (ROOT / "agent.prompt.md").read_text(encoding="utf-8")
        prompt += ("\nConfirmed runtime settings: write the full sectioned digest in English; retain original Chinese titles. "
                   "Combine reports on the same event across sections. Explain substantive updates to events in sent_history. "
                   "These inputs have no independently verified financial-number records or confirmed event-time records: "
                   "omit financial figures and calendar claims that require those records; never infer estimates or dates. "
                   "An abstract supports only a description of the authors' stated research, not a replication or investment conclusion. "
                   "Podcast show notes or episode descriptions support only those published descriptions; audio has not been listened to or transcribed.")
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
                      "coverage_warnings": notices + ["No new eligible items were available from the configured publisher feeds and selected official sources for this edition."]}
        digest["footer_personalization"] = True
        cited = {identifier for section in digest.get("sections", []) for item in section.get("items", [])
                 for identifier in item.get("source_ids", [])}
        digest["coverage_warnings"] = build_coverage_notices(
            notices, [article for article in public if article["id"] in cited],
            source_gaps=bool(warnings or enrichment_warnings), shortened=bool(context_warnings),
            extra_notices=[note for note in digest.get("coverage_warnings", []) if note not in notices])
        html, text = render_digest(digest, public)
        events = [{"id": a["canonical_id"], "title": a["title"], "summary": (a["summary"] or a["content"])[:600], "date": date}
                  for a in public if a["id"] in cited]
        edition = {"edition_id": "levyquant-morning-" + date, "date": date,
                   "mode": "live" if mode == "send" else "preview", "validated": True,
                   "subject": _briefing_subject(date), "copy_version": 2,
                   "html": html, "text": text, "events": events, "deliveries": {},
                   "created_at": now.isoformat(), "moomoo_settings_revision": settings_revision,
                   "source_count": successful_sources,
                   "configured_source_count": len(sources), "enabled_source_count": len(enabled_reports),
                   "source_diagnostics": reports, "article_count": len(public),
                   "section_count": len(digest.get("sections", [])),
                   "warnings": warnings + enrichment_warnings}
        edition["content_sha256"] = edition_fingerprint(edition)
        store.save(edition_path, edition)
    (output / "email-preview.html").write_text(edition["html"], encoding="utf-8")
    (output / "email-preview.txt").write_text(edition["text"], encoding="utf-8")
    if mode == "preview":
        return {"mode": mode, "status": "preview_ready_no_mail_sent", "date": date,
                "article_count": edition["article_count"], "section_count": edition["section_count"],
                "moomoo_settings_revision": edition.get("moomoo_settings_revision", 0)}
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
                              execution_id=environment.get("GITHUB_RUN_ID", "manual"),
                              subscription_service=subscription_service,
                              internal_recipients=recipients_from(environment["DIGEST_INTERNAL_RECIPIENTS"]) if subscription_service else None)
    # At least one durable acceptance is sufficient to remember that these
    # public stories have appeared; an incomplete edition remains frozen for reruns.
    if receipt["accepted"]:
        publish_latest(store, edition)
        cutoff = (now - timedelta(days=config["history_days"])).date().isoformat()
        current = {item["id"]: item for item in history["events"] if item.get("date", "") >= cutoff}
        current.update({item["id"]: item for item in edition["events"]})
        history["events"] = list(current.values())[-1000:]
        store.save("history.json", history)
    status = "all_submissions_accepted" if receipt["blocked_or_failed"] == 0 else "delivery_needs_attention"
    return {"mode": mode, "status": status, "date": date, **receipt}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("preview", "preview-email", "send", "smtp-test"), default="preview")
    parser.add_argument("--config", type=Path, default=ROOT / "config/cloud.json")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs")
    args = parser.parse_args(argv)
    args.output.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    report_store, report = None, None
    try:
        config = read_json(args.config)
        reporting = (environment.get("GITHUB_ACTIONS", "").lower() == "true"
                     and environment.get("GITHUB_REPOSITORY") == REPOSITORY
                     and isinstance(environment.get("GITHUB_RUN_ID"), str)
                     and re.fullmatch(r"[0-9]{1,32}", environment["GITHUB_RUN_ID"])
                     and all(environment.get(key) for key in ("GITHUB_TOKEN", "STATE_ENCRYPTION_KEY")))
        if reporting:
            checked = {**config, "sender": environment.get("SMTP_USERNAME") or config.get("sender")}
            preflight(checked, args.mode, environment)  # No remote reads for invalid configuration.
            started = datetime.now(timezone.utc)
            report = {"run_id": environment["GITHUB_RUN_ID"], "mode": args.mode,
                      "date": started.astimezone(ZoneInfo("America/New_York")).date().isoformat(),
                      "started_at": started.isoformat(), "updated_at": started.isoformat(),
                      "status": "running", "result_code": "running"}
            try:
                report_store = GitHubStateStore(REPOSITORY, environment["GITHUB_TOKEN"],
                                                encryption_key=environment["STATE_ENCRYPTION_KEY"])
                report_store.ensure_state_branch()
                record_run_report(report_store, report)
            except Exception:
                # Activity reporting is independent of the single delivery
                # attempt and cannot trigger a second SMTP submission.
                pass
        result = run(config, args.mode, environment, args.output)
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
    if report is not None:
        result["run_report_status"] = "unavailable"
        if report_store is not None:
            final = {**report, "updated_at": datetime.now(timezone.utc).isoformat(),
                     "status": "failed" if result["status"] in ("failed", "delivery_needs_attention") else "completed",
                     "result_code": result["status"] if result["status"] in RESULT_CODES else "completed"}
            final.update({key: result[key] for key in COUNT_FIELDS if type(result.get(key)) is int})
            if result["status"] == "failed":
                final.update(error_type=result.get("error_type") if result.get("error_type") in ERROR_TYPES else "Exception",
                             error_code="execution_failed", result_code="failed")
                if args.mode == "send":
                    try:
                        frozen = report_store.load("editions/" + report["date"] + ".json")
                        counts = summarize_edition(frozen)
                        final.update({key: counts[key] for key in COUNT_FIELDS if type(counts.get(key)) is int})
                    except Exception:
                        pass
            try:
                record_run_report(report_store, final)
                result["run_report_status"] = "recorded"
            except Exception:
                pass
    (args.output / "run-summary.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    lines = ["# LevyQuant daily digest", "", *[f"- {key}: {value}" for key, value in result.items()]]
    (args.output / "run-summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 1 if result["status"] in ("failed", "delivery_needs_attention") else 0


if __name__ == "__main__":
    raise SystemExit(main())
