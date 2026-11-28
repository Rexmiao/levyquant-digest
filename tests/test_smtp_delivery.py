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
            subject="LévyQuant Daily — 宏观晨报", html="<p>Markets &amp; 量化研究</p>",
            text="Markets & 量化研究", sender=self.sender, recipient=self.recipient,
            edition_id="2026-11-25-morning",
        )
        options.update(changes)
        return delivery.prepare_message(**options)

    def send(self):
        return delivery.send_one(self.message, username=self.sender, password=self.password)

    def test_prepared_message_has_one_recipient_and_utf8_alternatives(self):
        parsed = BytesParser(policy=policy.default).parsebytes(self.message.as_bytes())
        self.assertEqual(parsed["From"].addresses[0].display_name, "LévyQuant")
        self.assertEqual(parsed["From"].addresses[0].addr_spec, self.sender)
        self.assertEqual(parsed["To"].addresses[0].addr_spec, self.recipient)
        self.assertIsNone(parsed["Cc"])
        self.assertIsNone(parsed["Bcc"])
        self.assertIsNone(parsed["List-Unsubscribe"])
        self.assertIsNone(parsed["List-Unsubscribe-Post"])
        self.assertEqual(str(parsed["Subject"]), "LévyQuant Daily — 宏观晨报")
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

    def test_one_click_headers_are_valid_literal_ascii_and_do_not_change_the_body(self):
        url = "https://example-digest.hf.space/one-click-unsubscribe?id=" + "a" * 24 + "&token=" + "b" * 43
        message = self.make_message(unsubscribe_url=url)
        wire = message.as_bytes().decode("ascii")
        self.assertIn("List-Unsubscribe: <" + url + ">\r\n", wire)
        self.assertIn("List-Unsubscribe-Post: List-Unsubscribe=One-Click\r\n", wire)
        parsed = BytesParser(policy=policy.default).parsebytes(message.as_bytes())
        self.assertEqual(str(parsed["List-Unsubscribe"]), "<" + url + ">")
        baseline = BytesParser(policy=policy.default).parsebytes(self.message.as_bytes())
        self.assertEqual(parsed.get_body(preferencelist=("plain",)).get_content(),
                         baseline.get_body(preferencelist=("plain",)).get_content())
        self.smtp.assert_not_called()

    def test_actual_smtp_data_preserves_literal_one_click_headers(self):
        url = "https://example-digest.hf.space/one-click-unsubscribe?id=" + "a" * 24 + "&token=" + "b" * 43
        self.message = self.make_message(unsubscribe_url=url)
        self.assertEqual(self.send()["status"], "accepted")
        wire = self.client.data.call_args.args[0].decode("ascii")
        self.assertIn("List-Unsubscribe: <" + url + ">\r\n", wire)
        self.assertIn("List-Unsubscribe-Post: List-Unsubscribe=One-Click\r\n", wire)
        self.assertNotIn("=?", next(line for line in wire.split("\r\n") if line.startswith("List-Unsubscribe:")))

    def test_one_click_header_rejects_foreign_hosts_paths_tokens_and_injection(self):
        good = "https://example-digest.hf.space/one-click-unsubscribe?id=" + "a" * 24 + "&token=" + "b" * 43
        for url in (good.replace("https:", "http:"), good.replace("example-digest.hf.space", "outside.example"),
                    good.replace("example-digest.hf.space", "user:password@example-digest.hf.space"),
                    good.replace(".hf.space/", ".hf.space:443/"), good.replace("/one-click-unsubscribe", "/unsubscribe"),
                    good.replace("example-digest.hf.space", "evil.daily.levyquant.ai"),
                    good.replace("example-digest.hf.space", "daily.levyquant.ai.evil.example"),
                    good.replace("example-digest.hf.space", "levyquant.ai"),
                    good + "#fragment", good + "&id=" + "c" * 24, good + "\r\nBcc: hidden@example.org",
                    good.replace("b" * 43, "%0d%0aheader")):
            with self.subTest(url=url), self.assertRaises(delivery.DeliveryError) as captured:
                self.make_message(unsubscribe_url=url)
            self.assertEqual(captured.exception.stage, "validation")
        self.smtp.assert_not_called()

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


class SMTPSessionTests(unittest.TestCase):
    def setUp(self):
        self.sender = "sender@example.com"
        self.password = "test-only-secret-that-must-not-leak"
        self.clients = []
        def connect(*args, **kwargs):
            client = Mock()
            client.mail.return_value = (250, b"Sender accepted")
            client.rcpt.return_value = (250, b"Recipient accepted")
            client.data.return_value = (250, b"Message accepted")
            self.clients.append(client)
            return client
        self.smtp_patch = patch.object(delivery.smtplib, "SMTP_SSL", side_effect=connect)
        self.smtp = self.smtp_patch.start()
        self.addCleanup(self.smtp_patch.stop)

    def message(self, recipient):
        return delivery.prepare_message("LévyQuant Morning Briefing", "<p>Body</p>", "Body",
                                        self.sender, recipient, "2026-11-28-morning")

    def test_one_login_is_reused_for_several_single_recipient_transactions(self):
        recipients = ["a@example.org", "b@example.org", "c@example.org"]
        with delivery.SMTPSession(self.sender, self.password) as session:
            results = [session.send(self.message(address)) for address in recipients]
        self.assertEqual([result["status"] for result in results], ["accepted"] * 3)
        self.assertEqual(self.smtp.call_count, 1)
        client = self.clients[0]
        client.login.assert_called_once_with(self.sender, self.password)
        self.assertEqual([call.args[0] for call in client.rcpt.call_args_list], recipients)
        self.assertEqual(client.data.call_count, 3)
        client.close.assert_called_once()

    def test_connection_is_replaced_after_the_per_connection_limit(self):
        with patch.object(delivery.SMTPSession, "MAX_MESSAGES_PER_CONNECTION", 2):
            with delivery.SMTPSession(self.sender, self.password) as session:
                for index in range(5):
                    session.send(self.message("r%d@example.org" % index))
        self.assertEqual(self.smtp.call_count, 3)
        self.assertEqual([client.data.call_count for client in self.clients], [2, 2, 1])

    def test_any_failure_closes_the_connection_and_the_next_message_reconnects(self):
        session = delivery.SMTPSession(self.sender, self.password)
        self.assertEqual(session.send(self.message("a@example.org"))["status"], "accepted")
        self.clients[0].rcpt.return_value = (550, b"No such recipient")
        with self.assertRaises(delivery.DeliveryError) as caught:
            session.send(self.message("missing@example.org"))
        self.assertEqual(caught.exception.stage, "recipient")
        self.clients[0].close.assert_called_once()
        self.assertEqual(session.send(self.message("b@example.org"))["status"], "accepted")
        self.assertEqual(self.smtp.call_count, 2)
        session.close()

    def test_reused_connection_dropped_before_data_reconnects_once_without_duplicate(self):
        session = delivery.SMTPSession(self.sender, self.password)
        session.send(self.message("a@example.org"))
        self.clients[0].mail.side_effect = smtplib.SMTPServerDisconnected("idle timeout")
        result = session.send(self.message("b@example.org"))
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(self.smtp.call_count, 2)
        self.assertEqual(self.clients[0].data.call_count, 1)
        self.assertEqual(self.clients[1].data.call_count, 1)
        session.close()

    def test_second_drop_before_data_is_a_known_retry_safe_failure(self):
        session = delivery.SMTPSession(self.sender, self.password)
        session.send(self.message("a@example.org"))
        self.clients[0].rcpt.side_effect = smtplib.SMTPServerDisconnected("idle timeout")
        original = self.smtp.side_effect
        def connect_broken(*args, **kwargs):
            client = original(*args, **kwargs)
            client.mail.side_effect = smtplib.SMTPServerDisconnected("dropped again")
            return client
        self.smtp.side_effect = connect_broken
        with self.assertRaises(delivery.DeliveryError) as caught:
            session.send(self.message("b@example.org"))
        self.assertNotIsInstance(caught.exception, delivery.DeliveryUncertain)
        self.assertTrue(caught.exception.retry_safe)
        self.assertEqual(self.smtp.call_count, 2)
        self.assertEqual(sum(client.data.call_count for client in self.clients), 1)

    def test_data_failure_on_a_reused_connection_is_uncertain_and_never_retried(self):
        session = delivery.SMTPSession(self.sender, self.password)
        session.send(self.message("a@example.org"))
        self.clients[0].data.side_effect = smtplib.SMTPServerDisconnected(self.password)
        with self.assertRaises(delivery.DeliveryUncertain) as caught:
            session.send(self.message("b@example.org"))
        self.assertEqual(caught.exception.stage, "data")
        self.assertNotIn(self.password, str(caught.exception))
        self.assertEqual(self.smtp.call_count, 1)
        self.assertEqual(self.clients[0].data.call_count, 2)

    def test_session_rejects_a_different_account_before_connecting(self):
        session = delivery.SMTPSession(self.sender, self.password)
        with self.assertRaisesRegex(delivery.DeliveryError, "must match"):
            session.send(self.message("a@example.org"), username="other@example.org")
        with self.assertRaisesRegex(delivery.DeliveryError, "must match"):
            session.send(self.message("a@example.org"), password="a-different-secret")
        self.smtp.assert_not_called()


if __name__ == "__main__":
    unittest.main()
