"""Shared keyword settings over the existing authenticated encrypted CAS store."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unicodedata

from .state_store import StateConflict, StateError


SETTINGS_PATH = "settings/moomoo.json"
MOOMOO_SOURCE_ID = "moomoo_news_search"
MOOMOO_SOURCE_KIND = "moomoo_search"
_INPUT_CODES = frozenset({"invalid_moomoo_settings", "invalid_moomoo_queries",
                          "invalid_moomoo_snapshot", "invalid_moomoo_source"})


class SourceSettingsError(ValueError):
    """Fixed input/configuration code, never the rejected query or state value."""
    def __init__(self, code="invalid_moomoo_settings"):
        self.code = code if isinstance(code, str) and code in _INPUT_CODES else "invalid_moomoo_settings"
        super().__init__(self.code)


def validate_moomoo_queries(queries) -> list[str]:
    """Accept 1–4 rows; trim and casefold-dedupe, preserving first spelling/order.

    Controls, format controls, surrogates and line/paragraph separators are
    rejected before trimming. Each resulting query contains 1–200 characters.
    """
    if not isinstance(queries, list) or not 1 <= len(queries) <= 4:
        raise SourceSettingsError("invalid_moomoo_queries")
    result, seen = [], set()
    for query in queries:
        if not isinstance(query, str) or any(unicodedata.category(char) in {"Cc", "Cf", "Cs", "Zl", "Zp"}
                                             for char in query):
            raise SourceSettingsError("invalid_moomoo_queries")
        query = query.strip()
        if not 1 <= len(query) <= 200:
            raise SourceSettingsError("invalid_moomoo_queries")
        folded = query.casefold()
        if folded not in seen:
            seen.add(folded)
            result.append(query)
    return result


def validate_moomoo_snapshot(snapshot) -> dict:
    """Validate the credential-free UI/preview snapshot; revision zero is default."""
    if (not isinstance(snapshot, dict) or set(snapshot) != {"queries", "revision"}
            or type(snapshot.get("revision")) is not int or snapshot["revision"] < 0):
        raise SourceSettingsError("invalid_moomoo_snapshot")
    return {"queries": validate_moomoo_queries(snapshot["queries"]), "revision": snapshot["revision"]}


def default_moomoo_queries(sources) -> list[str]:
    """Read the one fixed manifest source; never derive defaults from other feeds."""
    if not isinstance(sources, list):
        raise SourceSettingsError("invalid_moomoo_source")
    matches = [source for source in sources if isinstance(source, dict) and source.get("id") == MOOMOO_SOURCE_ID]
    if len(matches) != 1 or matches[0].get("kind") != MOOMOO_SOURCE_KIND:
        raise SourceSettingsError("invalid_moomoo_source")
    return validate_moomoo_queries(matches[0].get("queries"))


def _stored_snapshot(value) -> dict:
    try:
        if (not isinstance(value, dict) or set(value) != {"schema_version", "queries", "revision", "updated_at"}
                or type(value.get("schema_version")) is not int or value["schema_version"] != 1
                or type(value.get("revision")) is not int or value["revision"] < 1
                or not isinstance(value.get("updated_at"), str)
                or not value["updated_at"].endswith(("Z", "+00:00"))):
            raise ValueError
        moment = datetime.fromisoformat(value["updated_at"].replace("Z", "+00:00"))
        if moment.tzinfo is None or moment.utcoffset() != timedelta(0):
            raise ValueError
        snapshot = validate_moomoo_snapshot({"queries": value["queries"], "revision": value["revision"]})
        if snapshot["queries"] != value["queries"]:
            raise ValueError
    except (ValueError, TypeError, OverflowError):
        raise StateError("Stored Moomoo settings are invalid") from None
    return snapshot


def read_moomoo_settings(store, default_queries) -> dict:
    """Only a missing record uses manifest defaults; read/schema errors propagate."""
    defaults = validate_moomoo_queries(default_queries)
    try:
        value = store.load(SETTINGS_PATH)
    except StateError:
        raise
    except Exception:
        raise StateError("Moomoo settings could not be read") from None
    return {"queries": defaults, "revision": 0} if value is None else _stored_snapshot(value)


def write_moomoo_settings(store, queries, expected_revision, default_queries) -> dict:
    """One revision check and one CAS save; conflicts are never blindly retried."""
    desired = validate_moomoo_snapshot({"queries": queries, "revision": expected_revision})
    current = read_moomoo_settings(store, default_queries)
    if current["revision"] != desired["revision"]:
        raise StateConflict("Moomoo settings revision conflict")
    revision = current["revision"] + 1
    value = {"schema_version": 1, "queries": desired["queries"], "revision": revision,
             "updated_at": datetime.now(timezone.utc).isoformat()}
    try:
        store.save(SETTINGS_PATH, value)
    except StateConflict:
        raise StateConflict("Moomoo settings revision conflict") from None
    except StateError:
        raise
    except Exception:
        raise StateError("Moomoo settings could not be saved") from None
    return {"queries": list(desired["queries"]), "revision": revision}
