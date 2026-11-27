"""Durable compare-and-swap state; reservations are saved before SMTP DATA.

The GitHub Contents API stores authenticated ciphertext on a separate state
branch, including in public repositories. The encryption key is supplied only
through an independent secret; no remote operation accepts plaintext state.
"""
from __future__ import annotations

import base64
from datetime import date
import json
import hashlib
import os
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, Request, build_opener

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:  # Local read-only previews do not need remote encryption.
    AESGCM = None


MAX_STATE_BYTES = 1024 * 1024
STATE_FORMAT = "levyquant-state-aesgcm-v1"
_INITIAL_STATE_PATH = "_state.json"


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward the repository credential to a moved repository/host.
        return None


urlopen = build_opener(_NoRedirect()).open


class StateError(RuntimeError):
    pass


class StateConflict(StateError):
    pass


def _state_path(name: str) -> str:
    if not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z0-9_-]+(?:/[a-zA-Z0-9_-]+)*\.json", name):
        raise StateError("Invalid state path")
    return name


def _state_object(raw: bytes | str) -> dict:
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError):
        raise StateError("Stored state is not valid JSON") from None
    if not isinstance(value, dict):
        raise StateError("Stored state must be a JSON object")
    return value


def _edition_day(path: str) -> str | None:
    """Only ordinary date-named frozen editions belong in a backfill scan."""
    match = re.fullmatch(r"editions/([0-9]{4}-[0-9]{2}-[0-9]{2})\.json", path)
    if match:
        try:
            day = match.group(1)
            if date.fromisoformat(day).isoformat() == day:
                return day
        except ValueError:
            pass
    return None


class LocalStateStore:
    """Single-process local preview/tests only; production uses remote CAS."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.versions: dict[str, str | None] = {}

    def _path(self, name: str) -> Path:
        return self.root / _state_path(name)

    def load(self, name: str) -> dict | None:
        path = self._path(name)
        if not path.exists():
            self.versions[name] = None
            return None
        content = path.read_text(encoding="utf-8")
        self.versions[name] = content
        return _state_object(content)

    def save(self, name: str, value: dict) -> None:
        path = self._path(name)
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if name not in self.versions:
            raise StateError("Load state before saving it")
        if current != self.versions[name]:
            raise StateConflict("State changed; another run may already own this delivery")
        content = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
        if len(content.encode("utf-8")) > MAX_STATE_BYTES:
            raise StateError("State exceeds the supported size limit")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".pending")
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, path)
        self.versions[name] = content

    def list_edition_dates(self) -> list[str]:
        directory = self.root / "editions"
        if directory.is_symlink():
            raise StateError("Edition directory is not a regular directory")
        if not directory.exists():
            return []
        if not directory.is_dir():
            raise StateError("Edition directory is not a regular directory")
        days = set()
        for path in directory.glob("*.json"):
            day = _edition_day("editions/" + path.name)
            if day and path.is_file() and not path.is_symlink():
                days.add(day)
        return sorted(days)


class GitHubStateStore:
    def __init__(self, repository: str, token: str, *, encryption_key: str | None = None,
                 branch: str = "delivery-state"):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise StateError("A valid GitHub repository is required")
        if any(part in (".", "..") for part in repository.split("/")):
            raise StateError("A valid GitHub repository is required")
        if not re.fullmatch(r"[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*", branch):
            raise StateError("Invalid delivery state branch")
        if not token:
            raise StateError("GITHUB_TOKEN is missing")
        if not isinstance(encryption_key, str) or not encryption_key:
            raise StateError("STATE_ENCRYPTION_KEY is required before remote state access")
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}=?", encryption_key):
            raise StateError("STATE_ENCRYPTION_KEY must be URL-safe Base64 for exactly 32 bytes")
        try:
            raw_key = base64.b64decode(encryption_key + "=" * (-len(encryption_key) % 4), altchars=b"-_", validate=True)
        except (ValueError, TypeError):
            raise StateError("STATE_ENCRYPTION_KEY has invalid encoding") from None
        if len(raw_key) != 32 or base64.urlsafe_b64encode(raw_key).decode().rstrip("=") != encryption_key.rstrip("="):
            raise StateError("STATE_ENCRYPTION_KEY must encode exactly 32 bytes")
        if AESGCM is None:
            raise StateError("The reviewed cryptography dependency is required for remote state")
        self._cipher = AESGCM(raw_key)
        self.repository, self.token, self.branch = repository, token, branch
        self.versions: dict[str, str | None] = {}

    def _aad(self, name: str) -> bytes:
        return json.dumps([STATE_FORMAT, self.repository.casefold(), self.branch, _state_path(name)],
                          separators=(",", ":")).encode("utf-8")

    def _encrypt(self, name: str, value: dict) -> bytes:
        if not isinstance(value, dict):
            raise StateError("State must be a JSON object")
        try:
            plaintext = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        except (TypeError, ValueError, UnicodeError):
            raise StateError("State cannot be encoded as JSON") from None
        if len(plaintext) > MAX_STATE_BYTES:
            raise StateError("State exceeds the supported size limit")
        nonce = os.urandom(12)
        ciphertext = self._cipher.encrypt(nonce, plaintext, self._aad(name))
        envelope = {"format": STATE_FORMAT, "nonce": base64.b64encode(nonce).decode("ascii"),
                    "ciphertext": base64.b64encode(ciphertext).decode("ascii")}
        encoded = json.dumps(envelope, separators=(",", ":")).encode("utf-8")
        # GitHub's base64 Contents response is supported only for small files.
        if len(encoded) > MAX_STATE_BYTES:
            raise StateError("Encrypted state exceeds the supported remote size limit")
        return encoded

    def _decrypt(self, name: str, encoded: bytes) -> dict:
        envelope = _state_object(encoded)
        if set(envelope) != {"format", "nonce", "ciphertext"} or envelope.get("format") != STATE_FORMAT:
            raise StateError("Plaintext or unsupported remote state is forbidden")
        try:
            nonce = base64.b64decode(envelope["nonce"], validate=True)
            ciphertext = base64.b64decode(envelope["ciphertext"], validate=True)
            if len(nonce) != 12 or len(ciphertext) < 16:
                raise ValueError("invalid encrypted envelope")
            plaintext = self._cipher.decrypt(nonce, ciphertext, self._aad(name))
        except Exception:
            # Authentication failures must never expose keys, provider objects,
            # ciphertext, recipient addresses, or the original exception.
            raise StateError("Encrypted state authentication failed; delivery is blocked") from None
        return _state_object(plaintext)

    def _request(self, path: str, method: str = "GET", data: dict | None = None):
        request = Request(
            "https://api.github.com/repos/" + self.repository + path,
            data=json.dumps(data).encode() if data is not None else None,
            method=method,
            headers={"Authorization": "Bearer " + self.token,
                     "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28",
                     "User-Agent": "LevyQuant-Digest",
                     "Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=30) as response:
                content = response.read(4 * MAX_STATE_BYTES + 1)
                if len(content) > 4 * MAX_STATE_BYTES:
                    raise StateError("GitHub state API response exceeds the size limit")
                return _state_object(content)
        except HTTPError as error:
            if error.code == 404:
                return None
            if error.code in (409, 422):
                raise StateConflict("Remote state conflict; stop before another send") from None
            raise StateError(f"GitHub state API returned HTTP {error.code}") from None
        except (URLError, TimeoutError, OSError):
            raise StateError("GitHub state could not be reached; delivery is blocked") from None

    def ensure_state_branch(self) -> None:
        """Create an encrypted-only root branch, or authenticate its marker.

        There is no plaintext migration or fallback for an existing branch.
        The marker catches wrong keys before creating a new day's edition.
        """
        repository = self._request("")
        if not repository:
            raise StateError("The intended GitHub repository is not accessible")
        ref_path = "/git/ref/heads/" + quote(self.branch, safe="")
        if self._request(ref_path) is None:
            marker = self._encrypt(_INITIAL_STATE_PATH, {"schema_version": 1, "encrypted_state": True})
            tree = self._request("/git/trees", "POST", {"tree": [{
                "path": _INITIAL_STATE_PATH, "mode": "100644", "type": "blob",
                "content": marker.decode("utf-8"),
            }]})
            if not tree or not tree.get("sha"):
                raise StateError("Encrypted state tree was not acknowledged")
            commit = self._request("/git/commits", "POST", {
                "message": "Initialize encrypted digest state [skip ci]", "tree": tree["sha"], "parents": [],
            })
            if not commit or not commit.get("sha"):
                raise StateError("Encrypted state commit was not acknowledged")
            ref = self._request("/git/refs", "POST", {"ref": "refs/heads/" + self.branch, "sha": commit["sha"]})
            if not ref or ref.get("object", {}).get("sha") != commit["sha"]:
                raise StateError("Encrypted state branch was not durably acknowledged")
        marker = self.load(_INITIAL_STATE_PATH)
        if marker != {"schema_version": 1, "encrypted_state": True}:
            raise StateError("Encrypted state initialization marker is missing or invalid")

    def ensure_private_branch(self) -> None:
        """Compatibility alias; authenticated encryption also permits public repos."""
        self.ensure_state_branch()

    def load(self, name: str) -> dict | None:
        _state_path(name)
        result = self._request("/contents/" + quote(name, safe="/") +
                               "?ref=" + quote(self.branch, safe=""))
        if result is None:
            self.versions[name] = None
            return None
        if result.get("encoding") != "base64":
            raise StateError("Unsupported state encoding")
        try:
            content = base64.b64decode(result["content"], validate=False)
        except (ValueError, KeyError, TypeError):
            raise StateError("Stored state has invalid content encoding") from None
        if len(content) > MAX_STATE_BYTES:
            raise StateError("Stored state exceeds the supported size limit")
        state = self._decrypt(name, content)
        if not isinstance(result.get("sha"), str) or not result["sha"]:
            raise StateError("Remote state version is missing")
        self.versions[name] = result["sha"]
        return state

    def list_edition_dates(self) -> list[str]:
        """Read filenames on the fixed state branch; never return private records."""
        result = self._request("/git/trees/" + quote(self.branch, safe="") + "?recursive=1")
        if (not isinstance(result, dict) or result.get("truncated") is not False
                or not isinstance(result.get("tree"), list) or len(result["tree"]) > 100000):
            raise StateError("Edition directory listing is incomplete")
        days = set()
        for entry in result["tree"]:
            if not isinstance(entry, dict):
                raise StateError("Edition directory listing is invalid")
            path = entry.get("path")
            if (entry.get("type") == "blob" and entry.get("mode") == "100644"
                    and isinstance(path, str)):
                day = _edition_day(path)
                if day:
                    days.add(day)
        return sorted(days)

    def save(self, name: str, value: dict) -> None:
        _state_path(name)
        if name not in self.versions:
            raise StateError("Load state before saving it")
        content = self._encrypt(name, value)
        data = {"message": "Persist digest delivery state [skip ci]", "branch": self.branch,
                "content": base64.b64encode(content).decode("ascii")}
        if self.versions[name]:
            data["sha"] = self.versions[name]
        result = self._request("/contents/" + quote(name, safe="/"), "PUT", data)
        if not result or not result.get("content", {}).get("sha"):
            raise StateError("State was not durably acknowledged; delivery is blocked")
        expected_sha = hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()
        if result["content"]["sha"] != expected_sha:
            raise StateError("State acknowledgement does not match the saved content; delivery is blocked")
        self.versions[name] = result["content"]["sha"]
