"""Offline administrator OTP/session boundaries with a durable-memory CAS stub."""
import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import re
import unittest
from unittest.mock import Mock, patch

from levyquant.admin_auth import (
    AdminAuthError, AdminAuthService, MAX_RECORDS, OTP_TTL, POLICY_PATH, REPOSITORY,
    SESSION_TTL, STATE_PATH, service_from_env,
)
from levyquant.state_store import StateConflict, StateError


KEY = base64.urlsafe_b64encode(b"a" * 32).decode()
EMAIL = "admin@example.org"
OTHER = "owner@example.org"
START = datetime(2026, 11, 26, 12, tzinfo=timezone.utc)


class MemoryStore:
    def __init__(self):
        self.values, self.saves = {}, []
        self.conflicts = 0
        self.ignore_state_save = False

    def load(self, path):
        return deepcopy(self.values.get(path))

    def save(self, path, value):
        self.saves.append((path, deepcopy(value)))
        if self.conflicts:
            self.conflicts -= 1
            raise StateConflict("Offline CAS conflict")
        if path != STATE_PATH or not self.ignore_state_save:
            self.values[path] = deepcopy(value)


class AdminAuthTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.clock = [START]
        self.service = AdminAuthService(self.store, KEY, now=lambda: self.clock[0])
        self.service.configure_emails([EMAIL, OTHER])

    def advance(self, **kwargs):
        self.clock[0] += timedelta(**kwargs)

    def request(self, email=EMAIL, client="offline-client"):
        return self.service.request_login(email, client)

    def code_for(self, identifier):
        return next(row["code"] for row in self.store.values[STATE_PATH]["challenges"] if row["id"] == identifier)

    def login(self, email=EMAIL):
        request = self.request(email)
        self.assertTrue(request["queued"])
        return self.service.verify_login(request["challenge_id"], self.code_for(request["challenge_id"]))

    def test_unknown_address_is_decoy_and_never_enters_the_queue(self):
        before = len(self.store.saves)
        result = self.request("unknown@example.org")
        self.assertEqual(set(result), {"challenge_id", "queued"})
        self.assertRegex(result["challenge_id"], r"^[A-Za-z0-9_-]{24}$")
        self.assertFalse(result["queued"])
        self.assertEqual(len(self.store.saves), before)
        self.assertEqual(self.service.pending_login_messages(), [])
        self.assertEqual(self.service.verify_login(result["challenge_id"], "000000"), {"status": "invalid_or_expired"})

    def test_six_digit_single_use_login_only_hashes_session_and_expires_or_logs_out(self):
        requested = self.request()
        identifier, code = requested["challenge_id"], self.code_for(requested["challenge_id"])
        self.assertRegex(code, r"^[0-9]{6}$")
        result = self.service.verify_login(identifier, code)
        self.assertEqual(result["status"], "authenticated")
        self.assertRegex(result["token"], r"^lq_session_[A-Za-z0-9_-]{43}$")
        self.assertEqual(datetime.fromisoformat(result["expires_at"]), START + SESSION_TTL)
        self.assertTrue(self.service.authenticate_session(result["token"]))
        self.assertNotIn(result["token"], json.dumps(self.store.values))
        self.assertEqual(self.service.verify_login(identifier, code), {"status": "invalid_or_expired"})
        self.assertEqual(self.store.values[STATE_PATH]["challenges"][0]["code"], "")
        self.assertEqual(self.service.logout_session(result["token"]), {"status": "logged_out"})
        self.assertFalse(self.service.authenticate_session(result["token"]))
        second = self.login(OTHER)
        self.advance(hours=1)
        self.assertFalse(self.service.authenticate_session(second["token"]))

    def test_wrong_codes_lock_after_five_and_expiry_cannot_authenticate(self):
        requested = self.request()
        code = self.code_for(requested["challenge_id"])
        wrong = "000000" if code != "000000" else "111111"
        for _ in range(5):
            self.assertEqual(self.service.verify_login(requested["challenge_id"], wrong), {"status": "invalid_or_expired"})
        self.assertEqual(self.store.values[STATE_PATH]["challenges"][0]["attempts"], 5)
        self.assertEqual(self.service.verify_login(requested["challenge_id"], code), {"status": "invalid_or_expired"})
        fresh = self.request(OTHER)
        fresh_code = self.code_for(fresh["challenge_id"])
        self.advance(minutes=10)
        self.assertEqual(self.service.verify_login(fresh["challenge_id"], fresh_code), {"status": "invalid_or_expired"})
        self.assertEqual(self.service.pending_login_messages(), [])

    def test_persistent_cooldown_hourly_and_daily_quotas_survive_new_service(self):
        first = self.request()
        self.assertTrue(first["queued"])
        self.assertFalse(self.request()["queued"])
        for _ in range(4):
            self.advance(seconds=61)
            self.assertTrue(self.request()["queued"])
        self.advance(seconds=61)
        restarted = AdminAuthService(self.store, KEY, now=lambda: self.clock[0])
        self.assertFalse(restarted.request_login(EMAIL, "different-client")["queued"])
        self.advance(hours=1)
        for _ in range(5):
            self.assertTrue(restarted.request_login(EMAIL, "different-client")["queued"])
            self.advance(seconds=61)
        self.advance(hours=1)
        self.assertFalse(restarted.request_login(EMAIL, "another-client")["queued"])
        self.advance(days=1)
        self.assertTrue(restarted.request_login(EMAIL, "another-client")["queued"])

    def test_policy_changes_revoke_sessions_and_old_challenges_cannot_revive(self):
        session = self.login()
        pending = self.request(OTHER)
        code = self.code_for(pending["challenge_id"])
        self.service.configure_emails(["replacement@example.org"])
        self.assertFalse(self.service.authenticate_session(session["token"]))
        self.assertEqual(self.service.verify_login(pending["challenge_id"], code), {"status": "invalid_or_expired"})
        self.service.configure_emails([EMAIL, OTHER])
        self.assertFalse(self.service.authenticate_session(session["token"]))
        self.assertEqual(self.service.verify_login(pending["challenge_id"], code), {"status": "invalid_or_expired"})

    def test_claim_is_reserved_and_reread_before_code_then_terminal_mail_never_replays(self):
        identifier = self.request()["challenge_id"]
        self.assertEqual(self.service.pending_login_messages(), [{"id": identifier}])
        claimed = self.service.claim_login_message(identifier)
        self.assertEqual(set(claimed), {"id", "email", "code", "expires_at", "reservation_id"})
        persisted = self.store.values[STATE_PATH]["challenges"][0]["message"]
        self.assertEqual(persisted["status"], "reserved")
        self.assertEqual(persisted["reservation_id"], claimed["reservation_id"])
        self.assertEqual(self.service.pending_login_messages(), [])
        self.assertIsNone(self.service.claim_login_message(identifier))
        self.service.mark_login_message(identifier, "uncertain", reservation_id=claimed["reservation_id"], stage="data")
        self.assertIsNone(self.service.claim_login_message(identifier))
        with self.assertRaises(AdminAuthError):
            self.service.mark_login_message(identifier, "accepted", reservation_id=claimed["reservation_id"])
        self.advance(minutes=10)
        self.assertIsNone(self.service.claim_login_message(identifier))

    def test_lost_reservation_or_otp_consumption_ack_does_not_expose_delivery_or_session(self):
        identifier = self.request()["challenge_id"]
        code = self.code_for(identifier)
        self.store.ignore_state_save = True
        with self.assertRaisesRegex(AdminAuthError, "state_not_acknowledged"):
            self.service.claim_login_message(identifier)
        with self.assertRaisesRegex(AdminAuthError, "state_not_acknowledged"):
            self.service.verify_login(identifier, code)
        self.assertEqual(self.store.values[STATE_PATH]["sessions"], [])

    def test_logout_requires_durable_revocation_and_invalid_delivery_values_have_fixed_errors(self):
        session = self.login()
        self.store.ignore_state_save = True
        with self.assertRaisesRegex(AdminAuthError, "state_not_acknowledged"):
            self.service.logout_session(session["token"])
        self.store.ignore_state_save = False
        self.service.logout_session(session["token"])
        self.assertFalse(self.service.authenticate_session(session["token"]))
        identifier = self.request(OTHER)["challenge_id"]
        claimed = self.service.claim_login_message(identifier)
        for values in ({"status": []}, {"status": "accepted", "stage": []},
                       {"status": "accepted", "smtp_code": True}):
            with self.subTest(values=values), self.assertRaisesRegex(AdminAuthError, "invalid_outcome"):
                self.service.mark_login_message(identifier, reservation_id=claimed["reservation_id"], **values)

    def test_cas_retries_are_bounded_and_recompute_limits(self):
        self.store.conflicts = 2
        result = self.request()
        self.assertTrue(result["queued"])
        self.assertEqual(len(self.store.values[STATE_PATH]["challenges"]), 1)
        self.assertEqual(len(self.store.values[STATE_PATH]["requests"]), 1)
        self.store.conflicts = 3
        before = len(self.store.saves)
        with self.assertRaisesRegex(AdminAuthError, "state_conflict"):
            self.request(OTHER)
        self.assertEqual(len(self.store.saves) - before, 3)

    def test_expired_records_are_reclaimed_and_all_state_records_remain_bounded(self):
        first = self.request()["challenge_id"]
        self.service.claim_login_message(first)
        self.advance(minutes=11)
        second = self.request(OTHER)
        self.assertTrue(second["queued"])
        self.assertNotIn(first, [row["id"] for row in self.store.values[STATE_PATH]["challenges"]])
        state = self.store.values[STATE_PATH]
        template = deepcopy(state["requests"][0])
        state["requests"] += [deepcopy(template) for _ in range(MAX_RECORDS - sum(len(state[key]) for key in ("challenges", "sessions", "requests")))]
        self.advance(seconds=61)
        self.assertFalse(self.request()["queued"])
        self.assertEqual(sum(len(self.store.values[STATE_PATH][key]) for key in ("challenges", "sessions", "requests")), MAX_RECORDS)
        self.advance(days=1)
        self.assertTrue(self.request()["queued"])
        self.assertLessEqual(sum(len(self.store.values[STATE_PATH][key]) for key in ("challenges", "sessions", "requests")), MAX_RECORDS)

    def test_missing_policy_is_disabled_bad_policy_or_state_fails_closed_and_inputs_are_safe(self):
        empty = AdminAuthService(MemoryStore(), KEY, now=START)
        self.assertEqual(empty.configured_emails(), {"emails": []})
        self.assertFalse(empty.request_login(EMAIL, "client")["queued"])
        for field in (POLICY_PATH, STATE_PATH):
            broken = MemoryStore()
            broken.values[field] = {"private": "sensitive@example.org sensitive-token"}
            auth = AdminAuthService(broken, KEY, now=START)
            for operation in (lambda: auth.request_login(EMAIL, "client"), auth.configured_emails):
                with self.assertRaises(AdminAuthError) as caught:
                    operation()
                self.assertNotIn("sensitive", str(caught.exception))
        for email in ("bad", "bad\r\n@example.org", "bad@-example.org"):
            with self.assertRaises(AdminAuthError) as caught:
                self.request(email)
            self.assertNotIn(email, str(caught.exception))
        with self.assertRaises(AdminAuthError):
            self.service.request_login(EMAIL, "client\nvalue")
        self.assertFalse(self.service.authenticate_session("Bearer injected"))
        with self.assertRaises(AdminAuthError):
            self.service.pending_login_messages(True)

    def test_client_ids_are_only_purpose_separated_hashes_and_accepted_mail_is_single_use(self):
        identifier = self.request(client="raw-client-address")["challenge_id"]
        serialized = json.dumps(self.store.values)
        self.assertNotIn("raw-client-address", serialized)
        record = self.store.values[STATE_PATH]["challenges"][0]
        self.assertRegex(record["client_key"], r"^[0-9a-f]{64}$")
        self.assertNotEqual(record["client_key"], self.service._digest("session", "raw-client-address"))
        claimed = self.service.claim_login_message(identifier)
        self.service.mark_login_message(identifier, "accepted", reservation_id=claimed["reservation_id"], smtp_code=250)
        self.assertEqual(self.service.pending_login_messages(), [])
        self.assertIsNone(self.service.claim_login_message(identifier))
        self.assertEqual(self.service.verify_login(identifier, claimed["code"])["status"], "authenticated")

    def test_actual_smtp_failure_stages_are_recorded_as_terminal_without_replay(self):
        for stage in ("validation", "greeting", "mail"):
            with self.subTest(stage=stage):
                store = MemoryStore()
                service = AdminAuthService(store, KEY, now=START)
                service.configure_emails([EMAIL])
                identifier = service.request_login(EMAIL, "offline-client")["challenge_id"]
                claimed = service.claim_login_message(identifier)
                result = service.mark_login_message(identifier, "rejected",
                    reservation_id=claimed["reservation_id"], stage=stage, smtp_code=550)
                self.assertEqual(result, {"status": "rejected"})
                message = store.values[STATE_PATH]["challenges"][0]["message"]
                self.assertEqual((message["status"], message["stage"], message["smtp_code"]), ("rejected", stage, 550))
                self.assertEqual(service.pending_login_messages(), [])
                self.assertIsNone(service.claim_login_message(identifier))

    def test_environment_factory_is_fixed_repo_requires_no_subscription_or_admin_token(self):
        environment = {"GITHUB_REPOSITORY": REPOSITORY, "GITHUB_TOKEN": "offline-repo-token", "STATE_ENCRYPTION_KEY": KEY}
        store = Mock()
        with patch("levyquant.admin_auth.GitHubStateStore", return_value=store) as factory:
            self.assertIsInstance(service_from_env(environment), AdminAuthService)
        factory.assert_called_once_with(REPOSITORY, "offline-repo-token", encryption_key=KEY)
        store.ensure_state_branch.assert_called_once_with()
        store.ensure_state_branch.side_effect = StateError("sensitive@example.org private-provider-message")
        with patch("levyquant.admin_auth.GitHubStateStore", return_value=store):
            with self.assertRaisesRegex(AdminAuthError, "^state_unavailable$"):
                service_from_env(environment)
        for updates in ({"GITHUB_REPOSITORY": "another/repo"}, {"STATE_ENCRYPTION_KEY": "invalid"}, {"GITHUB_TOKEN": ""}):
            with patch("levyquant.admin_auth.GitHubStateStore") as factory:
                with self.assertRaises(AdminAuthError):
                    service_from_env({**environment, **updates})
                factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
