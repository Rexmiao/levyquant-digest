"""Immutable public snapshots, separate from private delivery records."""
from __future__ import annotations

from copy import deepcopy
from datetime import date
from html import unescape
import json
import re
from urllib.parse import parse_qs, urlsplit

from .state_store import StateConflict, StateError

INDEX_PATH = "archive/index.json"
MAX_DATES = 20000
MAX_SNAPSHOT_BYTES = 700 * 1024
FIELDS = ("date", "subject", "html", "text")
_URL = re.compile(r"https?://[^\s<>\"']+")


class ArchiveError(StateError):
    """A fixed error without source contents or private URLs."""


def validate_date(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ArchiveError("Archive date is invalid")
    try:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError
    except ValueError:
        raise ArchiveError("Archive date is invalid") from None
    return value


def public_fields(value: dict) -> dict:
    """Select public base copy; refuse known recipient-specific action URLs."""
    limits = {"date": 10, "subject": 300, "html": 600000, "text": 300000}
    if not isinstance(value, dict):
        raise ArchiveError("Archive snapshot is invalid")
    result = {}
    for field, limit in limits.items():
        content = value.get(field)
        if not isinstance(content, str) or not content.strip() or len(content) > limit:
            raise ArchiveError("Archive snapshot is invalid")
        result[field] = content
    validate_date(result["date"])
    if any(ord(char) < 32 or ord(char) == 127 for char in result["subject"]):
        raise ArchiveError("Archive snapshot is invalid")
    for match in _URL.finditer(unescape(result["html"] + "\n" + result["text"])):
        try:
            link = urlsplit(match.group())
            parameters = parse_qs(link.query)
        except ValueError:
            continue
        if link.path in ("/confirm", "/unsubscribe", "/one-click-unsubscribe") and {"id", "token"} <= parameters.keys():
            raise ArchiveError("Personalized action links cannot be archived")
    try:
        size = len(json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8"))
    except (ValueError, TypeError, UnicodeError):
        raise ArchiveError("Archive snapshot is invalid") from None
    if size > MAX_SNAPSHOT_BYTES:
        raise ArchiveError("Archive snapshot exceeds the supported size limit")
    return result


def read_index(store) -> list[str]:
    value = store.load(INDEX_PATH)
    if value is None:
        return []
    if (not isinstance(value, dict) or set(value) != {"schema_version", "dates"}
            or type(value["schema_version"]) is not int or value["schema_version"] != 1
            or not isinstance(value["dates"], list) or len(value["dates"]) > MAX_DATES):
        raise ArchiveError("Archive index is invalid")
    dates = [validate_date(day) for day in value["dates"]]
    if dates != sorted(set(dates), reverse=True):
        raise ArchiveError("Archive index is invalid")
    return dates


def read_edition(store, day: str) -> dict | None:
    validate_date(day)
    value = store.load("archive/editions/" + day + ".json")
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != set(FIELDS):
        raise ArchiveError("Archive snapshot is invalid")
    result = public_fields(value)
    if result["date"] != day:
        raise ArchiveError("Archive snapshot date does not match")
    return result


def publish_edition(store, value: dict) -> bool:
    """Save the first body, then merge the index; retry can repair an orphan.

    An existing date always keeps its original body. Only definite CAS
    conflicts are retried, and never more than three attempts per document.
    """
    snapshot = public_fields(value)
    day = snapshot["date"]
    created = False
    for attempt in range(3):
        previous = read_edition(store, day)
        if previous is not None:
            break
        try:
            store.save("archive/editions/" + day + ".json", deepcopy(snapshot))
            created = True
            break
        except StateConflict:
            if attempt == 2:
                raise
    for attempt in range(3):
        dates = read_index(store)
        if day in dates:
            return created
        if len(dates) >= MAX_DATES:
            raise ArchiveError("Archive index exceeds the supported size limit")
        try:
            store.save(INDEX_PATH, {"schema_version": 1, "dates": sorted([*dates, day], reverse=True)})
            return created
        except StateConflict:
            if attempt == 2:
                raise
    raise ArchiveError("Archive could not be published")
