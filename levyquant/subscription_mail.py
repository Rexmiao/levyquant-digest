"""Send reserved subscription links and admin codes; never log private data."""
from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from hashlib import sha256
import json
import os
import re
from urllib.parse import parse_qs, urlsplit

from .smtp_delivery import (DeliveryError, DeliveryUncertain, mail_settings_from_env, mail_transport, prepare_message,
                            send_one, send_with)
from .subscriptions import REPOSITORY, SubscriptionError, service_from_env, validate_email


_IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_SMTP_STAGES = frozenset({"validation", "connect", "greeting", "auth", "mail", "sender", "recipient", "data"})
ADMIN_SUBJECT = "Your LévyQuant administrator sign-in code"


def admin_service_from_env(environment):
    # Keep existing injected subscription-only callers isolated from remote
    # administrator state. Production callers without injections use both.
    from .admin_auth import service_from_env as factory
    return factory(environment)


def _submit(transport, message, sender, password):
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
    return (status, stage if isinstance(stage, str) and stage in _SMTP_STAGES else None,
            code if type(code) is int and 100 <= code <= 599 else None)


def _login_claim(value, identifier):
    if (not isinstance(value, dict)
            or set(value) != {"id", "email", "code", "expires_at", "reservation_id"}
            or value.get("id") != identifier
            or not isinstance(value.get("reservation_id"), str)
            or not _IDENTIFIER.fullmatch(value["reservation_id"])
            or not isinstance(value.get("code"), str)
            or not re.fullmatch(r"[0-9]{6}", value["code"])
            or not isinstance(value.get("expires_at"), str)
            or len(value["expires_at"]) > 64):
        raise SubscriptionError("Invalid reserved administrator message")
    recipient = validate_email(value["email"])
    try:
        expires = datetime.fromisoformat(value["expires_at"].replace("Z", "+00:00"))
        if expires.tzinfo is None or expires.utcoffset() is None:
            raise ValueError
        expires = expires.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        raise SubscriptionError("Invalid administrator message expiry") from None
    return recipient, expires


def _send_admin_codes(service, transport, sender, password, counts):
    pending = service.pending_login_messages(limit=10)
    if (not isinstance(pending, list) or len(pending) > 10
            or any(not isinstance(row, dict) or set(row) != {"id"}
                   or not isinstance(row.get("id"), str) or not _IDENTIFIER.fullmatch(row["id"])
                   for row in pending)):
        raise SubscriptionError("Invalid bounded administrator queue")
    for row in pending:
        claimed = service.claim_login_message(row["id"])
        if claimed is None:
            counts["skipped"] += 1
            continue
        # The service must persist and reread its reservation before returning
        # a recipient/code. A crash or an unknown outcome stays non-replayable.
        recipient, expires = _login_claim(claimed, row["id"])
        if datetime.now(timezone.utc) >= expires:
            counts["skipped"] += 1
            continue
        text = ("Your LévyQuant administrator sign-in code is:\n\n" + claimed["code"]
                + "\n\nThis code expires 10 minutes after it was requested. "
                "Do not forward or share this code. If you did not request it, ignore this message.\n")
        html = ("<p>Your LévyQuant administrator sign-in code is:</p><p><strong>"
                + claimed["code"] + "</strong></p><p>This code expires 10 minutes after it was requested. "
                "Do not forward or share this code. If you did not request it, ignore this message.</p>")
        identity = sha256((claimed["id"] + "\0" + claimed["reservation_id"]).encode("ascii")).hexdigest()
        message = prepare_message(ADMIN_SUBJECT, html, text, sender, recipient, "admin-login-" + identity)
        status, stage, code = _submit(transport, message, sender, password)
        service.mark_login_message(claimed["id"], status, reservation_id=claimed["reservation_id"],
                                   stage=stage, smtp_code=code)
        counts[status] += 1


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


def run(environment: dict | None = None, *, service=None, transport=None, admin_service=None) -> dict:
    environment = dict(os.environ if environment is None else environment)
    subscriptions_enabled = environment.get("SUBSCRIPTIONS_ENABLED", "").lower() == "true"
    production = service is None and admin_service is None
    transport_name = mail_transport(environment)
    if production and transport_name != "gmail":
        # A requested non-Gmail transport must be complete: fail loudly rather than
        # reporting "disabled" while administrator codes silently stop.
        try:
            mail_settings_from_env(environment)
        except DeliveryError:
            raise SubscriptionError("Mail transport settings are missing or invalid for queued delivery") from None
    remote_configured = (all(environment.get(name) for name in (
        "GITHUB_REPOSITORY", "GITHUB_TOKEN", "STATE_ENCRYPTION_KEY", "SMTP_USERNAME"))
        and bool(environment.get("SES_SMTP_PASSWORD") if transport_name == "ses" else environment.get("SMTP_APP_PASSWORD")))
    if (not subscriptions_enabled and admin_service is None
            and (not production or not remote_configured)):
        return {"status": "disabled", "accepted": 0, "rejected": 0, "uncertain": 0, "skipped": 0}
    if environment.get("GITHUB_REPOSITORY") != REPOSITORY:
        raise SubscriptionError("Queued delivery is restricted to the intended repository")
    try:
        # Gmail by default; Amazon SES only when MAIL_TRANSPORT=ses is fully configured.
        mail = mail_settings_from_env(environment)
    except DeliveryError:
        raise SubscriptionError("Mail transport settings are missing or invalid for queued delivery") from None
    sender = validate_email(mail.from_address)
    password = mail.password
    if subscriptions_enabled and service is None and production:
        service = service_from_env(environment)
    if admin_service is None and production:
        admin_service = admin_service_from_env(environment)
    if transport is None:
        transport = send_one if mail.transport == "gmail" else (
            lambda message, *, username, password: send_with(message, mail))
    counts = {"accepted": 0, "rejected": 0, "uncertain": 0, "skipped": 0}
    # Ten-minute codes should not wait behind a batch of 48-hour confirmations.
    if admin_service is not None:
        _send_admin_codes(admin_service, transport, sender, password, counts)
    pending = service.pending_confirmations(limit=20) if subscriptions_enabled and service is not None else []
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
        introduction = "This email address was entered on the LévyQuant subscription page."
        description = ("LévyQuant sends a morning briefing on macroeconomics, U.S. equities and "
                       "quantitative research, around 7 a.m. New York time.")
        instruction = "To subscribe, open the page below and select Confirm."
        expiry_and_choice = ("This link expires 48 hours after the request. "
                             "If you did not request this, ignore this email. "
                             "No subscription will start unless you confirm.")
        html = (
            "<p>" + introduction + "</p><p>" + description + "</p><p>" + instruction + "</p>"
            '<p><a href="' + escape(url, quote=True) + '">Review and confirm subscription</a></p>'
            "<p>" + expiry_and_choice + "</p>"
            '<p style="font-size:12px;color:#5f6368;">LévyQuant &middot; ' + escape(sender, quote=True) + "</p>"
        )
        text = "\n\n".join((introduction, description, instruction,
                               "Review and confirm subscription:\n" + url,
                               expiry_and_choice, "LévyQuant · " + sender)) + "\n"
        message = prepare_message("Confirm your LévyQuant subscription", html, text, sender, recipient,
                                  "subscription-confirm-" + claimed["id"] + "-" + claimed["reservation_id"])
        status, stage, code = _submit(transport, message, sender, password)
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
