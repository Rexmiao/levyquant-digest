"""Offline SMTP transaction and duplicate-risk tests; never opens a real socket."""

import contextlib
from email import policy
from email.parser import BytesParser
import io
import smtplib
import ssl
import unittest
from unittest.mock import Mock, patch

from levyquant import smtp_delivery as delivery


class SMTPDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.sender = "sender@example.com"
        self.recipient = "reader@example.com"
        self.password = "test-only-secret-that-must-not-leak"
        self.message = self.make_message()
        self.client = Mock()
        self.client.mail.return_value = (250, b"Sender accepted")
        self.client.rcpt.return_value = (250, b"Recipient accepted")
        self.client.data.return_value = (250, b"Message accepted")
        self.smtp_patch = patch.object(delivery.smtplib, "SMTP_SSL", return_value=self.client)
        self.smtp = self.smtp_patch.start()
        self.addCleanup(self.smtp_patch.stop)

    def make_message(self, **changes):
        options = dict(
            subject="LevyQuant Daily — 宏观晨报", html="<p>Markets &amp; 量化研究</p>",
            text="Markets & 量化研究", sender=self.sender, recipient=self.recipient,
            edition_id="2026-11-25-morning",
        )
        options.update(changes)
        return delivery.prepare_message(**options)

    def send(self):
        return delivery.send_one(self.message, username=self.sender, password=self.password)

    def test_prepared_message_has_one_recipient_and_utf8_alternatives(self):
        parsed = BytesParser(policy=policy.default).parsebytes(self.message.as_bytes())
        self.assertEqual(parsed["From"].addresses[0].display_name, "LevyQuant")
        self.assertEqual(parsed["From"].addresses[0].addr_spec, self.sender)
        self.assertEqual(parsed["To"].addresses[0].addr_spec, self.recipient)
        self.assertIsNone(parsed["Cc"])
        self.assertIsNone(parsed["Bcc"])
        self.assertEqual(str(parsed["Subject"]), "LevyQuant Daily — 宏观晨报")
        self.assertEqual(parsed.get_content_type(), "multipart/alternative")
        self.assertEqual(parsed.get_body(preferencelist=("plain",)).get_content().strip(), "Markets & 量化研究")
        self.assertEqual(parsed.get_body(preferencelist=("html",)).get_content().strip(), "<p>Markets &amp; 量化研究</p>")
        self.message.as_bytes().decode("ascii")
        self.smtp.assert_not_called()

    def test_message_id_is_stable_per_edition_and_normalized_recipient(self):
        self.assertEqual(self.message["Message-ID"], self.make_message(recipient="Reader@Example.com")["Message-ID"])
        self.assertNotEqual(self.message["Message-ID"], self.make_message(recipient="another@example.com")["Message-ID"])
        self.assertNotEqual(self.message["Message-ID"], self.make_message(edition_id="2026-11-26-morning")["Message-ID"])
        self.assertNotIn(self.recipient, str(self.message["Message-ID"]))

    def test_header_injection_rejected_before_connecting(self):
        for change in (
            {"subject": "Daily\r\nBcc: other@example.com"},
            {"sender": "sender@example.com\nBcc: other@example.com"},
            {"recipient": "reader@example.com,other@example.com"},
            {"recipient": "reader@example.com\r\nBcc: other@example.com"},
            {"edition_id": "edition\nX-Another: injected"},
        ):
            with self.subTest(change=change), self.assertRaises(delivery.DeliveryError):
                self.make_message(**change)
        self.smtp.assert_not_called()

    def test_tampered_bcc_recipient_is_blocked(self):
        self.message["Bcc"] = "hidden@example.com"
        with self.assertRaises(delivery.DeliveryError) as caught:
            self.send()
        self.assertEqual(caught.exception.stage, "validation")
        self.smtp.assert_not_called()

    def test_different_smtp_account_is_blocked(self):
        with self.assertRaisesRegex(delivery.DeliveryError, "must match"):
            delivery.send_one(self.message, username="school@example.edu", password=self.password)
        self.smtp.assert_not_called()

    def test_tls_is_verified_and_envelope_is_single_recipient(self):
        result = self.send()
        self.assertEqual(self.smtp.call_args.args, ("smtp.gmail.com", 465))
        context = self.smtp.call_args.kwargs["context"]
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.client.login.assert_called_once_with(self.sender, self.password)
        self.client.mail.assert_called_once_with(self.sender)
        self.client.rcpt.assert_called_once_with(self.recipient)
        self.client.data.assert_called_once()
        self.assertEqual(result, {"status": "accepted", "recipient": self.recipient,
                                  "message_id": str(self.message["Message-ID"]), "smtp_code": 250})
        self.client.close.assert_called_once()

    def test_transmitted_bytes_preserve_the_prepared_mime(self):
        self.send()
        parsed = BytesParser(policy=policy.default).parsebytes(self.client.data.call_args.args[0])
        self.assertEqual(str(parsed["Message-ID"]), str(self.message["Message-ID"]))
        self.assertEqual(parsed.get_body(preferencelist=("plain",)).get_content().strip(), "Markets & 量化研究")
        self.assertEqual(parsed.get_body(preferencelist=("html",)).get_content().strip(), "<p>Markets &amp; 量化研究</p>")

    def test_connect_failure_is_known_failure_and_does_not_retry(self):
        self.smtp.side_effect = TimeoutError(self.password)
        with self.assertRaises(delivery.DeliveryError) as caught:
            self.send()
        self.assertNotIsInstance(caught.exception, delivery.DeliveryUncertain)
        self.assertEqual(caught.exception.stage, "connect")
        self.assertTrue(caught.exception.retry_safe)
        self.smtp.assert_called_once()
        self.client.mail.assert_not_called()

    def test_authentication_failure_redacts_server_response_and_secret(self):
        self.client.login.side_effect = smtplib.SMTPAuthenticationError(535, self.password.encode())
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            with self.assertRaises(delivery.DeliveryError) as caught:
                self.send()
        self.assertNotIsInstance(caught.exception, delivery.DeliveryUncertain)
        self.assertEqual(caught.exception.stage, "auth")
        self.assertEqual(caught.exception.smtp_code, 535)
        self.assertNotIn(self.password, str(caught.exception))
        self.assertNotIn(self.password, repr(caught.exception))
        self.assertEqual(stdout.getvalue() + stderr.getvalue(), "")
        self.assertTrue(caught.exception.__suppress_context__)
        self.client.mail.assert_not_called()

    def test_sender_refusal_never_submits_recipient_or_data(self):
        self.client.mail.return_value = (550, self.password.encode())
        with self.assertRaises(delivery.DeliveryError) as caught:
            self.send()
        self.assertEqual(caught.exception.stage, "mail")
        self.assertEqual(caught.exception.smtp_code, 550)
        self.assertNotIn(self.password, str(caught.exception))
        self.client.rcpt.assert_not_called()
        self.client.data.assert_not_called()

    def test_recipient_disconnect_is_known_failure_before_data(self):
        self.client.rcpt.side_effect = smtplib.SMTPServerDisconnected(self.password)
        with self.assertRaises(delivery.DeliveryError) as caught:
            self.send()
        self.assertNotIsInstance(caught.exception, delivery.DeliveryUncertain)
        self.assertEqual(caught.exception.stage, "recipient")
        self.assertTrue(caught.exception.retry_safe)
        self.client.data.assert_not_called()

    def test_recipient_refusal_never_submits_data(self):
        self.client.rcpt.return_value = (550, b"No such recipient")
        with self.assertRaises(delivery.DeliveryError) as caught:
            self.send()
        self.assertFalse(caught.exception.uncertain)
        self.assertEqual(caught.exception.stage, "recipient")
        self.client.data.assert_not_called()

    def test_data_disconnect_or_timeout_is_uncertain_and_never_retried(self):
        for failure in (TimeoutError(self.password), smtplib.SMTPServerDisconnected(self.password)):
            with self.subTest(failure=type(failure).__name__):
                self.client.reset_mock()
                self.client.data.side_effect = failure
                with self.assertRaises(delivery.DeliveryUncertain) as caught:
                    self.send()
                self.assertEqual(caught.exception.stage, "data")
                self.assertTrue(caught.exception.uncertain)
                self.assertFalse(caught.exception.retry_safe)
                self.assertEqual(caught.exception.recipient, self.recipient)
                self.assertEqual(caught.exception.message_id, self.message["Message-ID"])
                self.assertNotIn(self.password, str(caught.exception))
                self.client.data.assert_called_once()
                self.client.close.assert_called_once()

    def test_explicit_data_rejection_is_known_failure(self):
        self.client.data.return_value = (554, b"Rejected")
        with self.assertRaises(delivery.DeliveryError) as caught:
            self.send()
        self.assertNotIsInstance(caught.exception, delivery.DeliveryUncertain)
        self.assertEqual(caught.exception.smtp_code, 554)
        self.assertTrue(caught.exception.retry_safe)
        self.client.data.assert_called_once()

    def test_explicit_data_exception_is_known_failure(self):
        self.client.data.side_effect = smtplib.SMTPDataError(451, self.password.encode())
        with self.assertRaises(delivery.DeliveryError) as caught:
            self.send()
        self.assertNotIsInstance(caught.exception, delivery.DeliveryUncertain)
        self.assertEqual(caught.exception.smtp_code, 451)
        self.assertNotIn(self.password, str(caught.exception))

    def test_unexpected_data_response_is_uncertain(self):
        self.client.data.return_value = (200, b"Unexpected acknowledgement")
        with self.assertRaises(delivery.DeliveryUncertain):
            self.send()

    def test_close_failure_does_not_erase_final_acceptance(self):
        self.client.close.side_effect = OSError(self.password)
        self.assertEqual(self.send()["status"], "accepted")
        self.client.data.assert_called_once()


if __name__ == "__main__":
    unittest.main()
