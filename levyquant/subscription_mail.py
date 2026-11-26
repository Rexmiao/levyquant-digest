"""Send queued confirmation links from GitHub; never log their private data."""
from __future__ import annotations

from html import escape
import json
import os
import re
from urllib.parse import parse_qs, urlsplit

from .smtp_delivery import DeliveryError, DeliveryUncertain, prepare_message, send_one
from .subscriptions import REPOSITORY, SubscriptionError, service_from_env, validate_email


def _confirmation_url(value: str, service, identifier: str) -> str:
    if not isinstance(value, str) or any(char.isspace() or ord(char) < 32 for char in value):
        raise SubscriptionError("Invalid private confirmation URL")
    try:
        parsed, expected = urlsplit(value), urlsplit(service.public_base_url)
        parameters = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
        valid = (parsed.scheme == "https" and parsed.netloc == expected.netloc
                 and parsed.username is None and parsed.password is None and parsed.port is None
                 and parsed.path == "/confirm" and not parsed.fragment
                 and set(parameters) == {"id", "token"} and parameters["id"] == [identifier]
                 and len(parameters["token"]) == 1 and re.fullmatch(r"[A-Za-z0-9_-]{43}", parameters["token"][0]))
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise SubscriptionError("Invalid private confirmation URL")
    return value


def run(environment: dict | None = None, *, service=None, transport=None) -> dict:
    environment = dict(os.environ if environment is None else environment)
    if environment.get("SUBSCRIPTIONS_ENABLED", "").lower() != "true":
        return {"status": "disabled", "accepted": 0, "rejected": 0, "uncertain": 0, "skipped": 0}
    if environment.get("GITHUB_REPOSITORY") != REPOSITORY:
        raise SubscriptionError("Confirmation delivery is restricted to the intended repository")
    sender = validate_email(environment.get("SMTP_USERNAME", ""))
    password = environment.get("SMTP_APP_PASSWORD")
    if not isinstance(password, str) or not password.strip():
        raise SubscriptionError("SMTP_APP_PASSWORD is required for confirmation delivery")
    service = service if service is not None else service_from_env(environment)
    transport = transport or send_one
    counts = {"accepted": 0, "rejected": 0, "uncertain": 0, "skipped": 0}
    pending = service.pending_confirmations(limit=20)
    if not isinstance(pending, list) or len(pending) > 20:
        raise SubscriptionError("Invalid bounded confirmation queue")
    for row in pending:
        claimed = service.claim_confirmation(row["id"])
        if claimed is None:
            counts["skipped"] += 1
            continue
        # The service persisted and reread this reservation before exposing a
        # recipient or token. An unexpected exception leaves it reserved.
        recipient = validate_email(claimed["email"])
        url = _confirmation_url(claimed["url"], service, claimed["id"])
        html = (
            "<p>You requested a LevyQuant daily news subscription.</p>"
            '<p><a href="' + escape(url, quote=True) + '">Open the confirmation page</a></p>'
            "<p>Opening the link alone does not subscribe you. Press Confirm on the page to finish. "
            "The link expires after 48 hours. If you did not request this, ignore this message.</p>"
        )
        text = ("You requested a LevyQuant daily news subscription.\n\nOpen the confirmation page:\n" + url
                + "\n\nOpening the link alone does not subscribe you. Press Confirm on the page to finish. "
                "The link expires after 48 hours. If you did not request this, ignore this message.\n")
        message = prepare_message("Confirm your LevyQuant subscription", html, text, sender, recipient,
                                  "subscription-confirm-" + claimed["id"] + "-" + claimed["reservation_id"])
        try:
            receipt = transport(message, username=sender, password=password)
        except DeliveryUncertain as error:
            status, stage, code = "uncertain", error.stage, error.smtp_code
        except DeliveryError as error:
            status, stage, code = "rejected", error.stage, error.smtp_code
        else:
            status = "accepted" if isinstance(receipt, dict) and receipt.get("status") == "accepted" else "uncertain"
            stage = None
            code = receipt.get("smtp_code") if isinstance(receipt, dict) else None
        service.mark_confirmation(claimed["id"], status, reservation_id=claimed["reservation_id"], stage=stage, smtp_code=code)
        counts[status] += 1
    return {"status": "needs_attention" if counts["rejected"] or counts["uncertain"] else "completed", **counts}


def main() -> int:
    try:
        result = run()
    except Exception as error:
        # Never include exception messages: upstream errors can contain headers,
        # recipient addresses, confirmation tokens, or full private URLs.
        result = {"status": "failed", "error_type": type(error).__name__}
    print(json.dumps(result, sort_keys=True))
    return 1 if result["status"] in ("failed", "needs_attention") else 0


if __name__ == "__main__":
    raise SystemExit(main())
