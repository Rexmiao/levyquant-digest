"""Offline web-boundary tests: no provider, GitHub or mail connection."""
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from datetime import datetime, timezone
import http.client
from io import StringIO
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from levyquant import daily, space_app
from levyquant.delivery_reports import record_run_report
from levyquant.editor import EditorError, EditorValidationError
from levyquant.source_settings import SETTINGS_PATH
from levyquant.state_store import LocalStateStore, StateConflict, StateError
from levyquant.subscriptions import SubscriptionError


TOKEN = "test_admin_token_" + "x" * 32
AUTH = "Bearer " + TOKEN
ENV = {"GITHUB_TOKEN": "offline-github-key", "STATE_ENCRYPTION_KEY": "A" * 43,
       "SPACE_ADMIN_TOKEN": TOKEN, "GEMINI_API_KEY": "offline-gemini-key",
       "GEMINI_FREE_TIER_CONFIRMED": "true", "SUBSCRIPTIONS_ENABLED": "true",
       "DIGEST_PUBLIC_BASE_URL": "https://example.hf.space"}
PREVIEW = {"date": "2026-11-26", "subject": "Verified daily edition",
           "html": "<p>Public news.</p>", "text": "Public news."}


class MemoryStore:
    def __init__(self, values=None):
        self.values = deepcopy(values or {})
        self.ensure_state_branch = Mock()
        self.load = Mock(side_effect=lambda path: deepcopy(self.values.get(path)))
        self.save = Mock(side_effect=self._save)

    def _save(self, path, value):
        self.values[path] = deepcopy(value)


class AppTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.store_factory = Mock(return_value=self.store)
        self.service = Mock()
        self.service.request_signup.return_value = {"status": "check_email", "queued": True}
        self.service.confirm.return_value = {"status": "confirmed"}
        self.service.unsubscribe.return_value = {"status": "unsubscribed"}
        self.service.list_subscribers.return_value = [{"id": "abc", "email": "private@example.org"}]
        self.service.admin_suppress.return_value = {"status": "suppressed"}
        self.service_factory = Mock(return_value=self.service)
        self.github = Mock(return_value={"workflow_runs": []})
        self.app = self.make_app()

    def make_app(self, environment=None, **kwargs):
        return space_app.SpaceApplication(ENV if environment is None else environment,
            store_factory=self.store_factory, subscription_factory=self.service_factory,
            github_request=self.github, **kwargs)

    def request(self, method, path, body=None, authorization=AUTH):
        return self.app.handle_api(method, path, body, authorization=authorization, client_id="hashed-ip")

    def assert_error(self, status, callback):
        with self.assertRaises(space_app.AppError) as caught:
            callback()
        self.assertEqual(caught.exception.status, status)

    def test_unconfigured_public_landing_has_no_model_or_network_side_effect(self):
        with patch.object(daily, "run") as run:
            app = self.make_app({})
            status, result = app.handle_api("GET", "/api/public/preview")
        self.assertEqual(status, 200)
        self.assertFalse(result["available"])
        self.assertFalse(result["signup_enabled"])
        self.store_factory.assert_not_called()
        self.service_factory.assert_not_called()
        self.github.assert_not_called()
        run.assert_not_called()

    def test_public_preview_whitelists_fields_and_caches_without_decrypting_twice(self):
        self.store.values[space_app.PUBLIC_PATH] = {**PREVIEW, "recipients": ["private@example.org"],
            "deliveries": {"sensitive": "private"}, "provider_key": "do-not-expose"}
        first = self.app.public_preview()
        second = self.app.public_preview()
        self.assertEqual(first, {"available": True, **PREVIEW, "signup_enabled": True})
        self.assertEqual(first, second)
        self.assertNotIn("private", json.dumps(first))
        self.store_factory.assert_called_once_with()
        self.store.ensure_state_branch.assert_called_once_with()

    def test_wrong_encryption_key_is_generic_and_never_dispatches_send(self):
        self.store.ensure_state_branch.side_effect = StateError("a secret from provider@example.org")
        self.assertFalse(self.app.public_preview()["available"])
        with self.assertRaises(StateError):
            self.request("POST", "/api/admin/send", {})
        self.github.assert_not_called()

    def test_all_private_endpoints_require_auth_before_any_service(self):
        for method, path in (("GET", "/api/admin/subscribers"), ("GET", "/api/admin/status"),
                ("GET", "/api/admin/preview"), ("POST", "/api/admin/send"),
                ("POST", "/api/admin/preview"), ("POST", "/api/admin/publish"),
                ("POST", "/api/admin/subscribers"),
                ("GET", "/api/admin/moomoo-settings"), ("POST", "/api/admin/moomoo-settings"),
                ("GET", "/api/admin/login-emails"), ("POST", "/api/admin/login-emails"),
                ("POST", "/api/admin/logout"), ("GET", "/api/admin/delivery-report"),
                ("POST", "/api/admin/confirmation-status")):
            with self.subTest(path=path):
                self.assert_error(401, lambda: self.request(method, path, {}, authorization="Bearer wrong"))
        self.store_factory.assert_not_called()
        self.service_factory.assert_not_called()
        self.github.assert_not_called()

    def test_email_login_request_hides_allowlist_and_only_dispatches_queued_mail(self):
        auth = Mock()
        self.app = self.make_app(admin_auth_factory=lambda: auth)
        for queued in (False, True):
            auth.request_login.return_value = {"challenge_id": "c" * 24, "queued": queued,
                                              "private_email": "never-return@example.org"}
            status, result = self.request("POST", "/api/admin-login/request", {"email": "Owner@example.org"}, None)
            self.assertEqual((status, result), (200, {"status": "check_email", "challenge_id": "c" * 24}))
            self.assertNotIn("queued", result)
        auth.request_login.assert_called_with("owner@example.org", client_id="hashed-ip")
        self.github.assert_called_once_with("POST",
            "/repos/Rexmiao/levyquant-digest/actions/workflows/subscription-mail.yml/dispatches", {"ref": "main"})

    def test_email_login_verification_accepts_only_bounded_code_and_session_response(self):
        auth = Mock()
        self.app = self.make_app(admin_auth_factory=lambda: auth)
        auth.verify_login.return_value = {"status": "invalid_or_expired"}
        self.assert_error(401, lambda: self.request("POST", "/api/admin-login/verify",
                          {"challenge_id": "c" * 24, "code": "123456"}, None))
        auth.verify_login.return_value = {"status": "authenticated", "token": "lq_session_" + "s" * 43,
            "expires_at": "2026-11-26T21:00:00+00:00", "private_record": "must-not-return"}
        self.assertEqual(self.request("POST", "/api/admin-login/verify",
                         {"challenge_id": "c" * 24, "code": "001234"}, None), (200,
            {"status": "authenticated", "token": "lq_session_" + "s" * 43,
             "expires_at": "2026-11-26T21:00:00+00:00"}))
        auth.verify_login.assert_called_with("c" * 24, "001234")
        self.github.assert_not_called()

    def test_invalid_email_login_input_never_constructs_remote_service(self):
        auth_factory = Mock()
        cases = [("/api/admin-login/request", {"email": "bad"}),
                 ("/api/admin-login/request", {"email": "owner@example.org", "role": "admin"}),
                 ("/api/admin-login/verify", {"challenge_id": "c" * 25, "code": "123456"}),
                 ("/api/admin-login/verify", {"challenge_id": "c" * 24, "code": 123456}),
                 ("/api/admin-login/verify", {"challenge_id": "c" * 24, "code": "12345x"}),
                 ("/api/admin-login/verify", {"challenge_id": "c" * 24, "code": "123456", "email": "other@example.org"})]
        for path, body in cases:
            self.app = self.make_app(admin_auth_factory=auth_factory)
            self.assert_error(400, lambda: self.request("POST", path, body, None))
        auth_factory.assert_not_called()
        self.store_factory.assert_not_called()

    def test_email_session_accesses_same_console_but_cannot_change_admin_allowlist(self):
        auth = Mock()
        auth.authenticate_session.return_value = True
        self.app = self.make_app(admin_auth_factory=lambda: auth)
        session_header = "Bearer lq_session_" + "s" * 43
        self.assertEqual(self.request("GET", "/api/admin/subscribers", authorization=session_header)[0], 200)
        self.assertEqual(self.request("GET", "/api/admin/moomoo-settings", authorization=session_header)[0], 200)
        self.assert_error(401, lambda: self.request("POST", "/api/admin/login-emails",
                                {"emails": ["extra@example.org"]}, session_header))
        auth.configure_emails.assert_not_called()
        auth.authenticate_session.return_value = False
        self.assert_error(401, lambda: self.request("GET", "/api/admin/status", authorization=session_header))

    def test_recovery_credential_configures_only_explicit_login_email_list(self):
        auth = Mock()
        auth.configure_emails.return_value = {"emails": ["first@example.org", "second@example.org"]}
        auth.configured_emails.return_value = auth.configure_emails.return_value
        self.app = self.make_app(admin_auth_factory=lambda: auth)
        self.assertEqual(self.request("POST", "/api/admin/login-emails",
            {"emails": ["First@example.org", "second@example.org"]}),
            (200, {"emails": ["first@example.org", "second@example.org"]}))
        auth.configure_emails.assert_called_once_with(["first@example.org", "second@example.org"])
        self.assertEqual(self.request("GET", "/api/admin/login-emails"), (200, auth.configured_emails.return_value))
        self.github.assert_not_called()
        self.service_factory.assert_not_called()

    def test_session_logout_revokes_the_opaque_token_without_affecting_recovery_key(self):
        auth = Mock()
        auth.authenticate_session.return_value = True
        self.app = self.make_app(admin_auth_factory=lambda: auth)
        token = "lq_session_" + "s" * 43
        self.assertEqual(self.request("POST", "/api/admin/logout", {}, "Bearer " + token),
                         (200, {"status": "signed_out"}))
        auth.logout_session.assert_called_once_with(token)
        auth.logout_session.reset_mock()
        self.assertEqual(self.request("POST", "/api/admin/logout", {}), (200, {"status": "signed_out"}))
        auth.logout_session.assert_not_called()

    def test_missing_or_short_admin_secret_fails_closed(self):
        for token in ("", "short", " ", "x" * 300):
            app = self.make_app({**ENV, "SPACE_ADMIN_TOKEN": token})
            self.assert_error(503, lambda: app.handle_api("GET", "/api/admin/status", authorization=AUTH))

    def test_signup_returns_no_queue_or_address_and_dispatches_fixed_workflow(self):
        status, result = self.request("POST", "/api/subscribe", {"email": "person@example.org", "website": ""}, None)
        self.assertEqual((status, result), (200, {"status": "check_email"}))
        self.service.request_signup.assert_called_once_with("person@example.org", client_id="hashed-ip")
        self.github.assert_called_once_with("POST",
            "/repos/Rexmiao/levyquant-digest/actions/workflows/subscription-mail.yml/dispatches", {"ref": "main"})
        self.assertNotIn("person", json.dumps(self.github.call_args.args))

    def test_existing_signup_and_honeypot_do_not_dispatch(self):
        self.service.request_signup.return_value = {"status": "check_email", "queued": False}
        self.request("POST", "/api/subscribe", {"email": "person@example.org"}, None)
        self.request("POST", "/api/subscribe", {"email": "bot@example.org", "website": "bot"}, None)
        self.github.assert_not_called()
        self.assertEqual(self.service.request_signup.call_count, 1)

    def test_disabled_signup_does_not_store_or_dispatch(self):
        self.app = self.make_app({**ENV, "SUBSCRIPTIONS_ENABLED": "false"})
        self.assert_error(503, lambda: self.request("POST", "/api/subscribe", {"email": "person@example.org"}, None))
        self.service_factory.assert_not_called()
        self.github.assert_not_called()

    def test_signup_availability_matches_canonical_space_base_url_contract(self):
        for value in ("https://attacker.example", "https://example.hf.space:443",
                      "https://example.hf.space/path", "https://example.hf.space?token=private",
                      "https://name:secret@example.hf.space", "http://example.hf.space"):
            with self.subTest(value=value):
                app = self.make_app({**ENV, "DIGEST_PUBLIC_BASE_URL": value})
                self.assertFalse(app.signup_enabled())

    def test_invalid_email_fails_before_remote_service_or_dispatch(self):
        for email in ("invalid", ".private@example.org", "private@-example.org"):
            self.assert_error(400, lambda: self.request("POST", "/api/subscribe", {"email": email}, None))
        self.service_factory.assert_not_called()
        self.github.assert_not_called()

    def test_confirm_and_unsubscribe_only_pass_id_and_token_to_service(self):
        for path, expected in (("/api/confirm", "confirmed"), ("/api/unsubscribe", "unsubscribed")):
            status, result = self.request("POST", path, {"id": "opaque_id", "token": "opaque-token.part"}, None)
            self.assertEqual((status, result), (200, {"status": expected}))
        self.service.confirm.assert_called_once_with("opaque_id", "opaque-token.part")
        self.service.unsubscribe.assert_called_once_with("opaque_id", "opaque-token.part")
        self.github.assert_not_called()

    def test_public_mutations_share_client_limit_before_remote_initialization(self):
        self.service.request_signup.return_value = {"status": "check_email", "queued": False}
        paths = ("/api/subscribe", "/api/confirm", "/api/unsubscribe")
        for index in range(6):
            path = paths[index % len(paths)]
            body = {"email": "person@example.org"} if path == "/api/subscribe" else {"id": "opaque_id", "token": "opaque-token"}
            self.request("POST", path, body, None)
        before = self.service_factory.call_count
        for path in paths:
            body = {"email": "person@example.org"} if path == "/api/subscribe" else {"id": "opaque_id", "token": "opaque-token"}
            self.assert_error(429, lambda: self.request("POST", path, body, None))
        self.assertEqual(self.service_factory.call_count, before)
        self.store_factory.assert_not_called()
        self.github.assert_not_called()

    def test_global_public_limit_cannot_be_bypassed_by_changing_client_and_excludes_admin(self):
        self.service.request_signup.return_value = {"status": "check_email", "queued": False}
        for index in range(20):
            self.app.handle_api("POST", "/api/subscribe", {"email": "person@example.org"}, client_id=f"hashed-{index}")
        before = self.service_factory.call_count
        self.assert_error(429, lambda: self.app.handle_api("POST", "/api/confirm",
            {"id": "opaque_id", "token": "opaque-token"}, client_id="new-hashed-client"))
        self.assertEqual(self.service_factory.call_count, before)
        self.store_factory.assert_not_called()
        self.assertEqual(self.request("GET", "/api/admin/subscribers")[0], 200)
        self.assertEqual(self.service_factory.call_count, before + 1)
        self.github.assert_not_called()

    def test_caller_cannot_supply_repository_workflow_url_html_or_recipient(self):
        for body in ({"repository": "other/repo"}, {"workflow": "other.yml"},
                     {"url": "https://attacker.example"}, {"html": "untrusted"},
                     {"email": "person@example.org"}):
            self.assert_error(400, lambda: self.request("POST", "/api/admin/send", body))
            self.assert_error(400, lambda: self.request("POST", "/api/admin/publish", body))
        self.store_factory.assert_not_called()
        self.github.assert_not_called()

    def test_admin_send_only_queues_fixed_main_workflow_after_key_check(self):
        status, result = self.request("POST", "/api/admin/send", {})
        self.store.ensure_state_branch.assert_called_once_with()
        self.assertEqual((status, result), (202, {"status": "queued"}))
        self.github.assert_called_once_with("POST",
            "/repos/Rexmiao/levyquant-digest/actions/workflows/daily-digest.yml/dispatches",
            {"ref": "main", "inputs": {"run_mode": "send"}})

    def test_foreign_repository_is_rejected_before_state_or_dispatch(self):
        self.app = self.make_app({**ENV, "GITHUB_REPOSITORY": "someone/else"})
        self.assert_error(503, lambda: self.request("POST", "/api/admin/send", {}))
        self.assertFalse(self.app.signup_enabled())
        self.store_factory.assert_not_called()
        self.github.assert_not_called()

    def test_admin_status_contains_variable_names_and_validated_run_links_only(self):
        self.github.return_value = {"workflow_runs": [
            {"id": 42, "status": "completed", "conclusion": "success",
             "html_url": "https://github.com/Rexmiao/levyquant-digest/actions/runs/42",
             "secret": "do-not-expose"},
            {"id": 43, "status": "completed", "html_url": "https://attacker.example/43"}]}
        _, result = self.request("GET", "/api/admin/status")
        self.assertTrue(result["configured"])
        self.assertEqual(len(result["runs"]), 1)
        self.assertEqual(set(result["runs"][0]), {"id", "status", "conclusion", "html_url"})
        for value in ENV.values():
            if value not in ("true", "https://example.hf.space"):
                self.assertNotIn(value, json.dumps(result))

    def test_delivery_report_distinguishes_real_receipts_preview_and_unknown_legacy_runs(self):
        frozen = {**PREVIEW, "edition_id": "levyquant-morning-" + PREVIEW["date"], "mode": "live", "validated": True,
                  "events": [], "deliveries": {"hash-a": {"status": "accepted"},
                      "hash-b": {"status": "accepted"}, "hash-c": {"status": "uncertain"}}}
        frozen["content_sha256"] = daily.edition_fingerprint(frozen)
        self.store.values["editions/" + PREVIEW["date"] + ".json"] = frozen
        record_run_report(self.store, {"run_id": "42", "mode": "preview", "date": PREVIEW["date"],
            "status": "completed", "started_at": "2026-11-26T12:00:00+00:00",
            "updated_at": "2026-11-26T12:01:00+00:00", "result_code": "preview_ready_no_mail_sent"})
        self.github.return_value = {"workflow_runs": [
            {"id": 42, "status": "completed", "conclusion": "success", "display_title": "LevyQuant Daily Digest [send]",
             "html_url": "https://github.com/Rexmiao/levyquant-digest/actions/runs/42"},
            {"id": 43, "status": "completed", "conclusion": "success", "display_title": "LevyQuant Daily Digest",
             "html_url": "https://github.com/Rexmiao/levyquant-digest/actions/runs/43"},
            {"id": 44, "status": "completed", "conclusion": "failure", "display_title": "LevyQuant Daily Digest [send]",
             "html_url": "https://github.com/Rexmiao/levyquant-digest/actions/runs/44"},
            {"id": 45, "status": "completed", "conclusion": "success", "html_url": "https://untrusted.example"}]}
        self.store.values["runs/43.json"] = {"date": PREVIEW["date"], "created_at": "2026-11-26T12:00:00+00:00"}
        class ReportClock(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 11, 26, 12, tzinfo=timezone.utc)
        with patch.object(space_app, "datetime", ReportClock):
            status, report = self.request("GET", "/api/admin/delivery-report")
        self.assertEqual(status, 200)
        self.assertEqual(report["window_days"], 7)
        self.assertEqual(len(report["editions"]), 1)
        summary = report["editions"][0]
        self.assertEqual((summary["accepted"], summary["uncertain"], summary["mode"]), (2, 1, "send"))
        self.assertIsNone(summary["recipient_count"])
        self.assertTrue(summary["legacy_counts"])
        runs = {row["id"]: row for row in report["runs"]}
        self.assertEqual(set(runs), {42, 43, 44})
        self.assertEqual(runs[42]["mode"], "preview")
        self.assertIsNone(runs[42]["counts"])
        self.assertEqual(runs[43]["mode"], "send")
        self.assertEqual(runs[43]["date"], PREVIEW["date"])
        self.assertIsNone(runs[43]["result_status"])
        self.assertIsNone(runs[43]["counts"])
        self.assertEqual(runs[44]["mode"], "send")
        self.assertIsNone(runs[44]["counts"])
        self.assertNotIn("hash-a", json.dumps(report))
        self.assertNotIn(PREVIEW["html"], json.dumps(report))

    def test_delivery_report_preserves_known_receipts_when_workflow_api_fails(self):
        self.github.side_effect = space_app.AppError(503, "github_unavailable")
        status, report = self.request("GET", "/api/admin/delivery-report")
        self.assertEqual(status, 200)
        self.assertTrue(report["runs_unavailable"])
        self.assertEqual(report["editions"], [])
        self.assertEqual(report["runs"], [])
        self.store.save.assert_not_called()

    def test_confirmation_delivery_diagnostic_is_private_read_only_and_never_resends(self):
        metadata = {"subscriber_status": "pending", "mail_status": "accepted", "requested_at": None,
                    "expires_at": None, "reserved_at": None, "completed_at": None, "smtp_code": 250, "stage": None}
        self.service.confirmation_delivery_status.return_value = metadata
        self.assertEqual(self.request("POST", "/api/admin/confirmation-status", {"email": "Reader@example.org"}),
                         (200, metadata))
        self.service.confirmation_delivery_status.assert_called_once_with("reader@example.org")
        self.service.request_signup.assert_not_called()
        self.github.assert_not_called()
        self.assert_error(400, lambda: self.request("POST", "/api/admin/confirmation-status", {"email": "bad"}))

    def test_moomoo_defaults_and_saved_keywords_are_shared_across_app_instances(self):
        _, defaults = self.request("GET", "/api/admin/moomoo-settings")
        self.assertEqual(defaults, {"queries": ["NVIDIA", "Microsoft", "Federal Reserve"], "revision": 0})
        self.store.save.assert_not_called()
        status, saved = self.request("POST", "/api/admin/moomoo-settings",
                                     {"queries": ["  Apple  ", "Inflation", "apple"], "revision": 0})
        self.assertEqual((status, saved), (200, {"queries": ["Apple", "Inflation"], "revision": 1}))
        second = self.make_app()
        self.assertEqual(second.handle_api("GET", "/api/admin/moomoo-settings", authorization=AUTH),
                         (200, saved))
        self.assertEqual(set(self.store.values[SETTINGS_PATH]),
                         {"schema_version", "queries", "revision", "updated_at"})
        self.github.assert_not_called()
        self.service_factory.assert_not_called()

    def test_moomoo_stale_revision_and_remote_conflict_never_overwrite(self):
        body = {"queries": ["Apple"], "revision": 0}
        self.request("POST", "/api/admin/moomoo-settings", body)
        before = self.store.save.call_count
        self.assert_error(409, lambda: self.request("POST", "/api/admin/moomoo-settings", body))
        self.assertEqual(self.store.save.call_count, before)
        self.assertEqual(self.store.values[SETTINGS_PATH]["queries"], ["Apple"])
        self.store.save.side_effect = StateConflict("provider payload must not appear")
        self.assert_error(409, lambda: self.request("POST", "/api/admin/moomoo-settings",
                                                   {"queries": ["Microsoft"], "revision": 1}))
        self.assertEqual(self.store.save.call_count, before + 1)

    def test_invalid_moomoo_requests_are_rejected_before_state_access(self):
        for body in ({}, {"queries": [], "revision": 0}, {"queries": ["x"] * 5, "revision": 0},
                     {"queries": ["x\nsecret"], "revision": 0}, {"queries": ["x" * 201], "revision": 0},
                     {"queries": ["x"], "revision": True}, {"queries": ["x"], "revision": -1},
                     {"queries": ["x"], "revision": 0, "url": "https://untrusted.example"}):
            with self.subTest(body=body):
                self.assert_error(400, lambda: self.request("POST", "/api/admin/moomoo-settings", body))
        self.store_factory.assert_not_called()
        self.store.save.assert_not_called()

    def test_unreadable_moomoo_settings_block_preview_without_using_default_queries(self):
        self.store.load.side_effect = StateError("sensitive@example.org secret-key")
        runner = Mock()
        self.app = self.make_app(preview_runner=runner)
        self.app._run_preview()
        _, state = self.request("GET", "/api/admin/preview")
        self.assertEqual(state, {"status": "failed", "error": "preview_failed",
                               "error_type": "StateError", "error_stage": "source_settings_read"})
        self.assertNotIn("sensitive", json.dumps(state))
        runner.assert_not_called()

    def test_preview_thread_is_single_concurrent_and_receives_no_smtp_credentials(self):
        entered, release = threading.Event(), threading.Event()
        observed = []
        snapshots = []
        self.request("POST", "/api/admin/moomoo-settings", {"queries": ["Apple", "Inflation"], "revision": 0})
        def runner(config, mode, environment, output, *, moomoo_settings):
            observed.append((mode, dict(environment)))
            snapshots.append(deepcopy(moomoo_settings))
            entered.set()
            release.wait(3)
            edition = {**PREVIEW, "edition_id": "levyquant-morning-" + PREVIEW["date"],
                       "mode": "preview", "validated": True, "events": [], "deliveries": {}}
            edition["content_sha256"] = daily.edition_fingerprint(edition)
            store = LocalStateStore(output / "preview-state")
            path = "editions/" + PREVIEW["date"] + ".json"
            store.load(path)
            store.save(path, edition)
            return {"mode": "preview", "status": "preview_ready_no_mail_sent", "date": PREVIEW["date"]}
        self.app = self.make_app({**ENV, "SMTP_APP_PASSWORD": "must-not-pass", "SMTP_USERNAME": "private@example.org",
                                  "DIGEST_RECIPIENTS": "private@example.org"}, preview_runner=runner)
        self.assertEqual(self.request("POST", "/api/admin/preview", {})[0], 202)
        self.assertTrue(entered.wait(1))
        self.assert_error(409, lambda: self.request("POST", "/api/admin/preview", {}))
        release.set()
        self.wait_preview()
        self.assertEqual(observed, [("preview", {"GEMINI_API_KEY": ENV["GEMINI_API_KEY"],
                                                "GEMINI_FREE_TIER_CONFIRMED": "true"})])
        self.assertEqual(snapshots, [{"queries": ["Apple", "Inflation"], "revision": 1}])
        _, result = self.request("GET", "/api/admin/preview")
        self.assertEqual(result, {"status": "ready", "preview": PREVIEW, "moomoo_settings_revision": 1})
        self.assertEqual(self.request("POST", "/api/admin/publish", {}),
                         (200, {"status": "published", "date": PREVIEW["date"]}))
        self.assertEqual(self.store.values[space_app.PUBLIC_PATH], PREVIEW)
        self.github.assert_not_called()

    def wait_preview(self):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if self.request("GET", "/api/admin/preview")[1]["status"] != "running":
                return
            threading.Event().wait(.01)
        self.fail("preview worker did not finish")

    def test_failed_or_unvalidated_generated_preview_cannot_be_published(self):
        runner = Mock(side_effect=RuntimeError("secret@example.org offline-key"))
        self.app = self.make_app(preview_runner=runner)
        self.assert_error(409, lambda: self.request("POST", "/api/admin/publish", {}))
        self.request("POST", "/api/admin/preview", {})
        self.wait_preview()
        self.assertEqual(self.request("GET", "/api/admin/preview")[1],
                         {"status": "failed", "error": "preview_failed",
                          "error_type": "UnexpectedError", "error_stage": "preview_pipeline"})
        self.assert_error(409, lambda: self.request("POST", "/api/admin/publish", {}))
        self.store.save.assert_not_called()

    def test_preview_validation_diagnostics_whitelist_codes_and_hide_report(self):
        sensitive = "private@example.org https://provider.example/?key=offline-private-token"
        error = EditorValidationError({"errors": [
            {"code": "unsupported_numeric_claim", "message": sensitive, "path": sensitive},
            {"code": "unsupported_precise_date", "message": sensitive},
            {"code": "unsupported_numeric_claim"}, {"code": sensitive}],
            "editor_output": {"private": sensitive}})
        self.app = self.make_app(preview_runner=Mock(side_effect=error))
        captured_out, captured_err = StringIO(), StringIO()
        with redirect_stdout(captured_out), redirect_stderr(captured_err):
            self.app._run_preview()
        _, result = self.request("GET", "/api/admin/preview")
        self.assertEqual(result, {"status": "failed", "error": "preview_failed",
            "error_type": "EditorValidationError", "error_stage": "preview_pipeline",
            "error_code": "editor_validation_failed",
            "issue_codes": ["unsupported_numeric_claim", "unsupported_precise_date"]})
        self.assertNotIn(sensitive, json.dumps(result))
        self.assertEqual(captured_out.getvalue() + captured_err.getvalue(), "")
        self.assertFalse(self.app.public_preview()["available"])
        self.store.save.assert_not_called()

    def test_preview_editor_and_unknown_errors_never_parse_sensitive_message_or_type(self):
        sensitive = "private@example.org https://provider.example/?token=offline-private-token HTTP 429"
        injected_type = type("private_provider_class_name", (RuntimeError,), {})
        for error, expected in ((EditorError(sensitive), "EditorError"),
                                (injected_type(sensitive), "UnexpectedError")):
            with self.subTest(expected=expected):
                self.app = self.make_app(preview_runner=Mock(side_effect=error))
                self.app._run_preview()
                _, result = self.request("GET", "/api/admin/preview")
                self.assertEqual(result["error_type"], expected)
                self.assertEqual(set(result), {"status", "error", "error_type", "error_stage"})
                self.assertNotIn("private", json.dumps(result))

    def test_preview_only_exposes_allowlisted_editor_code_and_integer_http_status(self):
        sensitive = "private@example.org https://provider.example/?token=offline-private-token HTTP 403"
        cases = [("model_http_error", 429, {"error_code": "model_http_error", "http_status": 429}),
                 (sensitive, "403", {}), (sensitive, True, {}), (sensitive, 600, {})]
        for code, status, metadata in cases:
            with self.subTest(status=status):
                error = EditorError(sensitive, error_code=code, http_status=status)
                self.assertEqual(error.error_code, code if code == "model_http_error" else None)
                self.assertEqual(error.http_status, 429 if type(status) is int and status == 429 else None)
                # Simulate attributes overwritten by another caller; the HTTP
                # boundary must independently enforce the same fixed contract.
                error.error_code, error.http_status = code, status
                self.app = self.make_app(preview_runner=Mock(side_effect=error))
                self.app._run_preview()
                _, result = self.request("GET", "/api/admin/preview")
                self.assertEqual(result, {"status": "failed", "error": "preview_failed",
                    "error_type": "EditorError", "error_stage": "preview_pipeline", **metadata})
                self.assertNotIn("private", json.dumps(result))

    def test_subscriber_state_diagnostics_distinguish_init_and_registry_after_auth(self):
        sensitive = "private@example.org https://provider.example/?token=offline-private-token"
        self.service_factory.side_effect = StateError(sensitive)
        status, result = self.request("GET", "/api/admin/subscribers")
        self.assertEqual((status, result), (503, {"error": "state_unavailable",
            "state_error_type": "StateError", "error_stage": "subscription_service_init"}))
        self.service_factory.side_effect = None
        self.service.list_subscribers.side_effect = StateConflict(sensitive)
        status, result = self.request("GET", "/api/admin/subscribers")
        self.assertEqual((status, result), (503, {"error": "state_unavailable",
            "state_error_type": "StateConflict", "error_stage": "subscriber_registry_read"}))
        self.assertNotIn("private", json.dumps(result))
        before = self.service_factory.call_count
        self.assert_error(401, lambda: self.request("GET", "/api/admin/subscribers", authorization=None))
        self.assertEqual(self.service_factory.call_count, before)

    def test_publish_reloads_before_bounded_cas_retry(self):
        self.app._preview_state = {"status": "ready", "preview": deepcopy(PREVIEW)}
        self.app._generated_preview = deepcopy(PREVIEW)
        self.store.save.side_effect = [StateConflict("offline conflict"), None]
        self.assertEqual(self.request("POST", "/api/admin/publish", {})[0], 200)
        self.assertEqual(self.store.load.call_count, 2)
        self.assertEqual(self.store_factory.call_count, 2)
        self.store.save.side_effect = StateConflict("offline conflict")
        before = self.store.save.call_count
        self.assert_error(409, lambda: self.request("POST", "/api/admin/publish", {}))
        self.assertEqual(self.store.save.call_count - before, 3)

    def test_github_transport_blocks_redirects_and_caps_response(self):
        app = space_app.SpaceApplication(ENV)
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.status = 200
        response.read.return_value = b"x" * (space_app.MAX_GITHUB_BYTES + 1)
        opener = Mock()
        opener.open.return_value = response
        with patch.object(space_app, "build_opener", return_value=opener) as build:
            self.assert_error(503, lambda: app._github("GET",
                "/repos/Rexmiao/levyquant-digest/actions/workflows/daily-digest.yml/runs?per_page=5"))
        self.assertIsInstance(build.call_args.args[0], space_app._NoRedirect)
        self.assertIsNone(build.call_args.args[0].redirect_request(None, None, 302, None, None,
                                                                "https://attacker.example"))
        response.read.assert_called_once_with(space_app.MAX_GITHUB_BYTES + 1)
        self.assertEqual(opener.open.call_args.kwargs["timeout"], 20)


class HttpBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        for name in ("index.html", "admin.html", "app.js", "app.css"):
            (root / name).write_text("shell-" + name, encoding="utf-8")
        self.service = Mock()
        self.app = space_app.SpaceApplication(ENV, static_root=root, subscription_factory=Mock(return_value=self.service),
            store_factory=Mock(side_effect=StateError("private@example.org api-key")))
        self.server = space_app.SpaceHTTPServer(("127.0.0.1", 0), self.app)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=2)
        try:
            connection.request(method, path, body, headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read().decode()
        finally:
            connection.close()

    def test_confirmation_and_unsubscribe_get_only_show_shell_and_log_nothing(self):
        captured_out, captured_err = StringIO(), StringIO()
        with redirect_stdout(captured_out), redirect_stderr(captured_err):
            for path in ("/confirm?id=private-id&token=private-token", "/unsubscribe?id=private-id&token=private-token"):
                status, headers, body = self.request("GET", path)
                self.assertEqual((status, body), (200, "shell-index.html"))
                self.assertEqual(headers["Cache-Control"], "no-store")
                self.assertEqual(headers["Referrer-Policy"], "no-referrer")
                self.assertIn("object-src 'none'", headers["Content-Security-Policy"])
                self.assertNotIn("Access-Control-Allow-Origin", headers)
        self.assertEqual(captured_out.getvalue() + captured_err.getvalue(), "")
        self.service.confirm.assert_not_called()
        self.service.unsubscribe.assert_not_called()

    def test_one_click_accepts_receiver_urlencoded_and_multipart_posts_without_login(self):
        self.service.one_click_unsubscribe.return_value = {"status": "unsubscribed"}
        path = "/one-click-unsubscribe?id=" + "i" * 24 + "&token=" + "t" * 43
        status, _, body = self.request("POST", path, "List-Unsubscribe=One-Click",
                                     {"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual((status, json.loads(body)), (200, {"status": "unsubscribed"}))
        boundary = "----ReceiverBoundary123"
        multipart = ("--" + boundary + '\r\nContent-Disposition: form-data; name="List-Unsubscribe"\r\n\r\n'
                     + "One-Click\r\n--" + boundary + "--\r\n")
        status, _, body = self.request("POST", path, multipart,
                                     {"Content-Type": "multipart/form-data; boundary=" + boundary})
        self.assertEqual((status, json.loads(body)), (200, {"status": "unsubscribed"}))
        self.assertEqual(self.service.one_click_unsubscribe.call_count, 2)
        self.service.one_click_unsubscribe.assert_called_with("i" * 24, "t" * 43)

    def test_one_click_scanners_invalid_bodies_and_duplicate_parameters_cannot_unsubscribe(self):
        path = "/one-click-unsubscribe?id=" + "i" * 24 + "&token=" + "t" * 43
        captured = StringIO()
        with redirect_stdout(captured), redirect_stderr(captured):
            self.assertEqual(self.request("GET", path)[0], 405)
            cases = [(path, "List-Unsubscribe=Other", "application/x-www-form-urlencoded", 400),
                     (path, "List-Unsubscribe=One-Click&extra=field", "application/x-www-form-urlencoded", 400),
                     (path, "List-Unsubscribe=One-Click&List-Unsubscribe=One-Click", "application/x-www-form-urlencoded", 400),
                     (path, "{}", "application/json", 415),
                     (path, "x" * 4097, "application/x-www-form-urlencoded", 413),
                     (path + "&id=" + "i" * 24, "List-Unsubscribe=One-Click", "application/x-www-form-urlencoded", 400),
                     ("/one-click-unsubscribe?id=" + "i" * 24, "List-Unsubscribe=One-Click", "application/x-www-form-urlencoded", 400)]
            for url, data, content_type, expected in cases:
                self.assertEqual(self.request("POST", url, data, {"Content-Type": content_type})[0], expected)
        self.assertEqual(captured.getvalue(), "")
        self.service.one_click_unsubscribe.assert_not_called()
        self.app._subscription_factory.assert_not_called()

    def test_invalid_signed_one_click_link_does_not_report_success(self):
        self.service.one_click_unsubscribe.return_value = {"status": "invalid"}
        path = "/one-click-unsubscribe?id=" + "i" * 24 + "&token=" + "t" * 43
        status, _, body = self.request("POST", path, "List-Unsubscribe=One-Click",
                                     {"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual((status, json.loads(body)), (400, {"error": "invalid_unsubscribe_link"}))

    def test_private_api_denied_and_errors_never_include_state_error_text(self):
        status, _, body = self.request("GET", "/api/admin/subscribers")
        self.assertEqual((status, json.loads(body)), (401, {"error": "unauthorized"}))
        status, _, body = self.request("POST", "/api/admin/send", "{}",
            {"Authorization": AUTH, "Content-Type": "application/json"})
        self.assertEqual((status, json.loads(body)), (503, {"error": "state_unavailable"}))
        self.assertNotIn("private", body)
        self.assertNotIn("api-key", body)

    def test_real_subscription_validation_error_is_400_and_has_no_sensitive_message(self):
        self.service.confirm.side_effect = SubscriptionError("private@example.org sensitive-token")
        status, _, body = self.request("POST", "/api/confirm", '{"id":"opaque_id","token":"opaque-token"}',
            {"Content-Type": "application/json"})
        self.assertEqual((status, json.loads(body)), (400, {"error": "invalid_request"}))
        self.assertNotIn("private", body)
        self.assertNotIn("sensitive", body)

    def test_oversized_non_json_and_non_object_bodies_are_rejected(self):
        for body, headers, expected in (("x" * 4097, {"Content-Type": "application/json"}, 413),
                ("{}", {"Content-Type": "text/plain"}, 415),
                ("[]", {"Content-Type": "application/json"}, 400),
                ('{"email":"one@example.org"', {"Content-Type": "application/json"}, 400)):
            with self.subTest(expected=expected):
                status, _, _ = self.request("POST", "/api/subscribe", body, headers)
                self.assertEqual(status, expected)
        self.app._subscription_factory.assert_not_called()

    def test_api_query_tokens_not_accepted_as_admin_auth_or_subscription_action(self):
        status, _, body = self.request("GET", "/api/admin/status?token=" + TOKEN)
        self.assertEqual((status, json.loads(body)), (400, {"error": "invalid_request"}))
        self.service.confirm.assert_not_called()

    def test_static_assets_match_page_urls_and_disallow_arbitrary_paths(self):
        for path, expected_type in (("/static/app.js", "text/javascript"), ("/static/app.css", "text/css")):
            status, headers, body = self.request("GET", path)
            self.assertEqual(status, 200)
            self.assertTrue(headers["Content-Type"].startswith(expected_type))
            self.assertEqual(body, "shell-" + path.rsplit("/", 1)[1])
        self.assertEqual(self.request("GET", "/static/../../config/cloud.json")[0], 404)

    def test_concurrent_request_limit_closes_excess_connections_without_spawning(self):
        slots = Mock()
        slots.acquire.return_value = False
        request = Mock()
        with patch.object(self.server, "_slots", slots), patch.object(self.server, "shutdown_request") as close:
            self.server.process_request(request, ("127.0.0.1", 12345))
        slots.acquire.assert_called_once_with(blocking=False)
        close.assert_called_once_with(request)

    def test_public_throttle_does_not_block_static_get_or_authorized_admin(self):
        self.service.confirm.return_value = {"status": "confirmed"}
        self.service.list_subscribers.return_value = []
        for _ in range(6):
            self.assertEqual(self.request("POST", "/api/confirm", '{"id":"opaque_id","token":"opaque-token"}',
                {"Content-Type": "application/json"})[0], 200)
        before = self.app._subscription_factory.call_count
        self.assertEqual(self.request("POST", "/api/confirm", '{"id":"opaque_id","token":"opaque-token"}',
            {"Content-Type": "application/json"})[0], 429)
        self.assertEqual(self.app._subscription_factory.call_count, before)
        self.assertEqual(self.request("GET", "/")[0], 200)
        self.assertEqual(self.request("GET", "/static/app.css")[0], 200)
        self.assertEqual(self.request("GET", "/api/admin/subscribers", headers={"Authorization": AUTH})[0], 200)


class RateLimiterTests(unittest.TestCase):
    def test_monotonic_expiry_and_bounded_hashed_client_memory(self):
        moment = [100.0]
        limiter = space_app._PublicRateLimiter(clock=lambda: moment[0], global_limit=1000,
                                               client_limit=1000, max_clients=256)
        for index in range(256):
            limiter.check(f"192.0.2.{index}")
        self.assertEqual(len(limiter._clients), 256)
        self.assertTrue(all(len(key) == 64 and "." not in key for key in limiter._clients))
        with self.assertRaises(space_app.AppError) as caught:
            limiter.check("198.51.100.1")
        self.assertEqual(caught.exception.status, 429)
        self.assertEqual(len(limiter._clients), 256)
        moment[0] = 160.0
        limiter.check("198.51.100.1")
        self.assertEqual(len(limiter._clients), 1)
        self.assertEqual(len(limiter._global), 1)

    def test_simultaneous_requests_share_locked_global_budget(self):
        limiter = space_app._PublicRateLimiter()
        accepted, guard = [], threading.Lock()
        def check(index):
            try:
                limiter.check(f"hashed-{index}")
            except space_app.AppError as error:
                self.assertEqual(error.status, 429)
            else:
                with guard:
                    accepted.append(index)
        threads = [threading.Thread(target=check, args=(index,)) for index in range(40)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(accepted), 20)
        self.assertLessEqual(len(limiter._clients), 256)


if __name__ == "__main__":
    unittest.main()
