"""Hugging Face web entry point. This process never transports email."""
from __future__ import annotations

from collections import OrderedDict, deque
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from email import policy as email_policy
from email.utils import format_datetime
from email.parser import BytesParser
import base64
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import unicodedata
import tempfile
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zoneinfo import ZoneInfo

from . import daily
from . import archive
from .admin_auth import AdminAuthService
from .delivery_reports import read_run_reports, summarize_edition
from .editor import EDITOR_ERROR_CODES, EditorError, EditorValidationError
from .source_settings import (SourceSettingsError, default_moomoo_queries,
                              read_moomoo_settings, validate_moomoo_snapshot,
                              write_moomoo_settings)
from .state_store import GitHubStateStore, LocalStateStore, StateConflict, StateError
from .subscriptions import SubscriptionError, validate_email, validate_public_base_url

ROOT = Path(__file__).resolve().parent.parent
REPOSITORY = "Rexmiao/levyquant-digest"
MAX_BODY_BYTES = 4096
MAX_GITHUB_BYTES = 256 * 1024
PUBLIC_PATH = "public/latest.json"
_WORKFLOWS = frozenset(("daily-digest.yml", "subscription-mail.yml"))
_FIELDS = ("date", "subject", "html", "text")
_ADMIN_COOKIE = "__Host-lq_admin"
_SESSION_TOKEN = re.compile(r"lq_session_[A-Za-z0-9_-]{43}\Z")
# The only inline script allowed on public pages: it applies a remembered
# Day/Night choice before first paint. index.html and archive.html must contain
# exactly this text inside <script>...</script>; the CSP allows it by hash.
THEME_BOOTSTRAP = ("try{var t=localStorage.getItem('levyquant.theme');"
                   "if(t==='light'||t==='dark')document.documentElement.setAttribute('data-theme',t)}catch(e){}")
THEME_BOOTSTRAP_CSP = "'sha256-" + base64.b64encode(hashlib.sha256(THEME_BOOTSTRAP.encode("utf-8")).digest()).decode("ascii") + "'"
_ORIGIN_HOST = re.compile(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}\Z")
MAX_ADMIN_ORIGINS = 5


def _search_index(value: str) -> tuple[str, list[int]]:
    """Case-, accent- and space-insensitive search key with a map back to `value`.

    'LevyQuant', 'LévyQuant' and 'Lévy Quant' all fold to 'levyquant'. Each
    character is decomposed, stripped of combining marks and casefolded on its
    own, and whitespace is dropped; offsets[i] is the index in `value` of the
    character that produced key[i], so excerpts can be cut from the original
    text. CJK text is unchanged apart from removed spaces.
    """
    key, offsets = [], []
    for index, char in enumerate(value):
        if char.isspace():
            continue
        decomposed = unicodedata.normalize("NFD", char)
        folded = "".join(part for part in decomposed if not unicodedata.combining(part)).casefold()
        for part in folded:
            if not part.isspace():
                key.append(part)
                offsets.append(index)
    return "".join(key), offsets


def _search_fold(value: str) -> str:
    """The search key alone (see _search_index)."""
    return _search_index(value)[0]


def additional_admin_origins(value) -> tuple[str, ...]:
    """Parse DIGEST_ADMIN_ORIGINS: extra exact HTTPS origins (for example a custom
    domain) that may make browser admin writes besides DIGEST_PUBLIC_BASE_URL.

    Each entry must be exactly ``https://<lowercase host>`` with no port, path,
    credentials, query or fragment. Any malformed entry, or more than
    MAX_ADMIN_ORIGINS entries, makes the whole list untrusted (fail closed), so
    only the canonical public origin remains trusted.
    """
    if not isinstance(value, str) or not value.strip() or len(value) > 1024:
        return ()
    origins = []
    for item in value.split(","):
        item = item.strip()
        try:
            parsed = urlsplit(item)
            host = parsed.hostname or ""
            valid = (parsed.scheme == "https" and parsed.username is None and parsed.password is None
                     and parsed.port is None and parsed.path == "" and not parsed.query and not parsed.fragment
                     and len(host) <= 253 and _ORIGIN_HOST.fullmatch(host) is not None
                     and item == "https://" + host)
        except ValueError:
            valid = False
        if not valid:
            return ()
        origins.append(item)
    if len(origins) > MAX_ADMIN_ORIGINS:
        return ()
    return tuple(dict.fromkeys(origins))
_PUBLIC_MUTATIONS = frozenset(("/api/subscribe", "/api/confirm", "/api/unsubscribe",
                              "/api/admin-login/request", "/api/admin-login/verify"))
_EDITOR_ISSUE_CODES = frozenset((
    "schema_type", "schema_enum", "missing_field", "unexpected_field",
    "invalid_articles", "invalid_source", "duplicate_source_id", "unsafe_source_url",
    "missing_source_metadata", "duplicate_section", "invalid_item_text",
    "model_url_not_allowed", "unknown_or_missing_source", "duplicate_citation",
    "evidence_source_mismatch", "unsupported_evidence", "citation_without_evidence",
    "unsupported_numeric_claim", "financial_value_not_upstream_verified",
    "unsupported_precise_date", "invalid_event_time", "event_time_not_upstream_verified",
    "calendar_needs_confirmed_date", "watchlist_needs_time_window", "duplicate_item",
    "headline_only_expansion",
))


class AppError(RuntimeError):
    def __init__(self, status: int, code: str):
        super().__init__(code)
        self.status, self.code = status, code


def _private_error_details(error: Exception) -> dict:
    """Fixed diagnostics; never expose messages, reports or dynamic class names."""
    categories = ((EditorValidationError, "EditorValidationError"), (EditorError, "EditorError"),
                  (SubscriptionError, "SubscriptionError"), (StateConflict, "StateConflict"),
                  (StateError, "StateError"), (daily.ConfigurationError, "ConfigurationError"),
                  (AppError, "AppError"))
    error_type = next((label for category, label in categories if isinstance(error, category)),
                      "UnexpectedError")
    result = {"error_type": error_type}
    if isinstance(error, EditorValidationError):
        report = error.report
        errors = report.get("errors") if isinstance(report, dict) else None
        if isinstance(errors, list):
            result["issue_codes"] = sorted({issue["code"] for issue in errors[:1000]
                if isinstance(issue, dict) and isinstance(issue.get("code"), str)
                and issue["code"] in _EDITOR_ISSUE_CODES})
    if isinstance(error, EditorError):
        code, status = error.error_code, error.http_status
        if isinstance(code, str) and code in EDITOR_ERROR_CODES:
            result["error_code"] = code
        if type(status) is int and 100 <= status <= 599:
            result["http_status"] = status
    # Structured attributes only; never parse exception or provider text.
    return result


class _PublicRateLimiter:
    """Bound remote reads as well as queued mail; retain only hashed clients."""
    def __init__(self, *, clock=None, window=60, global_limit=20, client_limit=6, max_clients=256):
        self._clock = clock or time.monotonic
        self._window = window
        self._global_limit = global_limit
        self._client_limit = client_limit
        self._max_clients = max_clients
        self._lock = threading.Lock()
        self._global = deque()
        self._clients = {}

    def check(self, client_id: str) -> None:
        if not isinstance(client_id, str) or len(client_id) > 256:
            raise AppError(400, "invalid_request")
        key = hashlib.sha256(client_id.encode("utf-8")).hexdigest()
        with self._lock:
            moment = self._clock()
            cutoff = moment - self._window
            while self._global and self._global[0] <= cutoff:
                self._global.popleft()
            for previous in list(self._clients):
                events = self._clients[previous]
                while events and events[0] <= cutoff:
                    events.popleft()
                if not events:
                    del self._clients[previous]
            events = self._clients.get(key)
            if (len(self._global) >= self._global_limit
                    or (events is not None and len(events) >= self._client_limit)
                    or (events is None and len(self._clients) >= self._max_clients)):
                raise AppError(429, "rate_limited")
            if events is None:
                events = self._clients[key] = deque()
            events.append(moment)
            self._global.append(moment)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _preview_fields(value: dict) -> dict:
    """Do not expose subscriber, delivery, provider or raw state fields."""
    if not isinstance(value, dict):
        raise AppError(503, "preview_unavailable")
    limits = {"date": 10, "subject": 300, "html": 600000, "text": 300000}
    result = {}
    for field, limit in limits.items():
        item = value.get(field)
        if not isinstance(item, str) or not item.strip() or len(item) > limit:
            raise AppError(503, "preview_unavailable")
        result[field] = item
    try:
        if date.fromisoformat(result["date"]).isoformat() != result["date"]:
            raise ValueError
    except ValueError:
        raise AppError(503, "preview_unavailable") from None
    if any(ord(c) < 32 for c in result["subject"]):
        raise AppError(503, "preview_unavailable")
    return result


def _string(body: dict, field: str, maximum: int, *, empty: bool = False) -> str:
    value = body.get(field, "" if empty else None)
    if not isinstance(value, str) or len(value) > maximum or (not empty and not value):
        raise AppError(400, "invalid_request")
    if any(ord(c) < 32 for c in value):
        raise AppError(400, "invalid_request")
    return value


def _body_fields(body: dict, allowed: set[str]) -> None:
    if not isinstance(body, dict) or set(body) - allowed:
        raise AppError(400, "invalid_request")


class SpaceApplication:
    def __init__(self, environment=None, *, store_factory=None,
                 subscription_factory=None, github_request=None,
                 preview_runner=None, static_root=None, admin_auth_factory=None):
        self.environment = dict(os.environ if environment is None else environment)
        self.static_root = Path(static_root or ROOT / "runtime/huggingface/static")
        self._store_factory = store_factory
        self._subscription_factory = subscription_factory
        self._admin_auth_factory = admin_auth_factory
        self._github_override = github_request
        self._preview_runner = preview_runner or daily.run
        self._preview_lock = threading.Lock()
        self._preview_state = {"status": "idle"}
        self._generated_preview = None
        self._cache_lock = threading.Lock()
        self._public_cache = None
        self._public_cache_at = 0.0
        self._public_limiter = _PublicRateLimiter()
        self._one_click_limiter = _PublicRateLimiter(global_limit=120, client_limit=60)
        self._archive_limiter = _PublicRateLimiter(global_limit=30, client_limit=12)
        self._archive_lock = threading.RLock()
        self._archive_dates = None
        self._archive_dates_at = 0.0
        self._archive_bodies = OrderedDict()

    def _repository_valid(self) -> bool:
        return self.environment.get("GITHUB_REPOSITORY", REPOSITORY) == REPOSITORY

    def _remote_environment(self) -> dict:
        if not self._repository_valid() or any(not self.environment.get(name) for name in (
                "GITHUB_TOKEN", "STATE_ENCRYPTION_KEY")):
            raise AppError(503, "not_configured")
        return {**self.environment, "GITHUB_REPOSITORY": REPOSITORY}

    def _new_store(self, *, read_only=False):
        environment = self._remote_environment()
        store = self._store_factory() if self._store_factory else GitHubStateStore(
            REPOSITORY, environment["GITHUB_TOKEN"], encryption_key=environment["STATE_ENCRYPTION_KEY"])
        if read_only:
            if store.load("_state.json") != {"schema_version": 1, "encrypted_state": True}:
                raise StateError("Existing encrypted state is required")
        else:
            store.ensure_state_branch()
        return store

    def _new_subscription_service(self):
        environment = self._remote_environment()
        if self._subscription_factory:
            return self._subscription_factory()
        from .subscriptions import service_from_env
        return service_from_env(environment)

    def _moomoo_defaults(self) -> list[str]:
        config = daily.read_json(ROOT / "config/cloud.json")
        sources = daily.read_json(ROOT / config["source_manifest"])
        try:
            return default_moomoo_queries(sources.get("sources"))
        except SourceSettingsError:
            raise AppError(503, "source_settings_unavailable") from None

    def _moomoo_settings(self) -> dict:
        return read_moomoo_settings(self._new_store(), self._moomoo_defaults())

    def _new_admin_auth_service(self):
        environment = self._remote_environment()
        if self._admin_auth_factory:
            return self._admin_auth_factory()
        return AdminAuthService(self._new_store(), environment["STATE_ENCRYPTION_KEY"])

    def signup_enabled(self) -> bool:
        try:
            validate_public_base_url(self.environment.get("DIGEST_PUBLIC_BASE_URL", ""))
        except SubscriptionError:
            return False
        return (self.environment.get("SUBSCRIPTIONS_ENABLED", "").lower() == "true"
                and self._repository_valid()
                and all(self.environment.get(key) for key in ("GITHUB_TOKEN", "STATE_ENCRYPTION_KEY")))

    def _authorize_recovery(self, header: str | None) -> None:
        expected = self.environment.get("SPACE_ADMIN_TOKEN", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", expected):
            raise AppError(503, "admin_not_configured")
        supplied = header[7:] if isinstance(header, str) and header.startswith("Bearer ") else ""
        if len(supplied) > 256 or not hmac.compare_digest(supplied.encode("utf-8"), expected.encode("ascii")):
            raise AppError(401, "unauthorized")

    def authorize(self, header: str | None) -> None:
        supplied = header[7:] if isinstance(header, str) and header.startswith("Bearer ") else ""
        if re.fullmatch(r"lq_session_[A-Za-z0-9_-]{43}", supplied):
            if self._new_admin_auth_service().authenticate_session(supplied,
                    recovery_credential=self.environment.get("SPACE_ADMIN_TOKEN", "")):
                return
            raise AppError(401, "unauthorized")
        self._authorize_recovery(header)

    def public_preview(self) -> dict:
        with self._cache_lock:
            cached = self._public_cache
            if cached is not None and time.monotonic() - self._public_cache_at < 60:
                return {**deepcopy(cached), "signup_enabled": self.signup_enabled()}
        result = {"available": False, "date": None, "subject": None, "html": None, "text": None}
        try:
            value = self._new_store().load(PUBLIC_PATH)
            if value is not None:
                result = {"available": True, **_preview_fields(value)}
        except Exception:
            # A missing configuration or unreadable encrypted state must not
            # prevent the public landing page from starting, or reveal errors.
            pass
        with self._cache_lock:
            self._public_cache, self._public_cache_at = result, time.monotonic()
        return {**deepcopy(result), "signup_enabled": self.signup_enabled()}

    def _github(self, method: str, path: str, payload=None):
        self._remote_environment()
        allowed_get = f"/repos/{REPOSITORY}/actions/workflows/daily-digest.yml/runs?per_page=5"
        allowed_posts = {f"/repos/{REPOSITORY}/actions/workflows/{name}/dispatches" for name in _WORKFLOWS}
        if not ((method == "GET" and path == allowed_get and payload is None)
                or (method == "POST" and path in allowed_posts)):
            raise AppError(400, "invalid_request")
        if self._github_override:
            return self._github_override(method, path, payload)
        request = Request("https://api.github.com" + path, method=method,
            data=None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={"Authorization": "Bearer " + self.environment["GITHUB_TOKEN"],
                     "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
                     "Content-Type": "application/json", "User-Agent": "LevyQuant-Space"})
        try:
            with build_opener(_NoRedirect()).open(request, timeout=20) as response:
                status = response.status
                content = response.read(MAX_GITHUB_BYTES + 1)
            if len(content) > MAX_GITHUB_BYTES or status not in (200, 204):
                raise AppError(503, "github_unavailable")
            return {} if status == 204 else json.loads(content)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError):
            raise AppError(503, "github_unavailable") from None

    def _dispatch(self, workflow: str) -> None:
        if workflow not in _WORKFLOWS:
            raise AppError(400, "invalid_request")
        payload = {"ref": "main"}
        if workflow == "daily-digest.yml":
            payload["inputs"] = {"run_mode": "send"}
        self._github("POST", f"/repos/{REPOSITORY}/actions/workflows/{workflow}/dispatches", payload)

    def _admin_status(self) -> dict:
        required = ("GITHUB_TOKEN", "STATE_ENCRYPTION_KEY", "SPACE_ADMIN_TOKEN", "GEMINI_API_KEY")
        missing = [key for key in required if not self.environment.get(key)]
        if self.environment.get("GEMINI_FREE_TIER_CONFIRMED", "").lower() != "true":
            missing.append("GEMINI_FREE_TIER_CONFIRMED")
        if not self._repository_valid():
            missing.append("GITHUB_REPOSITORY")
        try:
            validate_public_base_url(self.environment.get("DIGEST_PUBLIC_BASE_URL", ""))
        except SubscriptionError:
            missing.append("DIGEST_PUBLIC_BASE_URL")
        raw_origins = self.environment.get("DIGEST_ADMIN_ORIGINS", "")
        extra_origins = additional_admin_origins(raw_origins)
        result = {"configured": not missing, "missing": missing, "runs": [],
                  # Counts and a flag only: never echo the configured origins.
                  "admin_origins": {"extra_trusted": len(extra_origins),
                                    "invalid": bool(isinstance(raw_origins, str) and raw_origins.strip()) and not extra_origins}}
        if "GITHUB_TOKEN" in missing or "GITHUB_REPOSITORY" in missing or "STATE_ENCRYPTION_KEY" in missing:
            return result
        try:
            response = self._github("GET", f"/repos/{REPOSITORY}/actions/workflows/daily-digest.yml/runs?per_page=5")
            for run in response.get("workflow_runs", [])[:5]:
                if not isinstance(run, dict) or not isinstance(run.get("id"), int):
                    continue
                link = run.get("html_url")
                expected = f"https://github.com/{REPOSITORY}/actions/runs/{run['id']}"
                if link != expected:
                    continue
                result["runs"].append({"id": run["id"], "status": run.get("status"),
                    "conclusion": run.get("conclusion"), "html_url": link})
        except Exception:
            result["runs_error"] = "unavailable"
        return result

    def _delivery_report(self) -> dict:
        store = self._new_store()
        today = datetime.now(timezone.utc).astimezone(ZoneInfo("America/New_York")).date()
        editions = []
        for offset in range(7):
            day = (today - timedelta(days=offset)).isoformat()
            edition = store.load("editions/" + day + ".json")
            if edition is None:
                continue
            daily.validate_frozen_edition(edition, day)
            if edition.get("mode") == "live":
                if edition.get("validated") is not True:
                    raise StateError("Delivery edition is not validated")
                editions.append(summarize_edition(edition))
        records = read_run_reports(store)
        counts = ("recipient_count", "accepted", "rejected", "uncertain", "reserved", "pending",
                  "skipped_unsubscribed", "internal_count", "already_accepted")
        runs = {}
        for record in records:
            identifier = int(record["run_id"])
            runs[identifier] = {"id": identifier, "mode": record["mode"], "status": "unknown", "conclusion": None,
                "html_url": f"https://github.com/{REPOSITORY}/actions/runs/{identifier}",
                "date": record["date"], "result_status": record["status"],
                "counts": {key: record.get(key) for key in counts} if record["mode"] == "send" else None,
                "error_type": record.get("error_type"), "error_code": record.get("error_code")}
        runs_unavailable = False
        try:
            response = self._github("GET", f"/repos/{REPOSITORY}/actions/workflows/daily-digest.yml/runs?per_page=5")
            for run in response.get("workflow_runs", [])[:5]:
                if (not isinstance(run, dict) or type(run.get("id")) is not int or run["id"] <= 0
                        or run.get("html_url") != f"https://github.com/{REPOSITORY}/actions/runs/{run['id']}"):
                    continue
                identifier = run["id"]
                row = runs.setdefault(identifier, {"id": identifier, "mode": None, "date": None,
                    "html_url": run["html_url"], "result_status": None, "counts": None,
                    "error_type": None, "error_code": None})
                row["status"] = run.get("status") if run.get("status") in ("queued", "in_progress", "completed", "waiting", "pending", "requested") else "unknown"
                row["conclusion"] = run.get("conclusion") if run.get("conclusion") in ("success", "failure", "cancelled", "timed_out", "skipped", "action_required", "neutral", "stale", "startup_failure") else None
                if row["mode"] is None:
                    title = run.get("display_title")
                    mode = re.fullmatch(r"LevyQuant Daily Digest \[(send|preview|preview-email|smtp-test)\]", title) if isinstance(title, str) else None
                    if mode:
                        row["mode"] = mode.group(1)
                if row["mode"] is None or row["date"] is None:
                    # Older live runs saved a date claim before generation.
                    # That proves the run mode, never SMTP success or counts.
                    claim = store.load("runs/" + str(identifier) + ".json")
                    if isinstance(claim, dict) and set(claim) == {"date", "created_at"}:
                        try:
                            claimed_day = date.fromisoformat(claim["date"])
                            claimed_at = datetime.fromisoformat(claim["created_at"])
                            if (claimed_day.isoformat() != claim["date"] or claimed_at.utcoffset() is None
                                    or row["mode"] not in (None, "send")):
                                raise ValueError
                        except (ValueError, TypeError, OverflowError):
                            continue
                        row["mode"] = "send"
                        row["date"] = claimed_day.isoformat()
        except Exception:
            runs_unavailable = True
        return {"editions": editions, "runs": [runs[key] for key in sorted(runs, reverse=True)[:50]],
                "window_days": 7, "runs_unavailable": runs_unavailable}

    def _run_preview(self) -> None:
        stage = "preview_setup"
        try:
            environment = {key: self.environment[key] for key in ("GEMINI_API_KEY", "GEMINI_FREE_TIER_CONFIRMED")
                           if key in self.environment}
            config = daily.read_json(ROOT / "config/cloud.json")
            stage = "source_settings_read"
            settings = self._moomoo_settings()
            with tempfile.TemporaryDirectory(prefix="levyquant-preview-") as directory:
                output = Path(directory)
                stage = "preview_pipeline"
                result = self._preview_runner(config, "preview", environment, output, moomoo_settings=settings)
                stage = "edition_validation"
                if (not isinstance(result, dict) or result.get("mode") != "preview"
                        or result.get("status") != "preview_ready_no_mail_sent"
                        or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", str(result.get("date", "")))):
                    raise AppError(503, "preview_failed")
                edition = LocalStateStore(output / "preview-state").load("editions/" + result["date"] + ".json")
                if not isinstance(edition, dict) or edition.get("validated") is not True or edition.get("mode") != "preview":
                    raise AppError(503, "preview_failed")
                daily.validate_frozen_edition(edition, result["date"])
                preview = _preview_fields(edition)
            with self._preview_lock:
                self._generated_preview = deepcopy(preview)
                self._preview_state = {"status": "ready", "preview": preview,
                                       "moomoo_settings_revision": settings["revision"]}
        except Exception as error:
            with self._preview_lock:
                self._generated_preview = None
                self._preview_state = {"status": "failed", "error": "preview_failed",
                                       "error_stage": stage, **_private_error_details(error)}

    def _start_preview(self) -> tuple[int, dict]:
        if (not self.environment.get("GEMINI_API_KEY")
                or self.environment.get("GEMINI_FREE_TIER_CONFIRMED", "").lower() != "true"):
            raise AppError(503, "model_not_configured")
        with self._preview_lock:
            if self._preview_state["status"] == "running":
                raise AppError(409, "preview_already_running")
            self._generated_preview = None
            self._preview_state = {"status": "running"}
            worker = threading.Thread(target=self._run_preview, daemon=True, name="levyquant-preview")
            worker.start()
        return 202, {"status": "running"}

    def _publish(self) -> dict:
        with self._preview_lock:
            if self._preview_state["status"] != "ready" or self._generated_preview is None:
                raise AppError(409, "validated_preview_required")
            preview = _preview_fields(deepcopy(self._generated_preview))
        archive.publish_edition(self._new_store(), preview)
        for attempt in range(3):
            store = self._new_store()
            store.load(PUBLIC_PATH)
            try:
                store.save(PUBLIC_PATH, preview)
                break
            except StateConflict:
                if attempt == 2:
                    raise AppError(409, "state_conflict") from None
        with self._cache_lock:
            self._public_cache = None
        with self._archive_lock:
            self._archive_dates = None
        return {"status": "published", "date": preview["date"]}

    def _archive_directory_context(self):
        """Return a reader only when this request just verified the marker."""
        with self._archive_lock:
            store = None
            if self._archive_dates is None or time.monotonic() - self._archive_dates_at >= 60:
                store = self._new_store(read_only=True)
                self._archive_dates = archive.read_index(store)
                self._archive_dates_at = time.monotonic()
            return list(self._archive_dates), store

    def _archive_directory(self) -> list[str]:
        return self._archive_directory_context()[0]

    def _archive_edition(self, day: str, *, store=None) -> dict:
        with self._archive_lock:
            if day in self._archive_bodies:
                self._archive_bodies.move_to_end(day)
                return deepcopy(self._archive_bodies[day])
            value = archive.read_edition(store if store is not None else self._new_store(read_only=True), day)
            if value is None:
                raise archive.ArchiveError("Indexed archive snapshot is missing")
            self._archive_bodies[day] = value
            while len(self._archive_bodies) > 128:
                self._archive_bodies.popitem(last=False)
            return deepcopy(value)

    def _archive_catalog(self) -> dict:
        dates = self._archive_directory()
        return {"months": sorted({day[:7] for day in dates}, reverse=True),
                "latest_date": dates[0] if dates else None}

    def _archive_search(self, body: dict) -> dict:
        _body_fields(body, {"month", "query", "page"})
        month = _string(body, "month", 7, empty=True)
        query = _string(body, "query", 100, empty=True).strip()
        page = body.get("page", 1)
        if type(page) is not int or not 1 <= page <= 9007199254740991:
            raise AppError(400, "invalid_request")
        if month:
            try:
                archive.validate_date(month + "-01")
            except archive.ArchiveError:
                raise AppError(400, "invalid_request") from None
        dates, store = self._archive_directory_context()
        months = sorted({day[:7] for day in dates}, reverse=True)
        selected_month = month or (months[0] if months else "")
        selected = [day for day in dates if day.startswith(selected_month + "-")] if selected_month else []
        if len(selected) > 31:
            raise archive.ArchiveError("Archive month exceeds the supported date count")
        offset = (page - 1) * 10
        # Browsing needs only this page. A keyword search still checks every
        # date in the month so totals and matches cannot omit later pages.
        scan_dates = selected if query else selected[offset:offset + 10]
        needle = _search_fold(query)
        matched = []
        for day in scan_dates:
            with self._archive_lock:
                if store is None and day not in self._archive_bodies:
                    store = self._new_store(read_only=True)
                edition = self._archive_edition(day, store=store)
            if needle and needle not in _search_fold(edition["subject"] + "\n" + edition["text"]):
                continue
            plain = " ".join(edition["text"].split())
            position = 0
            if needle:
                key, offsets = _search_index(plain)
                found = key.find(needle)
                position = offsets[found] if found >= 0 else -1
            start = max(0, position - 70) if position >= 0 else 0
            excerpt = ("…" if start else "") + plain[start:start + 240]
            if start + 240 < len(plain):
                excerpt += "…"
            matched.append({"date": day, "subject": edition["subject"], "excerpt": excerpt})
        total = len(matched) if query else len(selected)
        return {"month": selected_month, "query": query, "page": page, "page_size": 10,
                "total": total, "months": months,
                "items": matched[offset:offset + 10] if query else matched,
                "has_more": offset + 10 < total}

    def _archive_backfill(self, body: dict) -> dict:
        _body_fields(body, {"cursor"})
        cursor = _string(body, "cursor", 10, empty=True)
        if cursor:
            try:
                archive.validate_date(cursor)
            except archive.ArchiveError:
                raise AppError(400, "invalid_request") from None
        store = self._new_store()
        days = store.list_edition_dates()
        if not isinstance(days, list) or len(days) > archive.MAX_DATES:
            raise archive.ArchiveError("Edition directory is invalid")
        days = [archive.validate_date(day) for day in days]
        if days != sorted(set(days)):
            raise archive.ArchiveError("Edition directory is invalid")
        latest = store.load(PUBLIC_PATH)
        if latest is not None:
            latest = archive.public_fields(latest)
            days = sorted(set(days) | {latest["date"]})
        remaining = [day for day in days if day > cursor]
        batch = remaining[:31]
        archived = 0
        for day in batch:
            frozen = store.load("editions/" + day + ".json")
            snapshot = None
            if isinstance(frozen, dict) and frozen.get("mode") == "live" and frozen.get("validated") is True:
                daily.validate_frozen_edition(frozen, day)
                if any(isinstance(record, dict) and record.get("status") == "accepted"
                       for record in frozen["deliveries"].values()):
                    snapshot = frozen
            if snapshot is None and latest is not None and latest["date"] == day:
                snapshot = latest
            if snapshot is not None and archive.publish_edition(store, snapshot):
                archived += 1
        with self._archive_lock:
            self._archive_dates = None
        complete = len(remaining) <= 31
        return {"processed": len(batch), "archived": archived, "skipped": len(batch) - archived,
                "next_cursor": None if complete else batch[-1], "complete": complete}

    def handle_api(self, method: str, path: str, body: dict | None = None, *, authorization=None, client_id=""):
        """All exceptions crossing the HTTP boundary are replaced with codes."""
        body = {} if body is None else body
        if path.startswith("/api/admin/"):
            self.authorize(authorization)
        if method == "POST" and path in _PUBLIC_MUTATIONS:
            # This precedes validation, store construction and marker/registry
            # reads, including requests which do not enqueue a new message.
            self._public_limiter.check(client_id)
        if method == "GET" and path == "/api/public/preview":
            return 200, self.public_preview()
        if ((method == "GET" and path == "/api/archive")
                or (method == "POST" and path in ("/api/archive/search", "/api/archive/edition"))):
            self._archive_limiter.check(client_id)
            try:
                if method == "GET":
                    return 200, self._archive_catalog()
                if path == "/api/archive/search":
                    return 200, self._archive_search(body)
                _body_fields(body, {"date"})
                day = _string(body, "date", 10)
                try:
                    archive.validate_date(day)
                except archive.ArchiveError:
                    raise AppError(400, "invalid_request") from None
                dates, store = self._archive_directory_context()
                if day not in dates:
                    raise AppError(404, "archive_not_found")
                return 200, {"edition": self._archive_edition(day, store=store)}
            except StateError:
                raise AppError(503, "archive_unavailable") from None
        if method == "POST" and path == "/api/one-click-unsubscribe":
            self._one_click_limiter.check(client_id)
            _body_fields(body, {"id", "token", "List-Unsubscribe"})
            identifier, token = _string(body, "id", 24), _string(body, "token", 43)
            if (body.get("List-Unsubscribe") != "One-Click"
                    or not re.fullmatch(r"[A-Za-z0-9_-]{24}", identifier)
                    or not re.fullmatch(r"[A-Za-z0-9_-]{43}", token)):
                raise AppError(400, "invalid_request")
            result = self._new_subscription_service().one_click_unsubscribe(identifier, token)
            if not isinstance(result, dict) or result.get("status") != "unsubscribed":
                raise AppError(400, "invalid_unsubscribe_link")
            return 200, {"status": "unsubscribed"}
        if method == "POST" and path == "/api/admin-login/request":
            _body_fields(body, {"email"})
            try:
                email = validate_email(_string(body, "email", 254))
            except SubscriptionError:
                raise AppError(400, "invalid_request") from None
            result = self._new_admin_auth_service().request_login(email, client_id=client_id)
            identifier = result.get("challenge_id") if isinstance(result, dict) else None
            if not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9_-]{24}", identifier):
                raise AppError(503, "temporarily_unavailable")
            if result.get("queued") is True:
                self._dispatch("subscription-mail.yml")
            return 200, {"status": "check_email", "challenge_id": identifier}
        if method == "POST" and path == "/api/admin-login/verify":
            _body_fields(body, {"challenge_id", "code"})
            identifier, code = _string(body, "challenge_id", 24), _string(body, "code", 6)
            if not re.fullmatch(r"[A-Za-z0-9_-]{24}", identifier) or not re.fullmatch(r"[0-9]{6}", code):
                raise AppError(400, "invalid_request")
            result = self._new_admin_auth_service().verify_login(identifier, code)
            if not isinstance(result, dict) or result.get("status") != "authenticated":
                raise AppError(401, "invalid_or_expired")
            token, expires = result.get("token"), result.get("expires_at")
            if (not isinstance(token, str) or not re.fullmatch(r"lq_session_[A-Za-z0-9_-]{43}", token)
                    or not isinstance(expires, str) or len(expires) > 40):
                raise AppError(503, "temporarily_unavailable")
            return 200, {"status": "authenticated", "token": token, "expires_at": expires}
        if path == "/api/admin/session" and method in ("GET", "POST"):
            service = self._new_admin_auth_service()
            if method == "POST":
                _body_fields(body, set())
                self._authorize_recovery(authorization)
                return 200, service.create_recovery_session(authorization[7:])
            token = authorization[7:] if isinstance(authorization, str) else ""
            result = service.session_details(token,
                recovery_credential=self.environment.get("SPACE_ADMIN_TOKEN", ""))
            if result is None:
                raise AppError(401, "unauthorized")
            return 200, result
        if method == "POST" and path == "/api/subscribe":
            _body_fields(body, {"email", "website"})
            if not self.signup_enabled():
                raise AppError(503, "subscriptions_not_available")
            if _string(body, "website", 512, empty=True):
                return 200, {"status": "check_email"}
            email = _string(body, "email", 254)
            try:
                validate_email(email)
            except SubscriptionError:
                raise AppError(400, "invalid_request") from None
            service = self._new_subscription_service()
            result = service.request_signup(email, client_id=client_id)
            if result.get("queued") is True:
                self._dispatch("subscription-mail.yml")
            return 200, {"status": "check_email"}
        if method == "POST" and path in ("/api/confirm", "/api/unsubscribe"):
            _body_fields(body, {"id", "token"})
            identifier, token = _string(body, "id", 128), _string(body, "token", 256)
            if not re.fullmatch(r"[A-Za-z0-9_-]+", identifier) or not re.fullmatch(r"[A-Za-z0-9_.-]+", token):
                raise AppError(400, "invalid_request")
            service = self._new_subscription_service()
            result = getattr(service, "confirm" if path == "/api/confirm" else "unsubscribe")(identifier, token)
            allowed = {"confirmed", "invalid_or_expired"} if path == "/api/confirm" else {"unsubscribed", "invalid"}
            if not isinstance(result, dict) or result.get("status") not in allowed:
                raise AppError(503, "temporarily_unavailable")
            return 200, {"status": result["status"]}
        if method == "GET" and path == "/api/admin/subscribers":
            stage = "subscription_service_init"
            try:
                service = self._new_subscription_service()
                stage = "subscriber_registry_read"
                return 200, {"subscribers": service.list_subscribers()}
            except StateError as error:
                return 503, {"error": "state_unavailable", "error_stage": stage,
                             "state_error_type": _private_error_details(error)["error_type"]}
        if method == "POST" and path == "/api/admin/confirmation-status":
            _body_fields(body, {"email"})
            try:
                email = validate_email(_string(body, "email", 254))
            except SubscriptionError:
                raise AppError(400, "invalid_request") from None
            return 200, self._new_subscription_service().confirmation_delivery_status(email)
        if method == "POST" and path == "/api/admin/subscribers":
            _body_fields(body, {"id", "action"})
            if body.get("action") != "suppress":
                raise AppError(400, "invalid_request")
            identifier = _string(body, "id", 128)
            if not re.fullmatch(r"[A-Za-z0-9_-]+", identifier):
                raise AppError(400, "invalid_request")
            return 200, self._new_subscription_service().admin_suppress(identifier)
        if method == "GET" and path == "/api/admin/status":
            return 200, self._admin_status()
        if method == "GET" and path == "/api/admin/delivery-report":
            return 200, self._delivery_report()
        if method == "POST" and path == "/api/admin/archive/backfill":
            return 200, self._archive_backfill(body)
        if path == "/api/admin/login-emails" and method in ("GET", "POST"):
            # Changing the administrator allowlist requires the independent
            # recovery credential, even when a temporary email session is valid.
            self._authorize_recovery(authorization)
            if method == "GET":
                return 200, self._new_admin_auth_service().configured_emails()
            _body_fields(body, {"emails"})
            emails = body.get("emails")
            if not isinstance(emails, list) or not 1 <= len(emails) <= 5:
                raise AppError(400, "invalid_request")
            try:
                normalized = [validate_email(email) for email in emails]
            except SubscriptionError:
                raise AppError(400, "invalid_request") from None
            return 200, self._new_admin_auth_service().configure_emails(normalized)
        if method == "POST" and path == "/api/admin/logout":
            _body_fields(body, set())
            token = authorization[7:] if isinstance(authorization, str) else ""
            if token.startswith("lq_session_"):
                self._new_admin_auth_service().logout_session(token)
            return 200, {"status": "signed_out"}
        if method == "GET" and path == "/api/admin/moomoo-settings":
            return 200, self._moomoo_settings()
        if method == "POST" and path == "/api/admin/moomoo-settings":
            _body_fields(body, {"queries", "revision"})
            try:
                snapshot = validate_moomoo_snapshot(body)
            except SourceSettingsError:
                raise AppError(400, "invalid_moomoo_settings") from None
            try:
                saved = write_moomoo_settings(self._new_store(), snapshot["queries"],
                                               snapshot["revision"], self._moomoo_defaults())
            except StateConflict:
                raise AppError(409, "moomoo_settings_conflict") from None
            return 200, saved
        if method == "POST" and path == "/api/admin/send":
            _body_fields(body, set())
            self._new_store()  # Verify the encryption marker before dispatching.
            self._dispatch("daily-digest.yml")
            return 202, {"status": "queued"}
        if method == "GET" and path == "/api/admin/preview":
            with self._preview_lock:
                return 200, deepcopy(self._preview_state)
        if method == "POST" and path == "/api/admin/preview":
            _body_fields(body, set())
            return self._start_preview()
        if method == "POST" and path == "/api/admin/publish":
            _body_fields(body, set())
            return 200, self._publish()
        raise AppError(404, "not_found")


class SpaceHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 32

    def __init__(self, server_address, application: SpaceApplication):
        self.application = application
        self._slots = threading.BoundedSemaphore(32)
        super().__init__(server_address, SpaceRequestHandler)

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()

    def handle_error(self, request, client_address):
        # Base implementation prints request details and traceback. Never emit
        # addresses, headers, URLs, provider responses or tokens in this server.
        print("request_failed", flush=True)


class SpaceRequestHandler(BaseHTTPRequestHandler):
    server_version = "LevyQuant"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, format, *args):
        pass

    def _respond(self, status: int, payload, content_type="application/json; charset=utf-8"):
        encoded = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        cookie = getattr(self, "_response_cookie", None)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self' " + THEME_BOOTSTRAP_CSP + "; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; "
            "frame-src 'self' blob:; object-src 'none'; base-uri 'none'; form-action 'self'; "
            "frame-ancestors 'self' https://huggingface.co https://*.hf.space")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        if self.command != "HEAD":
            self.wfile.write(encoded)

    def send_error(self, code, message=None, explain=None):
        self._respond(code, {"error": "invalid_request"})

    def _body_size(self) -> int:
        if self.headers.get("Transfer-Encoding") is not None:
            raise AppError(400, "invalid_request")
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) != 1 or not re.fullmatch(r"[0-9]{1,10}", lengths[0]):
            raise AppError(400, "invalid_request")
        size = int(lengths[0])
        if size > MAX_BODY_BYTES:
            # A tiny rejected body can already be in the receive buffer.
            # Consume only this bounded case so closing the connection does
            # not reset the response while unread request bytes remain.
            if size == MAX_BODY_BYTES + 1:
                self.rfile.read(size)
            raise AppError(413, "request_too_large")
        return size

    def _body_bytes(self, size: int) -> bytes:
        raw = self.rfile.read(size)
        if len(raw) != size:
            raise AppError(400, "invalid_request")
        return raw

    def _json_body(self) -> dict:
        size = self._body_size()
        if self.headers.get_content_type() != "application/json":
            self._body_bytes(size)
            raise AppError(415, "json_required")
        try:
            raw = self._body_bytes(size)
            value = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeError):
            raise AppError(400, "invalid_request") from None
        if not isinstance(value, dict):
            raise AppError(400, "invalid_request")
        return value

    def _one_click_body(self) -> None:
        size = self._body_size()
        content_type = self.headers.get_content_type()
        if content_type not in ("application/x-www-form-urlencoded", "multipart/form-data"):
            self._body_bytes(size)
            raise AppError(415, "form_required")
        raw = self._body_bytes(size)
        try:
            if content_type == "application/x-www-form-urlencoded":
                pairs = parse_qsl(raw.decode("ascii"), keep_blank_values=True, strict_parsing=True,
                                  max_num_fields=2, encoding="utf-8", errors="strict")
                valid = pairs == [("List-Unsubscribe", "One-Click")]
            else:
                header = self.headers.get("Content-Type", "")
                boundary = self.headers.get_param("boundary")
                if (not isinstance(boundary, str) or not re.fullmatch(r"[A-Za-z0-9'()+_,./:=?-]{1,70}", boundary)
                        or len(header) > 200 or "\r" in header or "\n" in header):
                    raise ValueError
                message = BytesParser(policy=email_policy.default).parsebytes(
                    b"Content-Type: " + header.encode("ascii") + b"\r\nMIME-Version: 1.0\r\n\r\n" + raw)
                parts = list(message.iter_parts()) if message.is_multipart() else []
                valid = len(parts) == 1 and not message.defects
                if valid:
                    part = parts[0]
                    valid = (not part.defects and not part.is_multipart() and part.get_filename() is None
                             and part.get_content_disposition() == "form-data"
                             and part.get_param("name", header="content-disposition") == "List-Unsubscribe"
                             and part.get_payload(decode=True) == b"One-Click")
            if not valid:
                raise ValueError
        except (ValueError, TypeError, UnicodeError):
            raise AppError(400, "invalid_request") from None

    def _cookie_token(self):
        headers = self.headers.get_all("Cookie", [])
        if sum(len(value) for value in headers) > 8192:
            raise AppError(400, "invalid_request")
        values = [part.split("=", 1)[1].strip() for header in headers for part in header.split(";")
                  if "=" in part and part.split("=", 1)[0].strip() == _ADMIN_COOKIE]
        if len(values) > 1:
            raise AppError(401, "unauthorized")
        return values[0] if values and _SESSION_TOKEN.fullmatch(values[0]) else None

    def _require_same_origin(self):
        # Only operator-configured HTTPS origins are trusted: the canonical
        # DIGEST_PUBLIC_BASE_URL plus exact DIGEST_ADMIN_ORIGINS entries (for a
        # custom domain). Forwarded Host/Proto and the inbound Host header never
        # grant access, and a malformed extra list trusts no extra origin.
        environment = self.server.application.environment
        try:
            expected = validate_public_base_url(environment.get("DIGEST_PUBLIC_BASE_URL", ""))
        except SubscriptionError:
            raise AppError(503, "not_configured") from None
        trusted = {expected, *additional_admin_origins(environment.get("DIGEST_ADMIN_ORIGINS", ""))}
        origins = self.headers.get_all("Origin", [])
        if len(origins) != 1 or origins[0] not in trusted:
            raise AppError(403, "same_origin_required")
        fetch_site = self.headers.get("Sec-Fetch-Site")
        if fetch_site is not None and fetch_site != "same-origin":
            raise AppError(403, "same_origin_required")

    def _set_session_cookie(self, result):
        token, expiry = result.get("token"), result.get("expires_at")
        try:
            if not isinstance(token, str) or not _SESSION_TOKEN.fullmatch(token) or not isinstance(expiry, str):
                raise ValueError
            moment = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
            if moment.tzinfo is None or moment.utcoffset() != timedelta(0):
                raise ValueError
            remaining = min(3600, int((moment - datetime.now(timezone.utc)).total_seconds()))
            if remaining <= 0:
                raise ValueError
        except (ValueError, TypeError, OverflowError):
            raise AppError(503, "temporarily_unavailable") from None
        self._response_cookie = (f"{_ADMIN_COOKIE}={token}; Path=/; Secure; HttpOnly; SameSite=Strict; "
                                 f"Max-Age={remaining}; Expires={format_datetime(moment, usegmt=True)}")
        return {"status": "authenticated", "expires_at": expiry}

    def _clear_session_cookie(self):
        self._response_cookie = (f"{_ADMIN_COOKIE}=; Path=/; Secure; HttpOnly; SameSite=Strict; "
                                 "Max-Age=0; Expires=Thu, 01 Jan 1970 00:00:00 GMT")

    def _handle(self):
        try:
            parsed = urlsplit(self.path)
            path = parsed.path
            if parsed.scheme or parsed.netloc or (path.startswith("/api/") and parsed.query):
                raise AppError(400, "invalid_request")
            app = self.server.application
            if path == "/one-click-unsubscribe":
                # GET/HEAD scanners never change state. A valid signed URL plus
                # the exact receiver POST marker is the sole unsubscribe action.
                if self.command != "POST":
                    raise AppError(405, "post_required")
                if parsed.fragment:
                    raise AppError(400, "invalid_request")
                try:
                    pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True,
                                      max_num_fields=2, encoding="utf-8", errors="strict")
                    parameters = dict(pairs)
                    if len(pairs) != 2 or set(parameters) != {"id", "token"}:
                        raise ValueError
                except (ValueError, TypeError, UnicodeError):
                    raise AppError(400, "invalid_request") from None
                self._one_click_body()
                client = hashlib.sha256(self.client_address[0].encode("utf-8")).hexdigest()
                status, response = app.handle_api("POST", "/api/one-click-unsubscribe",
                    {**parameters, "List-Unsubscribe": "One-Click"}, client_id=client)
                self._respond(status, response)
                return
            if path.startswith("/api/"):
                authorization = self.headers.get("Authorization")
                cookie_token = self._cookie_token() if path.startswith("/api/admin/") else None
                using_cookie = authorization is None and cookie_token is not None
                if using_cookie:
                    authorization = "Bearer " + cookie_token
                browser_login = self.command == "POST" and path in (
                    "/api/admin/session", "/api/admin-login/verify")
                if browser_login or (using_cookie and self.command == "POST"):
                    self._require_same_origin()
                # Authenticate before reading a potentially slow admin body.
                if path.startswith("/api/admin/"):
                    app.authorize(authorization)
                body = self._json_body() if self.command == "POST" else None
                client = hashlib.sha256(self.client_address[0].encode("utf-8")).hexdigest()
                status, response = app.handle_api(self.command, path, body,
                    authorization=authorization, client_id=client)
                if browser_login and status == 200:
                    response = self._set_session_cookie(response)
                if self.command == "POST" and path == "/api/admin/logout" and status == 200:
                    self._clear_session_cookie()
                self._respond(status, response)
                return
            if self.command != "GET":
                raise AppError(405, "method_not_allowed")
            files = {"/": ("index.html", "text/html; charset=utf-8"),
                     "/confirm": ("index.html", "text/html; charset=utf-8"),
                     "/unsubscribe": ("index.html", "text/html; charset=utf-8"),
                     "/admin": ("admin.html", "text/html; charset=utf-8"),
                     "/archive": ("archive.html", "text/html; charset=utf-8"),
                     "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                     "/app.css": ("app.css", "text/css; charset=utf-8"),
                     "/static/app.js": ("app.js", "text/javascript; charset=utf-8"),
                     "/static/app.css": ("app.css", "text/css; charset=utf-8")}
            if path not in files:
                raise AppError(404, "not_found")
            name, content_type = files[path]
            try:
                content = (app.static_root / name).read_bytes()
            except OSError:
                raise AppError(503, "page_unavailable") from None
            self._respond(200, content, content_type)
        except AppError as error:
            if error.status == 401 and self.path.split("?", 1)[0].startswith("/api/admin/"):
                self._clear_session_cookie()
            self._respond(error.status, {"error": error.code})
        except SubscriptionError:
            self._respond(400, {"error": "invalid_request"})
        except StateError:
            self._respond(503, {"error": "state_unavailable"})
        except Exception:
            self._respond(503, {"error": "temporarily_unavailable"})

    do_GET = _handle
    do_POST = _handle
    do_HEAD = _handle


def main() -> None:
    server = SpaceHTTPServer(("0.0.0.0", 7860), SpaceApplication())
    print("LevyQuant web service ready", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
