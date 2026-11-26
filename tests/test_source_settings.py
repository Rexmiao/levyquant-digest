"""Offline shared keyword validation, strict records and optimistic concurrency."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from levyquant.source_settings import (
    SETTINGS_PATH, SourceSettingsError, default_moomoo_queries, read_moomoo_settings,
    validate_moomoo_queries, validate_moomoo_snapshot, write_moomoo_settings,
)
from levyquant.state_store import LocalStateStore, StateConflict, StateError


DEFAULTS = ["Default topic", "Another topic", "Example policy"]


def record(**updates):
    return {"schema_version": 1, "queries": ["Saved topic"], "revision": 1,
            "updated_at": "2026-11-26T12:00:00+00:00", **updates}


class SourceSettingsTests(unittest.TestCase):
    def test_missing_record_uses_independent_defaults_at_revision_zero_without_write(self):
        store = Mock()
        store.load.return_value = None
        value = read_moomoo_settings(store, DEFAULTS)
        self.assertEqual(value, {"queries": DEFAULTS, "revision": 0})
        store.load.assert_called_once_with(SETTINGS_PATH)
        store.save.assert_not_called()
        value["queries"].append("Changed locally")
        self.assertEqual(read_moomoo_settings(store, DEFAULTS)["queries"], DEFAULTS)

    def test_write_normalizes_queries_and_persists_only_versioned_utc_record(self):
        with tempfile.TemporaryDirectory() as directory:
            store = LocalStateStore(Path(directory))
            saved = write_moomoo_settings(store, [" Alpha ", "alpha", "Beta", " Beta "], 0, DEFAULTS)
            self.assertEqual(saved, {"queries": ["Alpha", "Beta"], "revision": 1})
            self.assertEqual(read_moomoo_settings(store, DEFAULTS), saved)
            stored = store.load(SETTINGS_PATH)
            self.assertEqual(set(stored), {"schema_version", "queries", "revision", "updated_at"})
            self.assertEqual(stored["schema_version"], 1)
            self.assertEqual(datetime.fromisoformat(stored["updated_at"]).utcoffset(), timezone.utc.utcoffset(None))
            newer = write_moomoo_settings(store, ["Replacement topic"], 1, DEFAULTS)
            self.assertEqual(newer["revision"], 2)
            self.assertEqual(read_moomoo_settings(store, DEFAULTS), newer)

    def test_stale_revision_and_store_cas_conflict_never_blindly_retry(self):
        store = Mock()
        store.load.return_value = record(revision=3)
        with self.assertRaises(StateConflict):
            write_moomoo_settings(store, ["Changed topic"], 2, DEFAULTS)
        store.load.assert_called_once_with(SETTINGS_PATH)
        store.save.assert_not_called()
        store.reset_mock()
        store.load.return_value = None
        store.save.side_effect = StateConflict("Concurrent write")
        with self.assertRaises(StateConflict):
            write_moomoo_settings(store, ["Changed topic"], 0, DEFAULTS)
        store.load.assert_called_once_with(SETTINGS_PATH)
        store.save.assert_called_once()

    def test_invalid_queries_or_snapshot_are_rejected_before_store_access(self):
        invalid = [[], ["x"] * 5, [""], [" "], [None], ["x" * 201], ["a\nb"],
                   ["a\tb"], ["a\u2028b"], ["a\u202eb"], "topic"]
        for queries in invalid:
            with self.subTest(queries=queries):
                store = Mock()
                with self.assertRaises(SourceSettingsError):
                    write_moomoo_settings(store, queries, 0, DEFAULTS)
                store.load.assert_not_called()
                store.save.assert_not_called()
        for value in ({"queries": ["Topic"], "revision": True}, {"queries": ["Topic"], "revision": -1},
                      {"queries": ["Topic"], "revision": 0, "updated_at": "not exposed"}, {"queries": ["Topic"]}):
            with self.subTest(value=value), self.assertRaises(SourceSettingsError):
                validate_moomoo_snapshot(value)
        self.assertEqual(validate_moomoo_queries(["x" * 200]), ["x" * 200])

    def test_bad_records_do_not_fall_back_or_expose_stored_values(self):
        invalid = [{}, record(schema_version=True), record(revision=0), record(revision=True),
                   record(queries=[" Trimmed "]), record(queries=["Topic", "topic"]),
                   record(queries=[]), record(updated_at="2026-11-26"),
                   record(updated_at="2026-11-26T12:00:00-05:00"),
                   record(updated_at="2026-11-26T12:00:00-00:00"),
                   {**record(), "extra": "sensitive-provider-data"}]
        for value in invalid:
            with self.subTest(value=value):
                store = Mock()
                store.load.return_value = value
                with self.assertRaises(StateError) as captured:
                    read_moomoo_settings(store, DEFAULTS)
                self.assertNotIn("sensitive", str(captured.exception))
                store.save.assert_not_called()

    def test_read_failures_stop_instead_of_replacing_settings_with_defaults(self):
        for error in (StateError("Offline unavailable"), OSError("sensitive-provider-data")):
            store = Mock()
            store.load.side_effect = error
            with self.assertRaises(StateError) as captured:
                read_moomoo_settings(store, DEFAULTS)
            self.assertNotIn("sensitive", str(captured.exception))
            store.save.assert_not_called()

    def test_manifest_defaults_are_taken_only_from_the_unique_fixed_source(self):
        target = {"id": "moomoo_news_search", "kind": "moomoo_search", "queries": DEFAULTS}
        sources = [{"id": "other", "kind": "moomoo_search", "queries": ["Unrelated"]}, deepcopy(target)]
        self.assertEqual(default_moomoo_queries(sources), DEFAULTS)
        for value in ([], [target, target], [{**target, "kind": "publisher_feed"}]):
            with self.subTest(value=value), self.assertRaises(SourceSettingsError):
                default_moomoo_queries(value)

    def test_snapshot_is_a_fresh_credential_free_normalized_value(self):
        supplied = {"queries": [" Topic ", "topic"], "revision": 7}
        value = validate_moomoo_snapshot(supplied)
        self.assertEqual(value, {"queries": ["Topic"], "revision": 7})
        value["queries"].append("Other")
        self.assertEqual(supplied, {"queries": [" Topic ", "topic"], "revision": 7})


if __name__ == "__main__":
    unittest.main()
