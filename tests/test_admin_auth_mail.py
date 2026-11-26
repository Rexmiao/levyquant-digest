"""Offline administrator-code delivery boundaries; never contacts SMTP or GitHub."""
from copy import deepcopy
from contextlib import redirect_stdout
import base64
from datetime import datetime, timedelta, timezone
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from levyquant import subscription_mail as mail
from levyquant.smtp_delivery import DeliveryError, DeliveryUncertain
from levyquant.state_store import StateError
from levyquant.subscriptions import REPOSITORY, SubscriptionError


NOW = datetime(2026, 11, 26, 12, tzinfo=timezone.utc)
IDENTIFIER = "offline_admin_request"
CLAIM = {"id": IDENTIFIER, "email": "admin@example.org", "code": "012345",
         "expires_at": (NOW + timedelta(minutes=10)).isoformat(), "reservation_id": "offline_reservation"}
ENV = {"SUBSCRIPTIONS_ENABLED": "true", "GITHUB_REPOSITORY": REPOSITORY,
       "GITHUB_TOKEN": "offline_github_token", "STATE_ENCRYPTION_KEY": "offline_state_key",
       "SMTP_USERNAME": "sender@example.org", "SMTP_APP_PASSWORD": "offline_password"}


class FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)


class ReservedQueue:
    """Controlled service contract: only an acknowledged claim exposes the code."""
    def __init__(self, claim=None):
        self.claim = deepcopy(CLAIM if claim is None else claim)
        self.status = "queued"
        self.claim_count = 0
        self.marks = []

    def pending_login_messages(self, limit=10):
        if limit != 10:
            raise AssertionError("unbounded admin queue")
        return [{"id": IDENTIFIER}] if self.status == "queued" else []

    def claim_login_message(self, identifier):
        self.claim_count += 1
        if identifier != IDENTIFIER or self.status != "queued":
            return None
        self.status = "reserved"
        return deepcopy(self.claim)

    def mark_login_message(self, identifier, status, *, reservation_id, stage=None, smtp_code=None):
        if (identifier != IDENTIFIER or self.status != "reserved"
                or reservation_id != self.claim["reservation_id"]):
            raise AssertionError("unmatched reservation")
        self.status = status
        self.marks.append((identifier, status, reservation_id, stage, smtp_code))


class AdminMailTests(unittest.TestCase):
    def setUp(self):
        self.clock = patch.object(mail, "datetime", FrozenDatetime)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.admin = ReservedQueue()
        self.transport = Mock(return_value={"status": "accepted", "smtp_code": 250})

    def run_admin(self, *, environment=None, service=None, transport=None):
        return mail.run(ENV if environment is None else environment,
                        admin_service=self.admin if service is None else service,
                        transport=self.transport if transport is None else transport)

    def test_reserved_code_message_has_no_link_and_result_has_no_private_values(self):
        def transport(message, **kwargs):
            self.assertEqual(self.admin.status, "reserved")
            self.assertEqual(self.admin.marks, [])
            self.assertEqual(str(message["Subject"]), mail.ADMIN_SUBJECT)
            self.assertEqual(str(message["To"]), CLAIM["email"])
            self.assertNotIn(CLAIM["code"], str(message["Message-ID"]))
            text = message.get_body(preferencelist=("plain",)).get_content()
            html = message.get_body(preferencelist=("html",)).get_content()
            for body in (text, html):
                self.assertIn(CLAIM["code"], body)
                self.assertIn("10 minutes", body)
                self.assertIn("Do not forward or share", body)
                self.assertNotIn("https://", body)
                self.assertNotIn("href=", body)
            return {"status": "accepted", "smtp_code": 250}

        result = self.run_admin(transport=transport)
        self.assertEqual(result, {"status": "completed", "accepted": 1, "rejected": 0, "uncertain": 0, "skipped": 0})
        self.assertEqual(self.admin.marks, [(IDENTIFIER, "accepted", CLAIM["reservation_id"], None, 250)])
        for private in (CLAIM["email"], CLAIM["code"], CLAIM["reservation_id"], *ENV.values()):
            self.assertNotIn(private, json.dumps(result))
        self.run_admin()
        self.transport.assert_not_called()

    def test_default_production_call_initializes_both_queues(self):
        subscriptions = Mock()
        def pending_confirmations(**kwargs):
            self.assertEqual(self.admin.status, "accepted")
            return []
        subscriptions.pending_confirmations.side_effect = pending_confirmations
        with (patch.object(mail, "service_from_env", return_value=subscriptions) as subscription_factory,
              patch.object(mail, "admin_service_from_env", return_value=self.admin) as admin_factory):
            result = mail.run(ENV, transport=self.transport)
        subscription_factory.assert_called_once_with(ENV)
        admin_factory.assert_called_once_with(ENV)
        subscriptions.pending_confirmations.assert_called_once_with(limit=20)
        self.assertEqual(result["accepted"], 1)

    def test_administrator_queue_works_while_public_subscriptions_are_disabled(self):
        environment = {**ENV, "SUBSCRIPTIONS_ENABLED": "false"}
        with (patch.object(mail, "service_from_env") as subscription_factory,
              patch.object(mail, "admin_service_from_env", return_value=self.admin) as admin_factory):
            result = mail.run(environment, transport=self.transport)
        subscription_factory.assert_not_called()
        admin_factory.assert_called_once_with(environment)
        self.assertEqual(result["accepted"], 1)

    def test_missing_configuration_stays_disabled_and_legacy_injection_does_not_open_admin_state(self):
        subscriptions = Mock()
        subscriptions.pending_confirmations.return_value = []
        with (patch.object(mail, "service_from_env") as subscription_factory,
              patch.object(mail, "admin_service_from_env") as admin_factory):
            self.assertEqual(mail.run({})["status"], "disabled")
            self.assertEqual(mail.run(ENV, service=subscriptions, transport=self.transport)["status"], "completed")
        subscription_factory.assert_not_called()
        admin_factory.assert_not_called()
        self.transport.assert_not_called()

    def test_wrong_repository_stops_before_factories_or_smtp(self):
        with patch.object(mail, "service_from_env") as subscriptions, patch.object(mail, "admin_service_from_env") as admins:
            with self.assertRaises(SubscriptionError):
                mail.run({**ENV, "GITHUB_REPOSITORY": "other/repository"}, transport=self.transport)
        subscriptions.assert_not_called()
        admins.assert_not_called()
        self.transport.assert_not_called()

    def test_expired_claim_and_unclaimed_request_never_reach_smtp(self):
        self.admin.claim["expires_at"] = NOW.isoformat()
        result = self.run_admin()
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(self.admin.marks, [])
        unclaimed = Mock()
        unclaimed.pending_login_messages.return_value = [{"id": IDENTIFIER}]
        unclaimed.claim_login_message.return_value = None
        self.assertEqual(self.run_admin(service=unclaimed)["skipped"], 1)
        unclaimed.mark_login_message.assert_not_called()
        self.transport.assert_not_called()

    def test_invalid_claims_are_rejected_before_transport(self):
        variants = [{"id": "different"}, {"email": "bad\nInjected@example.org"}, {"email": "invalid"},
                    {"code": "12345"}, {"code": "1234567"}, {"code": "１２３４５６"}, {"code": 123456},
                    {"code": "12345\n"}, {"expires_at": "2026-11-26"},
                    {"expires_at": "2026-11-26T12:10:00"}, {"expires_at": "invalid"},
                    {"reservation_id": ""}, {"reservation_id": "unsafe\nvalue"}, {"unexpected": "private-value"}]
        for updates in variants:
            with self.subTest(fields=tuple(updates)):
                admin = ReservedQueue({**CLAIM, **updates})
                with self.assertRaises(SubscriptionError) as captured:
                    self.run_admin(service=admin)
                self.assertNotIn(CLAIM["code"], str(captured.exception))
                self.assertEqual(admin.marks, [])
        self.transport.assert_not_called()

    def test_invalid_pending_queue_never_claims_or_transports(self):
        for pending in (None, [{"id": IDENTIFIER}] * 11, [{"id": IDENTIFIER, "email": "private@example.org"}],
                        [{"id": "bad\nidentifier"}], [{}]):
            with self.subTest(kind=type(pending).__name__):
                admin = Mock()
                admin.pending_login_messages.return_value = pending
                with self.assertRaises(SubscriptionError):
                    self.run_admin(service=admin)
                admin.claim_login_message.assert_not_called()
        self.transport.assert_not_called()

    def test_unacknowledged_claim_never_calls_smtp(self):
        admin = Mock()
        admin.pending_login_messages.return_value = [{"id": IDENTIFIER}]
        admin.claim_login_message.side_effect = StateError("private-provider-data")
        with self.assertRaises(StateError):
            self.run_admin(service=admin)
        self.transport.assert_not_called()
        admin.mark_login_message.assert_not_called()

    def test_uncertain_or_crashed_submission_is_not_replayed(self):
        uncertain = Mock(side_effect=DeliveryUncertain("private-value", stage="data"))
        self.assertEqual(self.run_admin(transport=uncertain)["uncertain"], 1)
        self.assertEqual(self.admin.status, "uncertain")
        self.run_admin()
        self.transport.assert_not_called()
        self.admin = ReservedQueue()
        crashed = Mock(side_effect=RuntimeError("private-value"))
        with self.assertRaises(RuntimeError):
            self.run_admin(transport=crashed)
        self.assertEqual(self.admin.status, "reserved")
        self.assertEqual(self.admin.marks, [])
        self.run_admin()
        self.transport.assert_not_called()

    def test_rejection_and_unrecognized_receipt_are_recorded_without_sensitive_fields(self):
        rejected = Mock(side_effect=DeliveryError("private-value", stage="recipient", smtp_code=550))
        result = self.run_admin(transport=rejected)
        self.assertEqual((result["status"], result["rejected"]), ("needs_attention", 1))
        self.assertEqual(self.admin.marks[0][-2:], ("recipient", 550))
        self.admin = ReservedQueue()
        result = self.run_admin(transport=Mock(return_value={"status": "unexpected", "smtp_code": "private-value"}))
        self.assertEqual(result["uncertain"], 1)
        self.assertEqual(self.admin.marks[0][-2:], (None, None))

    def test_terminal_mark_failure_does_not_retry_an_accepted_submission(self):
        self.admin.mark_login_message = Mock(side_effect=StateError("unacknowledged mark"))
        with self.assertRaises(StateError):
            self.run_admin()
        self.assertEqual(self.transport.call_count, 1)
        self.assertEqual(self.admin.status, "reserved")
        retry = Mock()
        self.run_admin(transport=retry)
        retry.assert_not_called()

    def test_cli_error_output_never_contains_code_email_or_exception_message(self):
        output = StringIO()
        with patch.object(mail, "run", side_effect=RuntimeError(CLAIM["email"] + " " + CLAIM["code"])), redirect_stdout(output):
            self.assertEqual(mail.main(), 1)
        self.assertEqual(json.loads(output.getvalue()), {"status": "failed", "error_type": "RuntimeError"})

    def test_real_admin_service_reserves_before_transport_and_accepted_is_not_resent(self):
        from levyquant.admin_auth import AdminAuthService
        from levyquant.state_store import LocalStateStore

        with tempfile.TemporaryDirectory() as directory:
            service = AdminAuthService(LocalStateStore(Path(directory)),
                                       base64.urlsafe_b64encode(b"x" * 32).decode(), now=lambda: NOW)
            service.configure_emails(["admin@example.org"])
            service.request_login("admin@example.org", "offline-client")
            identifier = service.pending_login_messages()[0]["id"]

            def transport(message, **kwargs):
                self.assertIsNone(service.claim_login_message(identifier))
                self.assertEqual(service.pending_login_messages(), [])
                self.assertEqual(str(message["To"]), "admin@example.org")
                return {"status": "accepted", "smtp_code": 250}

            result = self.run_admin(service=service, transport=transport)
            self.assertEqual(result["accepted"], 1)
            repeat = Mock()
            self.run_admin(service=service, transport=repeat)
            repeat.assert_not_called()

    def test_real_admin_service_records_mail_stage_rejection_and_never_resends(self):
        from levyquant.admin_auth import AdminAuthService, STATE_PATH
        from levyquant.state_store import LocalStateStore

        with tempfile.TemporaryDirectory() as directory:
            store = LocalStateStore(Path(directory))
            service = AdminAuthService(store, base64.urlsafe_b64encode(b"x" * 32).decode(), now=lambda: NOW)
            service.configure_emails(["admin@example.org"])
            service.request_login("admin@example.org", "offline-client")
            rejected = Mock(side_effect=DeliveryError("private-provider-data", stage="mail", smtp_code=550))

            result = self.run_admin(service=service, transport=rejected)
            self.assertEqual((result["status"], result["rejected"]), ("needs_attention", 1))
            self.assertEqual(rejected.call_count, 1)
            persisted = store.load(STATE_PATH)["challenges"][0]["message"]
            self.assertEqual((persisted["status"], persisted["stage"], persisted["smtp_code"]),
                             ("rejected", "mail", 550))
            self.assertEqual(service.pending_login_messages(), [])
            repeat = Mock()
            self.run_admin(service=service, transport=repeat)
            repeat.assert_not_called()


if __name__ == "__main__":
    unittest.main()
