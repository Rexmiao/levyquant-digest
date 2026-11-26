"""Offline web-boundary tests: no provider, GitHub or mail connection."""
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
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
                ("POST", "/api/admin/subscribers")):
            with self.subTest(path=path):
                self.assert_error(401, lambda: self.request(method, path, {}, authorization="Bearer wrong"))
        self.store_factory.assert_not_called()
        self.service_factory.assert_not_called()
        self.github.assert_not_called()

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

    def test_preview_thread_is_single_concurrent_and_receives_no_smtp_credentials(self):
        entered, release = threading.Event(), threading.Event()
        observed = []
        def runner(config, mode, environment, output):
            observed.append((mode, dict(environment)))
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
        _, result = self.request("GET", "/api/admin/preview")
        self.assertEqual(result, {"status": "ready", "preview": PREVIEW})
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
        self.assertEqual(self.request("GET", "/api/admin/preview")[1], {"status": "failed", "error": "preview_failed"})
        self.assert_error(409, lambda: self.request("POST", "/api/admin/publish", {}))
        self.store.save.assert_not_called()

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
