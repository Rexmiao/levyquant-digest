"""Offline immutable publication, recovery and archive input boundaries."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from levyquant import archive
from levyquant.state_store import LocalStateStore, StateConflict, StateError


def snapshot(day="2026-11-26", text="Public briefing"):
    return {"date": day, "subject": "LevyQuant morning briefing", "html": "<p>" + text + "</p>", "text": text}


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = LocalStateStore(self.root)

    def test_first_publication_is_immutable_and_only_four_public_fields_are_saved(self):
        first = {**snapshot(), "deliveries": {"private-hash": {"status": "accepted"}}, "email": "reader@example.org"}
        self.assertTrue(archive.publish_edition(self.store, first))
        self.assertFalse(archive.publish_edition(self.store, snapshot(text="A later private revision")))
        self.assertEqual(archive.read_edition(self.store, first["date"]), snapshot())
        self.assertEqual(archive.read_index(self.store), [first["date"]])
        self.assertNotIn("reader@example.org", (self.root / "archive/editions/2026-11-26.json").read_text())

    def test_index_failure_leaves_repairable_body_without_overwriting_first_copy(self):
        original = self.store.save
        def fail_index(path, value):
            if path == archive.INDEX_PATH:
                raise StateError("offline")
            original(path, value)
        with patch.object(self.store, "save", side_effect=fail_index):
            with self.assertRaises(StateError):
                archive.publish_edition(self.store, snapshot())
        self.assertEqual(archive.read_edition(self.store, "2026-11-26"), snapshot())
        self.assertEqual(archive.read_index(self.store), [])
        self.assertFalse(archive.publish_edition(self.store, snapshot(text="Must not replace orphan")))
        self.assertEqual(archive.read_index(self.store), ["2026-11-26"])
        self.assertEqual(archive.read_edition(self.store, "2026-11-26"), snapshot())

    def test_concurrent_index_writer_is_merged_after_definite_conflict(self):
        original = self.store.save
        raced = False
        def concurrent(path, value):
            nonlocal raced
            if path == archive.INDEX_PATH and not raced:
                raced = True
                other = LocalStateStore(self.root)
                archive.publish_edition(other, snapshot("2026-10-01"))
                raise StateConflict("offline conflict")
            original(path, value)
        with patch.object(self.store, "save", side_effect=concurrent):
            self.assertTrue(archive.publish_edition(self.store, snapshot()))
        self.assertEqual(archive.read_index(self.store), ["2026-11-26", "2026-10-01"])

    def test_concurrent_first_body_wins_and_index_retries_are_bounded(self):
        original = self.store.save
        raced = False
        def concurrent(path, value):
            nonlocal raced
            if path.startswith("archive/editions/") and not raced:
                raced = True
                other = LocalStateStore(self.root)
                archive.publish_edition(other, snapshot(text="First acknowledged version"))
                raise StateConflict("offline conflict")
            original(path, value)
        with patch.object(self.store, "save", side_effect=concurrent):
            self.assertFalse(archive.publish_edition(self.store, snapshot()))
        self.assertEqual(archive.read_edition(self.store, "2026-11-26")["text"], "First acknowledged version")
        self.store.load(archive.INDEX_PATH)
        self.store.save(archive.INDEX_PATH, {"schema_version": 1, "dates": []})
        with patch.object(self.store, "save", side_effect=StateConflict("offline conflict")) as save:
            with self.assertRaises(StateConflict):
                archive.publish_edition(self.store, snapshot())
        self.assertEqual(save.call_count, 3)

    def test_invalid_dates_private_action_links_and_oversized_copy_are_refused_before_write(self):
        invalid = [snapshot("2026-02-30"), snapshot("../private"), snapshot(text="https://example.hf.space/unsubscribe?id=opaque&token=secret"),
                   {**snapshot(), "html": '<a href="https://example.hf.space/confirm?id=opaque&amp;token=secret">Private</a>'},
                   {**snapshot(), "html": "x" * 600000, "text": "y" * 200000}]
        for value in invalid:
            with self.subTest(date=value["date"]), patch.object(self.store, "save") as save:
                with self.assertRaises(archive.ArchiveError):
                    archive.publish_edition(self.store, value)
                save.assert_not_called()

    def test_corrupt_index_or_snapshot_is_not_treated_as_empty(self):
        for value in ({"schema_version": True, "dates": []}, {"schema_version": 1, "dates": ["2026-02-30"]},
                      {"schema_version": 1, "dates": ["2026-11-26", "2026-11-26"]}):
            self.store.load(archive.INDEX_PATH)
            self.store.save(archive.INDEX_PATH, value)
            with self.assertRaises(archive.ArchiveError):
                archive.read_index(self.store)
        path = "archive/editions/2026-11-26.json"
        self.store.load(path)
        self.store.save(path, {**snapshot(), "private": "not a public document"})
        with self.assertRaises(archive.ArchiveError):
            archive.read_edition(self.store, "2026-11-26")


if __name__ == "__main__":
    unittest.main()
