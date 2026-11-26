"""Email OTP and opaque administrator sessions in the encrypted CAS store."""
from __future__ import annotations

import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import os
import re
import secrets

from .state_store import GitHubStateStore, StateConflict, StateError
from .subscriptions import SubscriptionError, validate_email


REPOSITORY = "Rexmiao/levyquant-digest"
POLICY_PATH = "admin-auth/policy.json"
STATE_PATH = "admin-auth/state.json"
MAX_RECORDS = 100
OTP_TTL = timedelta(minutes=10)
SESSION_TTL = timedelta(hours=1)
_ID = re.compile(r"[A-Za-z0-9_-]{24}\Z")
_CODE = re.compile(r"[0-9]{6}\Z")
_SESSION = re.compile(r"lq_session_[A-Za-z0-9_-]{43}\Z")
_HASH = re.compile(r"[a-f0-9]{64}\Z")
_OUTCOMES = {"accepted", "rejected", "uncertain"}
_STAGES = {"connect", "connection", "auth", "authentication", "sender", "recipient", "data", "delivery", "prepare", "unknown",
           "validation", "greeting", "mail"}
_ERRORS = {"invalid_email", "invalid_policy", "policy_invalid", "state_invalid", "state_unavailable",
    "state_conflict", "state_not_acknowledged", "invalid_key", "invalid_clock", "invalid_client",
    "invalid_message", "invalid_outcome", "reservation_invalid", "invalid_environment"}


class AdminAuthError(StateError):
    def __init__(self, code="state_unavailable"):
        self.code = code if isinstance(code, str) and code in _ERRORS else "state_unavailable"
        super().__init__(self.code)


def _email(value):
    try:
        return validate_email(value)
    except (SubscriptionError, ValueError, TypeError):
        raise AdminAuthError("invalid_email") from None


def _emails(values):
    if not isinstance(values, list) or len(values) > 5:
        raise AdminAuthError("invalid_policy")
    return sorted({_email(value) for value in values})


def _stamp(value):
    try:
        if not isinstance(value, str) or not value.endswith(("Z", "+00:00")):
            raise ValueError
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if moment.tzinfo is None or moment.utcoffset() != timedelta(0):
            raise ValueError
        return moment
    except (ValueError, TypeError, OverflowError):
        raise AdminAuthError("state_invalid") from None


def _key(value):
    try:
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}=?", value):
            raise ValueError
        raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        if len(raw) != 32 or base64.urlsafe_b64encode(raw).decode().rstrip("=") != value.rstrip("="):
            raise ValueError
        return raw
    except (ValueError, TypeError):
        raise AdminAuthError("invalid_key") from None


class AdminAuthService:
    def __init__(self, store, signing_key: str, now=None):
        self.store = store
        root = hmac.new(b"LevyQuant administrator key extract v1", _key(signing_key), hashlib.sha256).digest()
        self._keys = {purpose: hmac.new(root, ("levyquant/admin/" + purpose + "/v1\x01").encode(), hashlib.sha256).digest()
                      for purpose in ("session", "otp", "email-rate", "client-rate")}
        self._clock = now if callable(now) else (lambda: now) if now is not None else (lambda: datetime.now(timezone.utc))

    def _now(self):
        moment = self._clock()
        if not isinstance(moment, datetime) or moment.tzinfo is None or moment.utcoffset() is None:
            raise AdminAuthError("invalid_clock")
        return moment.astimezone(timezone.utc)

    def _digest(self, purpose, value):
        return hmac.new(self._keys[purpose], value.encode("utf-8"), hashlib.sha256).hexdigest()

    def _load(self, path):
        try:
            return deepcopy(self.store.load(path))
        except Exception:
            raise AdminAuthError("state_unavailable") from None

    def _policy(self):
        value = self._load(POLICY_PATH)
        if value is None:
            return {"schema_version": 1, "emails": [], "revision": 0, "updated_at": None}
        try:
            if (not isinstance(value, dict) or set(value) != {"schema_version", "emails", "revision", "updated_at"}
                    or type(value["schema_version"]) is not int or value["schema_version"] != 1
                    or type(value["revision"]) is not int or value["revision"] < 1
                    or _emails(value["emails"]) != value["emails"]):
                raise ValueError
            _stamp(value["updated_at"])
        except (ValueError, TypeError, KeyError, AdminAuthError):
            raise AdminAuthError("policy_invalid") from None
        return value

    def _state(self):
        value = self._load(STATE_PATH)
        if value is None:
            return {"schema_version": 1, "challenges": [], "sessions": [], "requests": []}
        try:
            if (not isinstance(value, dict) or set(value) != {"schema_version", "challenges", "sessions", "requests"}
                    or type(value["schema_version"]) is not int or value["schema_version"] != 1
                    or any(not isinstance(value[key], list) for key in ("challenges", "sessions", "requests"))
                    or sum(len(value[key]) for key in ("challenges", "sessions", "requests")) > MAX_RECORDS):
                raise ValueError
            ids, digests = set(), set()
            for row in value["challenges"]:
                if (not isinstance(row, dict) or set(row) != {"id", "email", "policy_revision", "code", "created_at", "expires_at", "attempts", "status", "client_key", "message"}
                        or not isinstance(row["id"], str) or not _ID.fullmatch(row["id"]) or row["id"] in ids
                        or _email(row["email"]) != row["email"] or type(row["policy_revision"]) is not int or row["policy_revision"] < 1
                        or not isinstance(row["client_key"], str) or not _HASH.fullmatch(row["client_key"])
                        or type(row["attempts"]) is not int or not 0 <= row["attempts"] <= 5
                        or row["status"] not in {"pending", "used", "locked"}
                        or not isinstance(row["code"], str)
                        or (row["status"] == "pending" and (not _CODE.fullmatch(row["code"]) or row["attempts"] >= 5))
                        or (row["status"] != "pending" and row["code"] != "")
                        or (row["status"] == "locked" and row["attempts"] != 5)
                        or _stamp(row["expires_at"]) - _stamp(row["created_at"]) != OTP_TTL):
                    raise ValueError
                ids.add(row["id"])
                message = row["message"]
                if (not isinstance(message, dict) or set(message) != {"status", "reservation_id", "reserved_at", "stage", "smtp_code"}
                        or message["status"] not in {"queued", "reserved", *_OUTCOMES}
                        or message["stage"] is not None and message["stage"] not in _STAGES
                        or message["smtp_code"] is not None and (type(message["smtp_code"]) is not int or not 100 <= message["smtp_code"] <= 599)):
                    raise ValueError
                if message["status"] == "queued":
                    if any(message[key] is not None for key in ("reservation_id", "reserved_at", "stage", "smtp_code")):
                        raise ValueError
                elif (not isinstance(message["reservation_id"], str) or not _ID.fullmatch(message["reservation_id"])
                      or not _stamp(row["created_at"]) <= _stamp(message["reserved_at"]) < _stamp(row["expires_at"])):
                    raise ValueError
            for row in value["sessions"]:
                if (not isinstance(row, dict) or set(row) != {"digest", "email", "policy_revision", "created_at", "expires_at"}
                        or not isinstance(row["digest"], str) or not _HASH.fullmatch(row["digest"]) or row["digest"] in digests
                        or _email(row["email"]) != row["email"] or type(row["policy_revision"]) is not int or row["policy_revision"] < 1
                        or _stamp(row["expires_at"]) - _stamp(row["created_at"]) != SESSION_TTL):
                    raise ValueError
                digests.add(row["digest"])
            for row in value["requests"]:
                if (not isinstance(row, dict) or set(row) != {"email_key", "client_key", "created_at"}
                        or any(not isinstance(row[key], str) or not _HASH.fullmatch(row[key]) for key in ("email_key", "client_key"))):
                    raise ValueError
                _stamp(row["created_at"])
        except (ValueError, TypeError, KeyError, AdminAuthError):
            raise AdminAuthError("state_invalid") from None
        return value

    def _allowed(self, row, policy, now):
        return (policy["revision"] > 0 and row["email"] in policy["emails"]
                and row["policy_revision"] == policy["revision"] and _stamp(policy["updated_at"]) <= now)

    def _active(self, row, policy, now):
        return (self._allowed(row, policy, now) and row["status"] == "pending"
                and _stamp(row["created_at"]) <= now < _stamp(row["expires_at"]) and row["attempts"] < 5)

    def _mutate(self, operation):
        for attempt in range(3):
            policy, state, now = self._policy(), self._state(), self._now()
            before = deepcopy(state)
            state["challenges"] = [row for row in state["challenges"] if _stamp(row["expires_at"]) > now]
            state["sessions"] = [row for row in state["sessions"] if _stamp(row["expires_at"]) > now]
            state["requests"] = [row for row in state["requests"] if _stamp(row["created_at"]) > now - timedelta(days=1)]
            result = operation(state, policy, now)
            if state == before:
                return result
            try:
                self.store.save(STATE_PATH, state)
            except StateConflict:
                if attempt < 2:
                    continue
                raise AdminAuthError("state_conflict") from None
            except Exception:
                raise AdminAuthError("state_unavailable") from None
            return result
        raise AdminAuthError("state_conflict")

    def configure_emails(self, emails):
        desired = _emails(emails)
        for attempt in range(3):
            current = self._policy()
            if current["revision"] and current["emails"] == desired:
                return {"emails": list(desired)}
            value = {"schema_version": 1, "emails": desired, "revision": current["revision"] + 1,
                     "updated_at": self._now().isoformat()}
            try:
                self.store.save(POLICY_PATH, value)
            except StateConflict:
                if attempt < 2:
                    continue
                raise AdminAuthError("state_conflict") from None
            except Exception:
                raise AdminAuthError("state_unavailable") from None
            if self._policy() != value:
                raise AdminAuthError("state_not_acknowledged")
            return {"emails": list(desired)}
        raise AdminAuthError("state_conflict")

    def configured_emails(self):
        policy = self._policy()
        self._state()
        return {"emails": list(policy["emails"])}

    def request_login(self, email, client_id=""):
        email = _email(email)
        if not isinstance(client_id, str) or len(client_id) > 256 or any(ord(char) < 32 or ord(char) == 127 for char in client_id):
            raise AdminAuthError("invalid_client")
        identifier = secrets.token_urlsafe(18)
        email_key, client_key = self._digest("email-rate", email), self._digest("client-rate", client_id)
        def request(state, policy, now):
            denied = {"challenge_id": identifier, "queued": False}
            if not policy["revision"] or email not in policy["emails"] or _stamp(policy["updated_at"]) > now:
                return denied
            recent = [row for row in state["requests"] if row["email_key"] == email_key]
            clients = [row for row in state["requests"] if row["client_key"] == client_key]
            if (any(_stamp(row["created_at"]) > now - timedelta(minutes=1) for row in recent)
                    or sum(_stamp(row["created_at"]) > now - timedelta(hours=1) for row in recent) >= 5
                    or len(recent) >= 10
                    or sum(_stamp(row["created_at"]) > now - timedelta(hours=1) for row in clients) >= 10
                    or len(clients) >= 20
                    or sum(len(state[key]) for key in ("challenges", "sessions", "requests")) + 2 > MAX_RECORDS):
                return denied
            if any(row["id"] == identifier for row in state["challenges"]):
                raise AdminAuthError("state_conflict")
            state["requests"].append({"email_key": email_key, "client_key": client_key, "created_at": now.isoformat()})
            state["challenges"].append({"id": identifier, "email": email, "policy_revision": policy["revision"],
                "code": f"{secrets.randbelow(1_000_000):06d}", "created_at": now.isoformat(),
                "expires_at": (now + OTP_TTL).isoformat(), "attempts": 0, "status": "pending", "client_key": client_key,
                "message": {"status": "queued", "reservation_id": None, "reserved_at": None, "stage": None, "smtp_code": None}})
            return {"challenge_id": identifier, "queued": True}
        return self._mutate(request)

    def verify_login(self, challenge_id, code):
        invalid = {"status": "invalid_or_expired"}
        if not isinstance(challenge_id, str) or not _ID.fullmatch(challenge_id):
            return invalid
        supplied = code if isinstance(code, str) and _CODE.fullmatch(code) else ""
        def verify(state, policy, now):
            row = next((row for row in state["challenges"] if row["id"] == challenge_id), None)
            if row is None or not self._active(row, policy, now):
                return dict(invalid)
            if not supplied or not hmac.compare_digest(self._digest("otp", challenge_id + supplied), self._digest("otp", challenge_id + row["code"])):
                row["attempts"] += 1
                if row["attempts"] >= 5:
                    row.update(status="locked", code="")
                return dict(invalid)
            if sum(len(state[key]) for key in ("challenges", "sessions", "requests")) >= MAX_RECORDS:
                return dict(invalid)
            token = "lq_session_" + secrets.token_urlsafe(32)
            expiry = (now + SESSION_TTL).isoformat()
            state["sessions"].append({"digest": self._digest("session", token), "email": row["email"],
                "policy_revision": policy["revision"], "created_at": now.isoformat(), "expires_at": expiry})
            row.update(status="used", code="")
            return {"status": "authenticated", "token": token, "expires_at": expiry}
        result = self._mutate(verify)
        if result["status"] == "authenticated":
            state = self._state()
            row = next((row for row in state["challenges"] if row["id"] == challenge_id), None)
            if row is None or row["status"] != "used" or not self.authenticate_session(result["token"]):
                raise AdminAuthError("state_not_acknowledged")
        return result

    def authenticate_session(self, token):
        if not isinstance(token, str) or not _SESSION.fullmatch(token):
            return False
        policy, state, now = self._policy(), self._state(), self._now()
        digest = self._digest("session", token)
        row = next((row for row in state["sessions"] if hmac.compare_digest(row["digest"], digest)), None)
        return bool(row is not None and self._allowed(row, policy, now)
                    and _stamp(row["created_at"]) <= now < _stamp(row["expires_at"]))

    def logout_session(self, token):
        if isinstance(token, str) and _SESSION.fullmatch(token):
            digest = self._digest("session", token)
            def revoke(state, policy, now):
                state["sessions"] = [row for row in state["sessions"] if not hmac.compare_digest(row["digest"], digest)]
            self._mutate(revoke)
            if self.authenticate_session(token):
                raise AdminAuthError("state_not_acknowledged")
        return {"status": "logged_out"}

    def pending_login_messages(self, limit=10):
        if type(limit) is not int or not 1 <= limit <= 10:
            raise AdminAuthError("invalid_message")
        policy, state, now = self._policy(), self._state(), self._now()
        return [{"id": row["id"]} for row in state["challenges"]
                if self._active(row, policy, now) and row["message"]["status"] == "queued"][:limit]

    def claim_login_message(self, identifier):
        if not isinstance(identifier, str) or not _ID.fullmatch(identifier):
            return None
        reservation = secrets.token_urlsafe(18)
        def claim(state, policy, now):
            row = next((row for row in state["challenges"] if row["id"] == identifier), None)
            if row is None or not self._active(row, policy, now) or row["message"]["status"] != "queued":
                return None
            row["message"].update(status="reserved", reservation_id=reservation, reserved_at=now.isoformat())
            return {"id": identifier, "email": row["email"], "code": row["code"],
                    "expires_at": row["expires_at"], "reservation_id": reservation}
        result = self._mutate(claim)
        if result is not None:
            policy, state, now = self._policy(), self._state(), self._now()
            row = next((row for row in state["challenges"] if row["id"] == identifier), None)
            if (row is None or row["message"]["status"] != "reserved"
                    or row["message"]["reservation_id"] != reservation):
                raise AdminAuthError("state_not_acknowledged")
            if not self._active(row, policy, now):
                return None
        return result

    def mark_login_message(self, identifier, status, *, reservation_id, stage=None, smtp_code=None):
        if (not isinstance(identifier, str) or not _ID.fullmatch(identifier)
                or not isinstance(reservation_id, str) or not _ID.fullmatch(reservation_id)
                or not isinstance(status, str) or status not in _OUTCOMES
                or stage is not None and (not isinstance(stage, str) or stage not in _STAGES)
                or smtp_code is not None and (type(smtp_code) is not int or not 100 <= smtp_code <= 599)):
            raise AdminAuthError("invalid_outcome")
        def mark(state, policy, now):
            row = next((row for row in state["challenges"] if row["id"] == identifier), None)
            if row is None or row["message"]["reservation_id"] != reservation_id:
                raise AdminAuthError("reservation_invalid")
            if row["message"]["status"] != "reserved":
                if row["message"]["status"] == status:
                    return {"status": status}
                raise AdminAuthError("reservation_invalid")
            row["message"].update(status=status, stage=stage, smtp_code=smtp_code)
            return {"status": status}
        return self._mutate(mark)


def service_from_env(environment=None):
    environment = dict(os.environ if environment is None else environment)
    token = environment.get("GITHUB_TOKEN")
    if (environment.get("GITHUB_REPOSITORY") != REPOSITORY or not isinstance(token, str) or not token.strip()
            or any(ord(char) < 32 for char in token)):
        raise AdminAuthError("invalid_environment")
    key = environment.get("STATE_ENCRYPTION_KEY", "")
    _key(key)
    try:
        store = GitHubStateStore(REPOSITORY, token, encryption_key=key)
        service = AdminAuthService(store, key)
        store.ensure_state_branch()
    except AdminAuthError:
        raise
    except Exception:
        raise AdminAuthError("state_unavailable") from None
    return service
