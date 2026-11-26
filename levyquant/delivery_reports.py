"""Credential-free delivery activity metadata over the existing encrypted store.

Only the CLI writes run reports. These helpers never contact a provider, send
mail, expose recipient hashes, or infer inbox arrival from SMTP acceptance.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date as CalendarDate, datetime, timedelta, timezone
import re

from .state_store import StateConflict, StateError


REPORTS_PATH = "reports/delivery-activity.json"
MAX_RUNS = 50
COUNT_FIELDS = ("recipient_count", "accepted", "rejected", "uncertain", "reserved", "pending",
                "skipped_unsubscribed", "internal_count", "already_accepted", "blocked_or_failed")
SUMMARY_FIELDS = COUNT_FIELDS[:-1]
MODES = frozenset({"send", "preview", "preview-email", "smtp-test"})
STATUSES = frozenset({"running", "completed", "failed", "needs_attention"})
RESULT_CODES = frozenset({"running", "completed", "failed", "needs_attention", "accepted", "smtp_test_accepted",
    "preview_ready_no_mail_sent", "preview_email_accepted", "all_submissions_accepted", "delivery_needs_attention"})
ERROR_TYPES = frozenset({"Exception", "RuntimeError", "ValueError", "TypeError", "ConfigurationError",
    "EditorError", "EditorValidationError", "StateError", "StateConflict", "DeliveryError", "DeliveryUncertain",
    "SourceSettingsError", "AdminAuthError"})
ERROR_CODES = frozenset({"execution_failed", "configuration_failed", "source_failed", "editor_failed",
    "editor_validation_failed", "state_failed", "smtp_failed", "unknown_error"})
_DELIVERY_STATUSES = frozenset({"accepted", "rejected", "uncertain", "reserved", "skipped_unsubscribed"})


class DeliveryReportError(StateError):
    """A fixed safe error message without rejected input or provider details."""


def _invalid():
    raise DeliveryReportError("Delivery report metadata is invalid")


def _date(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        _invalid()
    try:
        if CalendarDate.fromisoformat(value).isoformat() != value:
            _invalid()
    except ValueError:
        _invalid()
    return value


def _stamp(value):
    try:
        if not isinstance(value, str) or len(value) > 40 or not value.endswith(("Z", "+00:00")):
            raise ValueError
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if moment.tzinfo is None or moment.utcoffset() != timedelta(0):
            raise ValueError
        return moment.astimezone(timezone.utc).isoformat()
    except (ValueError, TypeError, OverflowError):
        _invalid()


def _count(value):
    if type(value) is not int or not 0 <= value <= 100:
        _invalid()
    return value


def _safe_report(report):
    if (not isinstance(report, dict)
            or not isinstance(report.get("run_id"), str)
            or not re.fullmatch(r"[0-9]{1,32}", report["run_id"])
            or not isinstance(report.get("mode"), str) or report["mode"] not in MODES
            or not isinstance(report.get("status"), str) or report["status"] not in STATUSES
            or not isinstance(report.get("result_code"), str) or report["result_code"] not in RESULT_CODES):
        _invalid()
    value = {"run_id": report["run_id"], "mode": report["mode"], "date": _date(report.get("date")),
             "status": report["status"], "started_at": _stamp(report.get("started_at")),
             "updated_at": _stamp(report.get("updated_at")), "result_code": report["result_code"]}
    if value["updated_at"] < value["started_at"]:
        _invalid()
    for field in COUNT_FIELDS:
        if field in report:
            value[field] = _count(report[field])
    if "error_type" in report:
        kind = report["error_type"]
        value["error_type"] = kind if isinstance(kind, str) and kind in ERROR_TYPES else "Exception"
    if "error_code" in report:
        code = report["error_code"]
        value["error_code"] = code if isinstance(code, str) and code in ERROR_CODES else "execution_failed"
    # Unrecognised fields are never copied into encrypted metadata or responses.
    return value


def _read(store):
    try:
        value = store.load(REPORTS_PATH)
    except StateError:
        raise DeliveryReportError("Delivery reports could not be read") from None
    except Exception:
        raise DeliveryReportError("Delivery reports could not be read") from None
    if value is None:
        return []
    if (not isinstance(value, dict) or set(value) != {"schema_version", "runs"}
            or type(value.get("schema_version")) is not int or value["schema_version"] != 1
            or not isinstance(value.get("runs"), list) or len(value["runs"]) > MAX_RUNS):
        _invalid()
    rows = [_safe_report(row) for row in value["runs"]]
    if len({row["run_id"] for row in rows}) != len(rows):
        _invalid()
    return rows


def _ordered(rows):
    return sorted(rows, key=lambda row: (row["updated_at"], int(row["run_id"])), reverse=True)[:MAX_RUNS]


def read_run_reports(store) -> list[dict]:
    """Read at most fifty safe metadata rows, newest update first."""
    return deepcopy(_ordered(_read(store)))


def record_run_report(store, report: dict) -> dict:
    """Merge one run using at most three fresh reads/CAS saves.

    A stale update or a repeated running marker cannot replace a terminal
    outcome. Retried terminal outcomes may advance the same run, while the
    original mode, New York edition date and first start time remain anchored.
    """
    incoming = _safe_report(report)
    for attempt in range(3):
        rows = _read(store)
        prior = next((row for row in rows if row["run_id"] == incoming["run_id"]), None)
        merged = deepcopy(incoming)
        if prior is not None:
            if any(prior[key] != incoming[key] for key in ("mode", "date")):
                _invalid()
            if (incoming["updated_at"] < prior["updated_at"]
                    or prior["status"] != "running" and incoming["status"] == "running"):
                return deepcopy(prior)
            merged["started_at"] = prior["started_at"]
            if merged == prior:
                return deepcopy(prior)
        combined = _ordered([row for row in rows if row["run_id"] != incoming["run_id"]] + [merged])
        try:
            store.save(REPORTS_PATH, {"schema_version": 1, "runs": combined})
        except StateConflict:
            if attempt < 2:
                continue
            raise StateConflict("Delivery report update conflicted") from None
        except Exception:
            raise DeliveryReportError("Delivery report could not be saved") from None
        return deepcopy(merged)
    raise StateConflict("Delivery report update conflicted")


def summarize_edition(edition: dict) -> dict:
    """Summarize a send edition without returning addresses or recipient hashes.

    Legacy delivery maps establish recorded outcomes only. Missing planned or
    internal totals remain null; an all-accepted legacy map is not evidence that
    every intended recipient was submitted, and no count proves inbox arrival.
    """
    if not isinstance(edition, dict) or edition.get("mode") not in ("live", "send"):
        _invalid()
    result = {"date": _date(edition.get("date")), "mode": "send"}
    summary = edition.get("delivery_summary")
    if summary is not None:
        if not isinstance(summary, dict) or any(field not in summary for field in SUMMARY_FIELDS):
            _invalid()
        counts = {field: _count(summary[field]) for field in SUMMARY_FIELDS}
        if (sum(counts[field] for field in ("accepted", "rejected", "uncertain", "reserved", "pending", "skipped_unsubscribed"))
                != counts["recipient_count"] or counts["internal_count"] > counts["recipient_count"]
                or counts["already_accepted"] > counts["accepted"]):
            _invalid()
        if counts["rejected"] or counts["uncertain"] or counts["reserved"]:
            status = "needs_attention"
        elif counts["pending"]:
            status = "running"
        else:
            status = "completed"
        return {**result, "status": status, **counts, "legacy_counts": False}

    deliveries = edition.get("deliveries")
    if not isinstance(deliveries, dict) or len(deliveries) > 100:
        _invalid()
    known = {status: 0 for status in _DELIVERY_STATUSES}
    for record in deliveries.values():
        if not isinstance(record, dict):
            _invalid()
        state = record.get("status")
        if isinstance(state, str) and state in _DELIVERY_STATUSES:
            known[state] += 1
    status = "needs_attention" if any(known[key] for key in ("rejected", "uncertain", "reserved")) else "unknown"
    return {**result, "status": status, "recipient_count": None,
            "accepted": known["accepted"], "rejected": known["rejected"], "uncertain": known["uncertain"],
            "reserved": known["reserved"], "pending": None, "skipped_unsubscribed": known["skipped_unsubscribed"],
            "internal_count": None, "already_accepted": None, "legacy_counts": True}
