"""Offline metadata sanitization, bounded CAS merges and honest legacy counts."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import unittest
from unittest.mock import Mock

from levyquant import delivery_reports as reports
from levyquant.state_store import StateConflict, StateError


NOW = datetime(2026, 11, 26, 12, tzinfo=timezone.utc)


def report(run_id="1", **updates):
    return {"run_id": run_id, "mode": "send", "date": "2026-11-26", "status": "running",
            "started_at": NOW.isoformat(), "updated_at": NOW.isoformat(), "result_code": "running", **updates}


def registry(*rows):
    return {"schema_version": 1, "runs": list(rows)}


class MemoryStore:
    def __init__(self, value=None):
        self.value = deepcopy(value)
        self.saves = []

    def load(self, path):
        if path != reports.REPORTS_PATH:
            raise AssertionError("unexpected report path")
        return deepcopy(self.value)

    def save(self, path, value):
        if path != reports.REPORTS_PATH:
            raise AssertionError("unexpected report path")
        self.value = deepcopy(value)
        self.saves.append(deepcopy(value))


class DeliveryReportTests(unittest.TestCase):
    def test_only_safe_fields_are_persisted_and_read_back(self):
        store = MemoryStore()
        source = report(message="private-provider-body", email="private@example.org", token="private-token",
                        url="https://private.example.org", accepted=2, error_type="private-type", error_code="private-code")
        saved = reports.record_run_report(store, source)
        self.assertEqual(saved["error_type"], "Exception")
        self.assertEqual(saved["error_code"], "execution_failed")
        self.assertEqual(reports.read_run_reports(store), [saved])
        encoded = json.dumps(store.value)
        for value in ("private-provider-body", "private@example.org", "private-token", "https://private.example.org",
                      "private-type", "private-code"):
            self.assertNotIn(value, encoded)
        saved["accepted"] = 99
        self.assertEqual(reports.read_run_reports(store)[0]["accepted"], 2)

    def test_conflict_reloads_and_preserves_another_run(self):
        other = report("2", updated_at=(NOW + timedelta(seconds=1)).isoformat())
        store = MemoryStore()
        original_save = store.save
        attempts = []
        def save(path, value):
            attempts.append(deepcopy(value))
            if len(attempts) == 1:
                store.value = registry(other)
                raise StateConflict("private-provider-value")
            original_save(path, value)
        store.save = save
        reports.record_run_report(store, report())
        self.assertEqual(len(attempts), 2)
        self.assertEqual({row["run_id"] for row in reports.read_run_reports(store)}, {"1", "2"})

    def test_conflict_attempts_are_bounded_and_uncertain_writes_are_not_retried(self):
        store = Mock()
        store.load.return_value = None
        store.save.side_effect = StateConflict("private-provider-value")
        with self.assertRaises(StateConflict) as captured:
            reports.record_run_report(store, report())
        self.assertEqual(store.save.call_count, 3)
        self.assertEqual(store.load.call_count, 3)
        self.assertNotIn("private", str(captured.exception))
        store.reset_mock()
        store.save.side_effect = OSError("private-provider-value")
        with self.assertRaises(reports.DeliveryReportError) as captured:
            reports.record_run_report(store, report())
        self.assertEqual(store.save.call_count, 1)
        self.assertNotIn("private", str(captured.exception))

    def test_terminal_outcome_cannot_regress_to_running_or_a_stale_outcome(self):
        final = report(status="completed", result_code="all_submissions_accepted", accepted=2,
                       updated_at=(NOW + timedelta(seconds=5)).isoformat())
        store = MemoryStore(registry(final))
        later_running = report(updated_at=(NOW + timedelta(seconds=10)).isoformat())
        self.assertEqual(reports.record_run_report(store, later_running), final)
        self.assertEqual(reports.record_run_report(store, report(status="failed", result_code="failed")), final)
        self.assertEqual(store.saves, [])

    def test_terminal_retry_updates_same_run_without_changing_its_first_start(self):
        first = report(status="failed", result_code="failed")
        store = MemoryStore(registry(first))
        retry_time = (NOW + timedelta(seconds=10)).isoformat()
        updated = reports.record_run_report(store, report(started_at=retry_time, updated_at=retry_time,
                                            status="completed", result_code="all_submissions_accepted", accepted=1))
        self.assertEqual(updated["started_at"], first["started_at"])
        self.assertEqual(updated["status"], "completed")
        self.assertEqual(len(reports.read_run_reports(store)), 1)
        for change in ({"mode": "preview"}, {"date": "2026-11-27"}):
            with self.subTest(change=change), self.assertRaises(reports.DeliveryReportError):
                reports.record_run_report(store, report(**change))

    def test_only_fifty_latest_runs_remain(self):
        rows = [report(str(index), updated_at=(NOW + timedelta(seconds=index)).isoformat()) for index in range(50)]
        store = MemoryStore(registry(*rows))
        reports.record_run_report(store, report("50", updated_at=(NOW + timedelta(seconds=50)).isoformat()))
        result = reports.read_run_reports(store)
        self.assertEqual(len(result), 50)
        self.assertEqual(result[0]["run_id"], "50")
        self.assertNotIn("0", {row["run_id"] for row in result})

    def test_invalid_metadata_and_counts_fail_before_state_access(self):
        changes = [{"run_id": "private@example.org"}, {"mode": "arbitrary"}, {"date": "2026-02-30"},
                   {"status": "sent_to_inbox"}, {"started_at": "2026-11-26T12:00:00"},
                   {"updated_at": "2026-11-26T12:00:00-00:00"}, {"updated_at": "2026-11-25T12:00:00Z"},
                   {"accepted": True}, {"accepted": -1}, {"accepted": 101}, {"result_code": "private-provider-value"}]
        for change in changes:
            with self.subTest(field=tuple(change)):
                store = Mock()
                with self.assertRaises(reports.DeliveryReportError) as captured:
                    reports.record_run_report(store, report(**change))
                self.assertNotIn("private", str(captured.exception))
                store.load.assert_not_called()
                store.save.assert_not_called()

    def test_invalid_or_unreachable_registry_does_not_become_empty_history(self):
        for value in ({}, registry(report(), report()), {"schema_version": True, "runs": []},
                      {"schema_version": 1, "runs": [], "private": "private-value"}):
            with self.subTest(kind=type(value).__name__), self.assertRaises(reports.DeliveryReportError):
                reports.read_run_reports(MemoryStore(value))
        store = Mock()
        store.load.side_effect = StateError("private-provider-value")
        with self.assertRaises(reports.DeliveryReportError) as captured:
            reports.read_run_reports(store)
        self.assertNotIn("private", str(captured.exception))
        store.save.assert_not_called()

    def test_safe_reader_drops_unrecognized_record_fields(self):
        result = reports.read_run_reports(MemoryStore(registry(report(email="private@example.org", message="private-message"))))
        self.assertNotIn("private", json.dumps(result))


def edition(**updates):
    summary = {"recipient_count": 4, "accepted": 2, "rejected": 0, "uncertain": 0, "reserved": 0,
               "pending": 1, "skipped_unsubscribed": 1, "internal_count": 1, "already_accepted": 1}
    return {"date": "2026-11-26", "mode": "live", "delivery_summary": summary, **updates}


class EditionSummaryTests(unittest.TestCase):
    def test_explicit_summary_includes_skips_and_prior_acceptances_without_addresses(self):
        original = edition(email="private@example.org")
        summary = reports.summarize_edition(original)
        self.assertEqual(summary["mode"], "send")
        self.assertEqual(summary["status"], "running")
        self.assertEqual(summary["skipped_unsubscribed"], 1)
        self.assertEqual(summary["already_accepted"], 1)
        self.assertFalse(summary["legacy_counts"])
        self.assertNotIn("private", json.dumps(summary))
        summary["accepted"] = 99
        self.assertEqual(original["delivery_summary"]["accepted"], 2)

    def test_completed_and_attention_status_are_distinct_from_inbox_delivery(self):
        base = edition()["delivery_summary"]
        finished = {**base, "accepted": 3, "pending": 0}
        self.assertEqual(reports.summarize_edition(edition(delivery_summary=finished))["status"], "completed")
        for field in ("rejected", "uncertain", "reserved"):
            value = {**base, field: 1, "pending": 0}
            with self.subTest(field=field):
                self.assertEqual(reports.summarize_edition(edition(delivery_summary=value))["status"], "needs_attention")

    def test_legacy_records_never_infer_unknown_total_internal_or_pending_counts(self):
        value = edition(delivery_summary=None, deliveries={"a" * 64: {"status": "accepted"},
                                                          "b" * 64: {"status": "accepted"}})
        summary = reports.summarize_edition(value)
        self.assertEqual(summary["accepted"], 2)
        self.assertEqual(summary["status"], "unknown")
        self.assertTrue(summary["legacy_counts"])
        for field in ("recipient_count", "internal_count", "pending", "already_accepted"):
            self.assertIsNone(summary[field])
        self.assertNotIn("a" * 64, json.dumps(summary))

    def test_legacy_unknown_outcomes_are_not_invented_as_pending_or_reserved(self):
        value = edition(delivery_summary=None, deliveries={"a" * 64: {"status": "accepted"},
                                                          "b" * 64: {"status": "old-unknown"}})
        summary = reports.summarize_edition(value)
        self.assertEqual((summary["accepted"], summary["reserved"], summary["pending"]), (1, 0, None))
        self.assertEqual(summary["status"], "unknown")
        value["deliveries"]["c" * 64] = {"status": "uncertain"}
        self.assertEqual(reports.summarize_edition(value)["status"], "needs_attention")

    def test_bad_summary_or_preview_never_masquerades_as_send(self):
        for value in (edition(mode="preview"), edition(date="2026-02-30"), edition(delivery_summary={}),
                      edition(delivery_summary={**edition()["delivery_summary"], "accepted": True}),
                      edition(delivery_summary={**edition()["delivery_summary"], "recipient_count": 3}),
                      edition(delivery_summary={**edition()["delivery_summary"], "already_accepted": 3})):
            with self.subTest(mode=value.get("mode")), self.assertRaises(reports.DeliveryReportError):
                reports.summarize_edition(value)


if __name__ == "__main__":
    unittest.main()
