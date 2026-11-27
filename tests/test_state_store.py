import base64
from copy import deepcopy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import unquote

from levyquant.state_store import LocalStateStore, GitHubStateStore, StateConflict, StateError, STATE_FORMAT


KEY = base64.urlsafe_b64encode(bytes(range(32))).decode("ascii")
OTHER_KEY = base64.urlsafe_b64encode(bytes(reversed(range(32)))).decode("ascii")
NAME = "editions/2026-11-26.json"


def content_record(content):
    sha = hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()
    return {"encoding": "base64", "content": base64.b64encode(content).decode("ascii"), "sha": sha}


class FakeGitHub:
    """Only the scoped Git Database/Contents contract, entirely in memory."""
    def __init__(self, *, private=False):
        self.private = private
        self.exists = False
        self.files = {}
        self.calls = []
        self.tree = None
        self.lost_ack = False

    def __call__(self, path, method="GET", data=None):
        self.calls.append((path, method, deepcopy(data)))
        if path == "":
            return {"private": self.private, "default_branch": "main"}
        if path.startswith("/git/ref/heads/"):
            return {"object": {"sha": "root-commit"}} if self.exists else None
        if path == "/git/trees":
            self.tree = data["tree"]
            return {"sha": "new-tree"}
        if path == "/git/commits":
            return {"sha": "root-commit"}
        if path == "/git/refs":
            self.exists = True
            self.files.update({entry["path"]: content_record(entry["content"].encode()) for entry in self.tree})
            return {"object": {"sha": data["sha"]}}
        if path.startswith("/contents/"):
            name = unquote(path[len("/contents/"):].split("?", 1)[0])
            if method == "GET":
                return deepcopy(self.files.get(name))
            if method == "PUT":
                current = self.files.get(name)
                if data.get("sha") != (current["sha"] if current else None):
                    raise StateConflict("remote CAS conflict")
                record = content_record(base64.b64decode(data["content"]))
                self.files[name] = record
                return None if self.lost_ack else {"content": {"sha": record["sha"]}}
        raise AssertionError("Unexpected fake API request")


class StateStoreTests(unittest.TestCase):
    def test_date_listing_is_readonly_calendar_validated_and_does_not_read_contents(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            editions = root / "editions"
            editions.mkdir()
            for name in ("2026-11-27.json", "2026-11-26.json", "2026-02-31.json", "private.json"):
                (editions / name).write_text("not even valid JSON", encoding="utf-8")
            (editions / "nested").mkdir()
            (editions / "nested/2026-11-25.json").write_text("private", encoding="utf-8")
            store = LocalStateStore(root)
            self.assertEqual(store.list_edition_dates(), ["2026-11-26", "2026-11-27"])
            self.assertEqual(store.versions, {})

    def test_reservation_survives_later_failure_and_conflicting_writer_stops(self):
        with tempfile.TemporaryDirectory() as directory:
            one, two = LocalStateStore(directory), LocalStateStore(directory)
            self.assertIsNone(one.load("editions/2026-11-25.json"))
            self.assertIsNone(two.load("editions/2026-11-25.json"))
            one.save("editions/2026-11-25.json", {"delivery": {"hash": "reserved"}})
            with self.assertRaises(StateConflict):
                two.save("editions/2026-11-25.json", {"delivery": {"hash": "sent"}})
            again = LocalStateStore(directory)
            self.assertEqual(again.load("editions/2026-11-25.json")["delivery"]["hash"], "reserved")

    def test_path_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(StateError):
                LocalStateStore(directory).load("../outside.json")


class EncryptedRemoteStateTests(unittest.TestCase):
    def test_date_listing_only_uses_fixed_branch_regular_blobs_and_rejects_incomplete_tree(self):
        store = self.store()
        entries = [{"path": name, "type": "blob", "mode": "100644"} for name in (
            "editions/2026-11-27.json", "editions/2026-11-26.json", "editions/2026-02-31.json",
            "subscribers/2026-11-25.json", "editions/nested/2026-11-25.json", "public/latest.json")]
        entries.append({"path": "editions/2026-11-24.json", "type": "blob", "mode": "120000"})
        store._request = Mock(return_value={"tree": entries, "truncated": False})
        self.assertEqual(store.list_edition_dates(), ["2026-11-26", "2026-11-27"])
        store._request.assert_called_once_with("/git/trees/delivery-state?recursive=1")
        self.assertEqual(store.versions, {})
        for value in ({"tree": entries, "truncated": True}, {"tree": entries}, None):
            store._request = Mock(return_value=value)
            with self.assertRaises(StateError):
                store.list_edition_dates()

    def setUp(self):
        self.api = FakeGitHub()

    def store(self, *, key=KEY, repository="owner/repo", branch="delivery-state"):
        store = GitHubStateStore(repository, "not-a-real-token", encryption_key=key, branch=branch)
        store._request = self.api
        return store

    def write_state(self, value=None):
        store = self.store()
        store.load(NAME)
        store.save(NAME, value or {"recipient": "private@example.org", "html": "Private frozen body", "status": "reserved"})
        return store

    def test_public_repository_gets_an_encrypted_only_orphan_branch(self):
        store = self.store()
        store.ensure_state_branch()
        self.assertTrue(self.api.exists)
        self.assertEqual(set(self.api.files), {"_state.json"})
        marker = json.loads(base64.b64decode(self.api.files["_state.json"]["content"]))
        self.assertEqual(set(marker), {"format", "nonce", "ciphertext"})
        self.assertEqual(marker["format"], STATE_FORMAT)
        commit = next(data for path, method, data in self.api.calls if path == "/git/commits")
        self.assertEqual(commit["parents"], [])
        self.assertFalse(any("main" in path for path, _, _ in self.api.calls))
        before = len(self.api.calls)
        store.ensure_private_branch()  # Compatibility alias also accepts public.
        self.assertFalse(any(method != "GET" for _, method, _ in self.api.calls[before:]))

    def test_private_repository_uses_the_same_mandatory_encryption(self):
        self.api.private = True
        self.store().ensure_state_branch()
        self.assertIn("_state.json", self.api.files)

    def test_transparent_round_trip_uploads_only_ciphertext_and_random_nonce(self):
        state = {"recipient": "private@example.org", "html": "Private frozen body", "status": "reserved"}
        store = self.write_state(state)
        encoded = base64.b64decode(self.api.files[NAME]["content"])
        envelope = json.loads(encoded)
        self.assertEqual(envelope["format"], STATE_FORMAT)
        self.assertEqual(len(base64.b64decode(envelope["nonce"])), 12)
        self.assertGreaterEqual(len(base64.b64decode(envelope["ciphertext"])), 16)
        for sensitive in ("private@example.org", "Private frozen body", '"status"', KEY):
            self.assertNotIn(sensitive, encoded.decode())
        self.assertEqual(self.store().load(NAME), state)
        store.save(NAME, state)
        second = json.loads(base64.b64decode(self.api.files[NAME]["content"]))
        self.assertNotEqual(envelope["nonce"], second["nonce"])
        self.assertNotEqual(envelope["ciphertext"], second["ciphertext"])

    def test_missing_invalid_and_wrong_length_keys_stop_before_any_api_access(self):
        invalid = (None, "", "not base64", base64.urlsafe_b64encode(b"short").decode(),
                   base64.urlsafe_b64encode(b"x" * 33).decode(), KEY + "\n", KEY[:-2] + "==")
        with patch("levyquant.state_store.urlopen") as request:
            for key in invalid:
                with self.subTest(key_length=len(key) if isinstance(key, str) else None):
                    with self.assertRaises(StateError) as error:
                        self.store(key=key)
                    if key:
                        self.assertNotIn(key, str(error.exception))
            request.assert_not_called()

    def test_unpadded_urlsafe_32_byte_key_is_accepted(self):
        self.assertIsInstance(self.store(key=KEY.rstrip("=")), GitHubStateStore)

    def test_wrong_key_is_rejected_by_marker_even_before_new_edition_exists(self):
        self.store().ensure_state_branch()
        self.api.calls.clear()
        with self.assertRaisesRegex(StateError, "authentication") as error:
            self.store(key=OTHER_KEY).ensure_state_branch()
        self.assertNotIn(OTHER_KEY, str(error.exception))
        self.assertTrue(all(method == "GET" for _, method, _ in self.api.calls))

    def test_repository_branch_and_path_are_authenticated(self):
        self.write_state()
        for options, path in (
            ({"repository": "another/repo"}, NAME),
            ({"branch": "another-state"}, NAME),
            ({}, "editions/2026-11-27.json"),
        ):
            with self.subTest(options=options, path=path):
                target = self.store(**options)
                target._request = Mock(return_value=deepcopy(self.api.files[NAME]))
                with self.assertRaisesRegex(StateError, "authentication"):
                    target.load(path)
                self.assertNotIn(path, target.versions)

    def test_tampered_ciphertext_and_nonce_are_rejected_without_sensitive_errors(self):
        self.write_state()
        original = json.loads(base64.b64decode(self.api.files[NAME]["content"]))
        for field in ("nonce", "ciphertext"):
            with self.subTest(field=field):
                envelope = deepcopy(original)
                raw = bytearray(base64.b64decode(envelope[field]))
                raw[-1] ^= 1
                envelope[field] = base64.b64encode(raw).decode()
                self.api.files[NAME] = content_record(json.dumps(envelope).encode())
                with self.assertRaisesRegex(StateError, "authentication") as error:
                    self.store().load(NAME)
                for sensitive in (KEY, "private@example.org", "Private frozen body", envelope[field]):
                    self.assertNotIn(sensitive, str(error.exception))

    def test_plaintext_and_invalid_envelopes_are_never_migrated_or_overwritten(self):
        for state in (
            {"recipient": "private@example.org", "status": "reserved"},
            {"format": "unsupported", "nonce": "", "ciphertext": ""},
            {"format": STATE_FORMAT, "nonce": "bad!", "ciphertext": "bad!"},
            {"format": STATE_FORMAT, "nonce": "", "ciphertext": "", "extra": "metadata"},
        ):
            with self.subTest(fields=list(state)):
                self.api.files[NAME] = content_record(json.dumps(state).encode())
                store = self.store()
                with self.assertRaises(StateError):
                    store.load(NAME)
                with self.assertRaisesRegex(StateError, "Load state"):
                    store.save(NAME, {"status": "new"})
        self.assertFalse(any(method == "PUT" for _, method, _ in self.api.calls))

    def test_existing_branch_without_valid_encrypted_marker_is_blocked(self):
        self.api.exists = True
        with self.assertRaisesRegex(StateError, "marker"):
            self.store().ensure_state_branch()
        self.api.files["_state.json"] = content_record(b'{"encrypted_state":true}')
        with self.assertRaisesRegex(StateError, "Plaintext"):
            self.store().ensure_state_branch()
        self.assertTrue(all(method == "GET" for _, method, _ in self.api.calls))

    def test_encrypted_cas_conflict_is_not_retried(self):
        one, two = self.store(), self.store()
        self.assertIsNone(one.load(NAME))
        self.assertIsNone(two.load(NAME))
        one.save(NAME, {"status": "reserved"})
        before = len(self.api.calls)
        with self.assertRaises(StateConflict):
            two.save(NAME, {"status": "accepted"})
        self.assertEqual(len(self.api.calls) - before, 1)
        self.assertEqual(self.store().load(NAME)["status"], "reserved")

    def test_lost_ack_still_leaves_decryptable_reservation_for_next_run(self):
        store = self.store()
        store.load(NAME)
        self.api.lost_ack = True
        with self.assertRaisesRegex(StateError, "acknowledged"):
            store.save(NAME, {"status": "reserved"})
        self.api.lost_ack = False
        self.assertEqual(self.store().load(NAME), {"status": "reserved"})

    def test_missing_crypto_dependency_has_no_plaintext_fallback(self):
        with patch("levyquant.state_store.AESGCM", None), patch("levyquant.state_store.urlopen") as request:
            with self.assertRaisesRegex(StateError, "cryptography"):
                self.store()
            request.assert_not_called()
