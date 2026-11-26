"""Bounded double-opt-in subscriptions over the encrypted CAS state store."""
from __future__ import annotations

import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import os
import re
import secrets
from urllib.parse import urlencode, urlsplit

from .state_store import GitHubStateStore, StateConflict, StateError


REGISTRY_PATH = "subscriptions/registry.json"
REPOSITORY = "Rexmiao/levyquant-digest"
MAX_RECORDS = 200
MAX_CONFIRMED = 90
MAX_DAILY_CONFIRMATIONS = 50
MAX_CLIENT_HOURLY = 5
CONFIRMATION_TTL = timedelta(hours=48)
_ID = re.compile(r"[A-Za-z0-9_-]{24}\Z")
_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}\Z")
_STATUSES = {"pending", "confirmed", "seeded", "unsubscribed", "suppressed"}
_MAIL_STATUSES = {"queued", "reserved", "accepted", "rejected", "uncertain"}


class SubscriptionError(StateError):
    """A safe configuration/input error; never contains an address or token."""


def validate_email(value: str) -> str:
    if (not isinstance(value, str) or len(value) > 254
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise SubscriptionError("A valid plain email address is required")
    address = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", address):
        raise SubscriptionError("A valid plain email address is required")
    local, domain = address.rsplit("@", 1)
    if (len(local) > 64 or local.startswith(".") or local.endswith(".") or ".." in address
            or any(not part or len(part) > 63 or part.startswith("-") or part.endswith("-") for part in domain.split("."))):
        raise SubscriptionError("A valid plain email address is required")
    return address.casefold()


def validate_public_base_url(value: str) -> str:
    if not isinstance(value, str) or any(char.isspace() or ord(char) < 32 for char in value):
        raise SubscriptionError("A canonical HTTPS hf.space URL is required")
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname or ""
        valid = (parsed.scheme == "https" and parsed.username is None and parsed.password is None
                 and parsed.port is None and parsed.path in ("", "/") and not parsed.query and not parsed.fragment
                 and re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.hf\.space", hostname))
    except ValueError:
        valid = False
    if not valid:
        raise SubscriptionError("A canonical HTTPS hf.space URL is required")
    return "https://" + hostname


def _timestamp(value: object) -> datetime:
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else None
        if moment is None or moment.utcoffset() is None:
            raise ValueError
        return moment.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        raise StateError("Subscription timestamps are invalid") from None


def _decode_key(value: str) -> bytes:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}=?", value):
        raise SubscriptionError("A valid STATE_ENCRYPTION_KEY is required")
    try:
        raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except (ValueError, TypeError):
        raise SubscriptionError("A valid STATE_ENCRYPTION_KEY is required") from None
    if len(raw) != 32 or base64.urlsafe_b64encode(raw).decode().rstrip("=") != value.rstrip("="):
        raise SubscriptionError("A valid STATE_ENCRYPTION_KEY is required")
    return raw


class SubscriptionService:
    def __init__(self, store, signing_key: str, public_base_url: str, now=None):
        self.store = store
        self.public_base_url = validate_public_base_url(public_base_url)
        # HKDF-style extract/expand with independent purpose labels. Tokens do
        # not use the AES encryption key directly as their HMAC signing key.
        root = hmac.new(b"LevyQuant subscription key extract v1", _decode_key(signing_key), hashlib.sha256).digest()
        self._keys = {purpose: hmac.new(root, ("levyquant/" + purpose + "/v1\x01").encode(), hashlib.sha256).digest()
                      for purpose in ("confirm", "unsubscribe", "client-limits")}
        self._clock = now if callable(now) else (lambda: now) if now is not None else (lambda: datetime.now(timezone.utc))
        self.signup_queued = False

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.utcoffset() is None:
            raise SubscriptionError("The subscription clock must be timezone-aware")
        return value.astimezone(timezone.utc)

    def _load(self) -> dict:
        registry = self.store.load(REGISTRY_PATH)
        if registry is None:
            return {"schema_version": 1, "records": {}, "limits": {"date": "", "count": 0, "hour": "", "clients": {}}}
        if (not isinstance(registry, dict) or registry.get("schema_version") != 1
                or not isinstance(registry.get("records"), dict) or len(registry["records"]) > MAX_RECORDS
                or not isinstance(registry.get("limits"), dict)):
            raise StateError("Subscription registry is invalid")
        seen = set()
        for identifier, record in registry["records"].items():
            if (not isinstance(identifier, str) or not _ID.fullmatch(identifier) or not isinstance(record, dict)
                    or record.get("id") != identifier or record.get("status") not in _STATUSES):
                raise StateError("Subscription record is invalid")
            address = validate_email(record.get("email"))
            if address in seen or record.get("email") != address:
                raise StateError("Subscription records contain duplicate or invalid addresses")
            seen.add(address)
            _timestamp(record.get("created_at"))
            if record.get("confirmed_at") is not None:
                _timestamp(record["confirmed_at"])
            if not isinstance(record.get("unsubscribe_nonce"), str) or not _ID.fullmatch(record["unsubscribe_nonce"]):
                raise StateError("Subscription token state is invalid")
            confirmation = record.get("confirmation")
            if confirmation is not None:
                if (not isinstance(confirmation, dict) or confirmation.get("status") not in _MAIL_STATUSES
                        or not isinstance(confirmation.get("nonce"), str) or not _ID.fullmatch(confirmation["nonce"])):
                    raise StateError("Confirmation state is invalid")
                _timestamp(confirmation.get("requested_at"))
                _timestamp(confirmation.get("expires_at"))
                if confirmation["status"] in ("reserved", "accepted", "rejected", "uncertain"):
                    if not isinstance(confirmation.get("reservation_id"), str) or not _ID.fullmatch(confirmation["reservation_id"]):
                        raise StateError("Confirmation reservation is invalid")
            if record["status"] == "pending" and confirmation is None:
                raise StateError("Pending subscription has no confirmation state")
            if any(flag in record and type(record[flag]) is not bool for flag in ("legacy_authorized", "opted_out")):
                raise StateError("Subscription authorization flags are invalid")
        limits = registry["limits"]
        if (not isinstance(limits.get("date"), str) or not isinstance(limits.get("hour"), str)
                or type(limits.get("count")) is not int or limits["count"] < 0
                or not isinstance(limits.get("clients"), dict) or len(limits["clients"]) > MAX_DAILY_CONFIRMATIONS
                or any(not isinstance(key, str) or type(count) is not int or count < 0 for key, count in limits["clients"].items())):
            raise StateError("Subscription rate-limit state is invalid")
        if sum(record["status"] == "confirmed" for record in registry["records"].values()) > MAX_CONFIRMED:
            raise StateError("Confirmed subscription capacity is invalid")
        return registry

    def _mutate(self, change):
        for attempt in range(3):
            registry = self._load()
            result, changed = change(registry)
            if not changed:
                return result
            try:
                self.store.save(REGISTRY_PATH, registry)
                return result
            except StateConflict:
                if attempt == 2:
                    raise
        raise StateConflict("Subscription state remained busy")

    @staticmethod
    def _find(registry: dict, email: str):
        return next((record for record in registry["records"].values() if record["email"] == email), None)

    def _new_record(self, email: str, now: datetime, *, status: str) -> dict:
        return {"id": secrets.token_urlsafe(18), "email": email, "status": status,
                "created_at": now.isoformat(), "confirmed_at": None,
                "unsubscribe_nonce": secrets.token_urlsafe(18), "confirmation": None}

    def _token(self, record: dict, purpose: str) -> str:
        if purpose == "confirm":
            confirmation = record["confirmation"]
            payload = "\x00".join((record["id"], confirmation["nonce"], confirmation["expires_at"]))
        else:
            payload = "\x00".join((record["id"], record["unsubscribe_nonce"]))
        return base64.urlsafe_b64encode(hmac.new(self._keys[purpose], payload.encode(), hashlib.sha256).digest()).decode().rstrip("=")

    def _url(self, record: dict, purpose: str) -> str:
        path = "/confirm" if purpose == "confirm" else "/unsubscribe"
        return self.public_base_url + path + "?" + urlencode({"id": record["id"], "token": self._token(record, purpose)})

    def request_signup(self, email: str, client_id: str = "") -> dict:
        email = validate_email(email)
        if not isinstance(client_id, str) or len(client_id) > 256 or any(ord(char) < 32 for char in client_id):
            raise SubscriptionError("Invalid client rate-limit identifier")
        self.signup_queued = False
        now = self._now()
        client_hash = hmac.new(self._keys["client-limits"], client_id.encode(), hashlib.sha256).hexdigest() if client_id else ""
        generic = {"status": "check_email", "queued": False}
        def change(registry):
            record = self._find(registry, email)
            if record and record["status"] in ("confirmed", "seeded", "suppressed"):
                return generic, False
            confirmation = record.get("confirmation") if record else None
            if confirmation:
                if confirmation["status"] in ("reserved", "uncertain"):
                    return generic, False
                if now - _timestamp(confirmation["requested_at"]) < timedelta(hours=1):
                    return generic, False
            if record is None and len(registry["records"]) >= MAX_RECORDS:
                # Expired, never-confirmed public attempts must not permanently
                # occupy all slots. Keep every legacy/tombstone record and all
                # ambiguous or in-flight SMTP reservations for reconciliation.
                for identifier, expired in list(registry["records"].items()):
                    proof = expired.get("confirmation")
                    if (expired["status"] == "pending" and not expired.get("legacy_authorized") and not expired.get("opted_out")
                            and proof and proof["status"] not in ("reserved", "uncertain")
                            and now >= _timestamp(proof["expires_at"])):
                        del registry["records"][identifier]
                if len(registry["records"]) >= MAX_RECORDS:
                    return generic, False
            limits = registry["limits"]
            if limits["date"] != now.date().isoformat():
                limits.update(date=now.date().isoformat(), count=0, hour="", clients={})
            hour = now.strftime("%Y-%m-%dT%H")
            if limits["hour"] != hour:
                limits.update(hour=hour, clients={})
            if limits["count"] >= MAX_DAILY_CONFIRMATIONS or (client_hash and limits["clients"].get(client_hash, 0) >= MAX_CLIENT_HOURLY):
                return generic, False
            if record is None:
                record = self._new_record(email, now, status="pending")
                registry["records"][record["id"]] = record
            if record["status"] == "unsubscribed":
                record["opted_out"] = True
            record["status"] = "pending"
            record["confirmed_at"] = None
            record["confirmation"] = {"nonce": secrets.token_urlsafe(18), "status": "queued",
                                      "requested_at": now.isoformat(), "expires_at": (now + CONFIRMATION_TTL).isoformat()}
            limits["count"] += 1
            if client_hash:
                limits["clients"][client_hash] = limits["clients"].get(client_hash, 0) + 1
            return {"status": "check_email", "queued": True}, True
        result = self._mutate(change)
        self.signup_queued = result["queued"]
        return result

    def confirm(self, identifier: str, token: str) -> dict:
        invalid = {"status": "invalid_or_expired"}
        if not isinstance(identifier, str) or not _ID.fullmatch(identifier) or not isinstance(token, str) or not _TOKEN.fullmatch(token):
            return invalid
        now = self._now()
        def change(registry):
            record = registry["records"].get(identifier)
            if not record or not record.get("confirmation") or record["status"] not in ("pending", "confirmed"):
                return invalid, False
            if now >= _timestamp(record["confirmation"]["expires_at"]) or not hmac.compare_digest(token, self._token(record, "confirm")):
                return invalid, False
            if record["status"] == "confirmed":
                return {"status": "confirmed"}, False
            if sum(row["status"] == "confirmed" for row in registry["records"].values()) >= MAX_CONFIRMED:
                return invalid, False
            record.update(status="confirmed", confirmed_at=now.isoformat(), opted_out=False)
            return {"status": "confirmed"}, True
        return self._mutate(change)

    def unsubscribe(self, identifier: str, token: str) -> dict:
        invalid = {"status": "invalid"}
        if not isinstance(identifier, str) or not _ID.fullmatch(identifier) or not isinstance(token, str) or not _TOKEN.fullmatch(token):
            return invalid
        def change(registry):
            record = registry["records"].get(identifier)
            if not record or not hmac.compare_digest(token, self._token(record, "unsubscribe")):
                return invalid, False
            if record["status"] in ("unsubscribed", "suppressed"):
                return {"status": "unsubscribed"}, False
            record.update(status="unsubscribed", opted_out=True, unsubscribed_at=self._now().isoformat())
            return {"status": "unsubscribed"}, True
        return self._mutate(change)

    def list_subscribers(self) -> list[dict]:
        fields = ("id", "email", "status", "created_at", "confirmed_at")
        return [{key: record.get(key) for key in fields} for record in self._load()["records"].values()]

    def admin_suppress(self, identifier: str) -> dict:
        if not isinstance(identifier, str) or not _ID.fullmatch(identifier):
            return {"status": "not_found"}
        def change(registry):
            record = registry["records"].get(identifier)
            if record is None:
                return {"status": "not_found"}, False
            if record["status"] == "suppressed":
                return {"status": "suppressed"}, False
            record.update(status="suppressed", opted_out=True, suppressed_at=self._now().isoformat())
            return {"status": "suppressed"}, True
        return self._mutate(change)

    def delivery_recipients(self, subscribers: list[str], internal: list[str]) -> list[str]:
        if not isinstance(subscribers, list) or not isinstance(internal, list) or not internal:
            raise SubscriptionError("Valid subscriber and required internal recipient lists are required")
        subscribers = list(dict.fromkeys(validate_email(value) for value in subscribers))
        internal = list(dict.fromkeys(validate_email(value) for value in internal))
        now = self._now()
        def change(registry):
            changed = False
            # Fixed internal delivery is an independent operator setting and
            # does not create public subscription/unsubscribe records.
            for email in subscribers:
                existing = self._find(registry, email)
                if existing is None:
                    if len(registry["records"]) >= MAX_RECORDS:
                        raise SubscriptionError("Subscription registry capacity reached before delivery")
                    record = self._new_record(email, now, status="seeded")
                    registry["records"][record["id"]] = record
                    changed = True
                elif not existing.get("legacy_authorized"):
                    existing["legacy_authorized"] = True
                    changed = True
            blocked = {record["email"] for record in registry["records"].values()
                       if record["status"] in ("unsubscribed", "suppressed") or record.get("opted_out")}
            confirmed = [record["email"] for record in registry["records"].values() if record["status"] == "confirmed"]
            combined = list(dict.fromkeys(internal + [email for email in subscribers + confirmed if email not in blocked]))
            if len(combined) > 100:
                raise SubscriptionError("More than 100 combined recipients requires a reviewed mailing setup")
            return combined, changed
        return self._mutate(change)

    def unsubscribe_url(self, email: str) -> str:
        email, now = validate_email(email), self._now()
        def change(registry):
            record = self._find(registry, email)
            if record:
                protect = record["status"] == "pending" and not record.get("legacy_authorized")
                if protect:
                    record["legacy_authorized"] = True
                return self._url(record, "unsubscribe"), protect
            if len(registry["records"]) >= MAX_RECORDS:
                raise SubscriptionError("Subscription registry capacity reached before delivery")
            record = self._new_record(email, now, status="seeded")
            registry["records"][record["id"]] = record
            return self._url(record, "unsubscribe"), True
        return self._mutate(change)

    def pending_confirmations(self, limit: int = 20) -> list[dict]:
        if type(limit) is not int or not 1 <= limit <= 20:
            raise SubscriptionError("Confirmation batch limit must be between 1 and 20")
        now = self._now()
        pending = [record for record in self._load()["records"].values()
                   if record["status"] == "pending" and record["confirmation"]["status"] == "queued"
                   and now < _timestamp(record["confirmation"]["expires_at"])]
        return [{"id": row["id"], "email": row["email"]} for row in sorted(pending, key=lambda row: row["created_at"])[:limit]]

    def claim_confirmation(self, identifier: str) -> dict | None:
        if not isinstance(identifier, str) or not _ID.fullmatch(identifier):
            return None
        now = self._now()
        def change(registry):
            record = registry["records"].get(identifier)
            if (not record or record["status"] != "pending" or record["confirmation"]["status"] != "queued"
                    or now >= _timestamp(record["confirmation"]["expires_at"])):
                return None, False
            reservation_id = secrets.token_urlsafe(18)
            record["confirmation"].update(status="reserved", reservation_id=reservation_id, reserved_at=now.isoformat())
            return {"id": identifier, "email": record["email"], "url": self._url(record, "confirm"), "reservation_id": reservation_id}, True
        claimed = self._mutate(change)
        if claimed is None:
            return None
        current = self._load()["records"].get(identifier)
        if (not current or current["status"] != "pending" or current["confirmation"]["status"] != "reserved"
                or current["confirmation"].get("reservation_id") != claimed["reservation_id"]):
            raise StateError("Confirmation reservation was not durably verified")
        return claimed

    def mark_confirmation(self, identifier: str, status: str, *, reservation_id: str,
                          stage: str | None = None, smtp_code: int | None = None) -> None:
        if status not in ("accepted", "rejected", "uncertain"):
            raise SubscriptionError("Invalid confirmation delivery outcome")
        def change(registry):
            record = registry["records"].get(identifier)
            confirmation = record.get("confirmation") if record else None
            if not confirmation or confirmation.get("reservation_id") != reservation_id:
                raise StateError("Confirmation reservation does not match")
            if confirmation["status"] == status:
                return None, False
            if confirmation["status"] != "reserved":
                raise StateError("Confirmation outcome cannot overwrite a terminal record")
            confirmation.update(status=status, completed_at=self._now().isoformat())
            if stage in ("validation", "connect", "auth", "sender", "recipient", "data"):
                confirmation["stage"] = stage
            if type(smtp_code) is int and 100 <= smtp_code <= 599:
                confirmation["smtp_code"] = smtp_code
            return None, True
        self._mutate(change)


def service_from_env(environment: dict | None = None) -> SubscriptionService:
    environment = dict(os.environ if environment is None else environment)
    if environment.get("GITHUB_REPOSITORY") != REPOSITORY:
        raise SubscriptionError("Subscriptions are restricted to the intended personal repository")
    base_url = validate_public_base_url(environment.get("DIGEST_PUBLIC_BASE_URL", ""))
    signing_key = environment.get("STATE_ENCRYPTION_KEY", "")
    _decode_key(signing_key)
    store = GitHubStateStore(REPOSITORY, environment.get("GITHUB_TOKEN", ""), encryption_key=signing_key)
    store.ensure_state_branch()
    return SubscriptionService(store, signing_key, base_url)
