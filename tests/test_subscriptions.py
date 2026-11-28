"""Offline subscription tokens, CAS, limits, and SMTP-reservation invariants."""
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from io import StringIO
import base64
import json
from pathlib import Path
import secrets
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from levyquant import subscription_mail
from levyquant.smtp_delivery import DeliveryError, DeliveryUncertain, prepare_message
from levyquant.state_store import LocalStateStore, StateConflict, StateError
from levyquant.subscriptions import (REGISTRY_PATH, REPOSITORY, SubscriptionError, SubscriptionService, service_from_env,
                                     validate_email, validate_public_base_url)


KEY = base64.urlsafe_b64encode(b"s" * 32).decode()
BASE = "https://example-digest.hf.space"
NOW = datetime(2026, 11, 26, 12, tzinfo=timezone.utc)


class SubscriptionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = LocalStateStore(Path(temporary.name))
        self.now = NOW
        self.service = SubscriptionService(self.store, KEY, BASE, now=lambda: self.now)

    def link_parts(self, url):
        params = parse_qs(urlsplit(url).query)
        self.assertEqual(set(params), {"id", "token"})
        self.assertNotIn("@", url)
        self.assertNotIn("%40", url.lower())
        return params["id"][0], params["token"][0]

    def claim(self, email="reader@example.org"):
        self.assertTrue(self.service.request_signup(email)["queued"])
        row = next(row for row in self.service.pending_confirmations() if row["email"] == email.lower())
        return self.service.claim_confirmation(row["id"])

    def confirm_reader(self, email="reader@example.org"):
        claimed = self.claim(email)
        self.service.mark_confirmation(claimed["id"], "accepted", reservation_id=claimed["reservation_id"])
        identifier, token = self.link_parts(claimed["url"])
        self.assertEqual(self.service.confirm(identifier, token), {"status": "confirmed"})
        return claimed

    def test_signup_requires_confirmation_and_tokens_are_purpose_separated(self):
        claimed = self.claim("Reader@example.org")
        self.assertEqual(self.service.delivery_recipients([], ["internal@example.org"]), ["internal@example.org"])
        self.assertNotIn("internal@example.org", {row["email"] for row in self.service.list_subscribers()})
        identifier, token = self.link_parts(claimed["url"])
        self.assertEqual(self.service.unsubscribe(identifier, token), {"status": "invalid"})
        self.assertEqual(self.service.confirm(identifier, token), {"status": "confirmed"})
        self.assertEqual(self.service.confirm(identifier, token), {"status": "confirmed"})
        self.assertEqual(self.service.delivery_recipients([], ["internal@example.org"]),
                         ["internal@example.org", "reader@example.org"])
        rows = self.service.list_subscribers()
        self.assertEqual(set(rows[0]), {"id", "email", "status", "created_at", "confirmed_at"})
        self.assertFalse(self.service.request_signup("reader@example.org")["queued"])

    def test_unsubscribe_and_suppression_remove_external_but_never_required_internal(self):
        claimed = self.confirm_reader()
        unsubscribe = self.service.unsubscribe_url("READER@example.org")
        self.assertEqual(unsubscribe, self.service.unsubscribe_url("reader@example.org"))
        identifier, token = self.link_parts(unsubscribe)
        self.assertEqual(self.service.confirm(identifier, token), {"status": "invalid_or_expired"})
        self.assertEqual(self.service.unsubscribe(identifier, token), {"status": "unsubscribed"})
        old_id, old_token = self.link_parts(claimed["url"])
        self.assertEqual(self.service.confirm(old_id, old_token), {"status": "invalid_or_expired"})
        self.assertEqual(self.service.delivery_recipients(["reader@example.org"], ["internal@example.org"]), ["internal@example.org"])
        internal_id, internal_token = self.link_parts(self.service.unsubscribe_url("internal@example.org"))
        self.service.unsubscribe(internal_id, internal_token)
        self.service.admin_suppress(internal_id)
        self.assertEqual(self.service.delivery_recipients(["reader@example.org"], ["INTERNAL@example.org"]), ["internal@example.org"])
        self.assertFalse(self.service.request_signup("internal@example.org")["queued"])

    def test_public_merge_switch_never_disables_legacy_optouts_or_internal_protection(self):
        self.confirm_reader("public@example.org")
        internal = ["internal@example.org"]
        self.assertEqual(self.service.delivery_recipients(["legacy@example.org"], internal,
            include_public_subscribers=False), internal + ["legacy@example.org"])
        self.service.unsubscribe(*self.link_parts(self.service.unsubscribe_url("legacy@example.org")))
        self.assertEqual(self.service.delivery_recipients(["legacy@example.org"], internal,
            include_public_subscribers=False), internal)
        with patch.object(self.store, "save") as save:
            self.assertFalse(self.service.is_delivery_allowed("legacy@example.org", internal))
            self.assertFalse(self.service.is_delivery_allowed("missing@example.org", internal))
            self.assertTrue(self.service.is_delivery_allowed("public@example.org", internal))
            save.assert_not_called()
        self.service.one_click_unsubscribe(*self.link_parts(self.service.one_click_unsubscribe_url(internal[0])))
        self.assertTrue(self.service.is_delivery_allowed(internal[0], internal))

    def test_one_click_tokens_are_separate_from_web_and_confirmation_tokens(self):
        confirmation = self.confirm_reader()
        web = self.service.unsubscribe_url("reader@example.org")
        click = self.service.one_click_unsubscribe_url("reader@example.org")
        self.assertEqual(urlsplit(click).path, "/one-click-unsubscribe")
        identifier, web_token = self.link_parts(web)
        click_id, click_token = self.link_parts(click)
        self.assertEqual(click_id, identifier)
        self.assertNotEqual(web_token, click_token)
        self.assertEqual(self.service.one_click_unsubscribe(identifier, web_token), {"status": "invalid"})
        self.assertEqual(self.service.unsubscribe(click_id, click_token), {"status": "invalid"})
        self.assertEqual(self.service.one_click_unsubscribe(*self.link_parts(confirmation["url"])), {"status": "invalid"})
        self.assertEqual(self.service.confirm(click_id, click_token), {"status": "invalid_or_expired"})
        self.assertEqual(self.service.one_click_unsubscribe(click_id, click_token), {"status": "unsubscribed"})
        self.assertEqual(self.service.one_click_unsubscribe(click_id, click_token), {"status": "unsubscribed"})
        self.assertFalse(self.service.is_delivery_allowed("reader@example.org", ["internal@example.org"]))

    def test_eligibility_state_failures_block_external_but_fixed_internal_has_priority(self):
        with patch.object(self.store, "load", side_effect=StateError("Offline unavailable")):
            with self.assertRaises(StateError):
                self.service.is_delivery_allowed("reader@example.org", ["internal@example.org"])
            self.assertTrue(self.service.is_delivery_allowed("INTERNAL@example.org", ["internal@example.org"]))

    def test_confirmation_delivery_status_is_readonly_safe_and_distinguishes_queue_from_acceptance(self):
        self.service.request_signup("reader@example.org")
        with patch.object(self.store, "save") as save:
            queued = self.service.confirmation_delivery_status("READER@example.org")
            self.assertEqual(queued["subscriber_status"], "pending")
            self.assertEqual(queued["mail_status"], "queued")
            self.assertEqual(self.service.confirmation_delivery_status("missing@example.org"), {"status": "not_found"})
            save.assert_not_called()
        identifier = self.service.pending_confirmations()[0]["id"]
        claim = self.service.claim_confirmation(identifier)
        self.assertEqual(self.service.confirmation_delivery_status("reader@example.org")["mail_status"], "reserved")
        self.service.mark_confirmation(identifier, "accepted", reservation_id=claim["reservation_id"], stage="data", smtp_code=250)
        result = self.service.confirmation_delivery_status("reader@example.org")
        self.assertEqual((result["subscriber_status"], result["mail_status"], result["smtp_code"], result["stage"]),
                         ("pending", "accepted", 250, "data"))
        self.assertEqual(set(result), {"subscriber_status", "mail_status", "requested_at", "expires_at", "reserved_at", "completed_at", "smtp_code", "stage"})
        for sensitive in ("reader@example.org", identifier, claim["url"], claim["reservation_id"]):
            self.assertNotIn(sensitive, json.dumps(result))

    def test_confirm_ttl_and_explicit_resubscribe_do_not_revive_old_token(self):
        claimed = self.claim()
        self.service.mark_confirmation(claimed["id"], "accepted", reservation_id=claimed["reservation_id"])
        identifier, token = self.link_parts(claimed["url"])
        self.now += timedelta(hours=48)
        self.assertEqual(self.service.confirm(identifier, token), {"status": "invalid_or_expired"})
        self.assertEqual(self.service.pending_confirmations(), [])
        self.assertTrue(self.service.request_signup("reader@example.org")["queued"])
        self.assertEqual(self.service.confirm(identifier, token), {"status": "invalid_or_expired"})
        new_claim = self.service.claim_confirmation(identifier)
        new_id, new_token = self.link_parts(new_claim["url"])
        self.assertNotEqual(new_token, token)
        self.assertEqual(self.service.confirm(new_id, new_token), {"status": "confirmed"})

    def test_explicit_resubscribe_keeps_old_optout_until_fresh_confirmation(self):
        old = self.confirm_reader()
        self.service.unsubscribe(*self.link_parts(self.service.unsubscribe_url("reader@example.org")))
        self.now += timedelta(hours=1)
        self.assertTrue(self.service.request_signup("reader@example.org")["queued"])
        self.assertEqual(self.service.delivery_recipients(["reader@example.org"], ["internal@example.org"]), ["internal@example.org"])
        self.assertEqual(self.service.confirm(*self.link_parts(old["url"])), {"status": "invalid_or_expired"})
        claimed = self.service.claim_confirmation(old["id"])
        self.service.mark_confirmation(claimed["id"], "accepted", reservation_id=claimed["reservation_id"])
        self.assertEqual(self.service.confirm(*self.link_parts(claimed["url"])), {"status": "confirmed"})
        self.assertEqual(self.service.delivery_recipients(["reader@example.org"], ["internal@example.org"]),
                         ["internal@example.org", "reader@example.org"])

    def test_rate_limits_have_generic_public_status_and_no_client_plaintext(self):
        first = self.service.request_signup("reader@example.org", client_id="client-marker")
        again = self.service.request_signup("READER@example.org", client_id="client-marker")
        self.assertEqual(first["status"], again["status"])
        self.assertFalse(again["queued"])
        for index in range(4):
            self.assertTrue(self.service.request_signup(f"reader{index}@example.org", client_id="client-marker")["queued"])
        self.assertFalse(self.service.request_signup("limited@example.org", client_id="client-marker")["queued"])
        self.assertNotIn("client-marker", json.dumps(self.store.load(REGISTRY_PATH)))
        self.now += timedelta(hours=1)
        self.assertTrue(self.service.request_signup("reader@example.org", client_id="client-marker")["queued"])

    def test_global_daily_registry_and_confirmed_limits_are_enforced(self):
        for index in range(50):
            self.assertTrue(self.service.request_signup(f"reader{index}@example.org")["queued"])
        self.assertEqual(self.service.request_signup("overflow@example.org"), {"status": "check_email", "queued": False})
        registry = self.store.load(REGISTRY_PATH)
        for record in registry["records"].values():
            record.update(status="confirmed", confirmed_at=self.now.isoformat())
        for index in range(40):
            record = self.service._new_record(f"confirmed{index}@example.org", self.now, status="confirmed")
            record["confirmed_at"] = self.now.isoformat()
            registry["records"][record["id"]] = record
        self.store.save(REGISTRY_PATH, registry)
        self.now += timedelta(days=1)
        claimed = self.claim("last-reader@example.org")
        self.assertEqual(self.service.confirm(*self.link_parts(claimed["url"])), {"status": "invalid_or_expired"})
        registry = self.store.load(REGISTRY_PATH)
        for index in range(200 - len(registry["records"])):
            record = self.service._new_record(f"seed{index}@example.org", self.now, status="seeded")
            registry["records"][record["id"]] = record
        self.store.save(REGISTRY_PATH, registry)
        self.assertEqual(len(self.service.list_subscribers()), 200)
        self.assertFalse(self.service.request_signup("capacity@example.org")["queued"])

    def test_final_delivery_limit_and_casefold_deduplication(self):
        subscribers = [f"reader{index}@example.org" for index in range(99)]
        result = self.service.delivery_recipients(subscribers, ["internal@example.org", "READER0@EXAMPLE.ORG"])
        self.assertEqual(len(result), 100)
        self.assertEqual(result[:2], ["internal@example.org", "reader0@example.org"])
        with self.assertRaises(SubscriptionError):
            self.service.delivery_recipients(subscribers, ["internal@example.org", "other-internal@example.org"])

    def test_expired_public_pending_capacity_is_reclaimed_but_protected_records_remain(self):
        registry = self.service._load()
        protected = []
        expired_id = None
        old = self.now - timedelta(days=3)
        for index in range(200):
            record = self.service._new_record(f"old{index}@example.org", old, status="pending")
            record["confirmation"] = {"nonce": secrets.token_urlsafe(18), "status": "queued",
                                      "requested_at": old.isoformat(), "expires_at": (old + timedelta(hours=48)).isoformat()}
            if index in (0, 1):
                record["confirmation"].update(status="reserved" if index == 0 else "uncertain",
                                              reservation_id=secrets.token_urlsafe(18))
            elif index == 2:
                record["legacy_authorized"] = True
            elif index in (3, 4):
                record["status"] = "unsubscribed" if index == 3 else "suppressed"
            elif index == 5:
                record["opted_out"] = True
            if index < 6:
                protected.append(record["id"])
            if index == 6:
                expired_id = record["id"]
            registry["records"][record["id"]] = record
        self.store.save(REGISTRY_PATH, registry)
        self.assertTrue(self.service.request_signup("fresh@example.org")["queued"])
        current = self.store.load(REGISTRY_PATH)["records"]
        self.assertEqual(len(current), 7)
        self.assertTrue(all(identifier in current for identifier in protected))
        self.assertNotIn(expired_id, current)
        self.assertEqual(len(self.service.pending_confirmations()), 1)

    def test_cas_conflicts_retry_bounded_and_reservations_never_reclaim(self):
        original = self.store.save
        attempts = []
        def conflict_twice(path, value):
            attempts.append(path)
            if len(attempts) < 3:
                raise StateConflict("offline conflict")
            original(path, value)
        with patch.object(self.store, "save", side_effect=conflict_twice):
            self.assertTrue(self.service.request_signup("reader@example.org")["queued"])
        self.assertEqual(len(attempts), 3)
        row = self.service.pending_confirmations()[0]
        claimed = self.service.claim_confirmation(row["id"])
        self.assertIsNone(self.service.claim_confirmation(row["id"]))
        self.service.mark_confirmation(row["id"], "uncertain", reservation_id=claimed["reservation_id"])
        self.now += timedelta(days=1)
        self.assertFalse(self.service.request_signup("reader@example.org")["queued"])
        self.assertEqual(self.service.pending_confirmations(), [])
        with patch.object(self.store, "save", side_effect=StateConflict("offline conflict")) as saved:
            with self.assertRaises(StateConflict):
                self.service.request_signup("other@example.org")
        self.assertEqual(saved.call_count, 3)

    def test_approved_custom_domain_is_the_only_non_hf_space_base_url_and_signs_links_on_it(self):
        self.assertEqual(validate_public_base_url("https://daily.levyquant.ai"), "https://daily.levyquant.ai")
        self.assertEqual(validate_public_base_url("https://daily.levyquant.ai/"), "https://daily.levyquant.ai")
        for base in ("http://daily.levyquant.ai", "https://evil.daily.levyquant.ai", "https://daily.levyquant.ai.evil.example",
                     "https://levyquant.ai", "https://daily.levyquant.ai:443", "https://daily.levyquant.ai/path",
                     "https://user@daily.levyquant.ai", "https://daily.levyquant.ai?x=1"):
            with self.subTest(base=base), self.assertRaises(SubscriptionError):
                validate_public_base_url(base)
        service = SubscriptionService(self.store, KEY, "https://daily.levyquant.ai", now=lambda: self.now)
        service.delivery_recipients(["reader@example.org"], ["internal@example.org"])
        for url in (service.unsubscribe_url("reader@example.org"), service.one_click_unsubscribe_url("reader@example.org")):
            self.assertTrue(url.startswith("https://daily.levyquant.ai/"), url)
        # The one-click URL passes the strict SMTP header check on the custom domain too.
        prepare_message("Subject", "<p>x</p>", "x", "sender@example.com", "reader@example.org", "edition-1",
                        unsubscribe_url=service.one_click_unsubscribe_url("reader@example.org"))

    def test_queued_mail_uses_ses_when_switched_on_and_never_falls_back_to_gmail(self):
        environment = {"SUBSCRIPTIONS_ENABLED": "true", "GITHUB_REPOSITORY": REPOSITORY, "GITHUB_TOKEN": "offline",
                       "STATE_ENCRYPTION_KEY": "offline", "SMTP_USERNAME": "operator@example.org",
                       "MAIL_TRANSPORT": "ses", "MAIL_FROM_ADDRESS": "briefing@levyquant.ai",
                       "SES_SMTP_HOST": "email-smtp.us-east-1.amazonaws.com",
                       "SES_SMTP_USERNAME": "AKIAEXAMPLEOFFLINE01", "SES_SMTP_PASSWORD": "offline-ses-secret"}
        self.service.request_signup("reader@example.org")
        with patch("levyquant.subscription_mail.send_with", return_value={"status": "accepted"}) as ses, \
                patch("levyquant.subscription_mail.send_one") as gmail:
            result = subscription_mail.run(environment, service=self.service)
        self.assertEqual(result["accepted"], 1)
        gmail.assert_not_called()
        message, settings = ses.call_args.args
        self.assertEqual((message["From"].addresses[0].addr_spec, settings.transport), ("briefing@levyquant.ai", "ses"))
        self.assertIn("briefing@levyquant.ai", message.get_body(preferencelist=("plain",)).get_content())
        broken = {**environment, "SES_SMTP_PASSWORD": "", "SMTP_APP_PASSWORD": "gmail-would-work"}
        with patch("levyquant.subscription_mail.send_one") as gmail, self.assertRaises(SubscriptionError):
            subscription_mail.run(broken, service=self.service)
        gmail.assert_not_called()

    def test_production_worker_fails_loudly_on_partial_ses_settings_even_when_signup_is_off(self):
        environment = {"GITHUB_REPOSITORY": REPOSITORY, "GITHUB_TOKEN": "offline", "STATE_ENCRYPTION_KEY": "offline",
                       "SMTP_USERNAME": "operator@example.org", "SMTP_APP_PASSWORD": "gmail-would-work",
                       "MAIL_TRANSPORT": "ses", "MAIL_FROM_ADDRESS": "briefing@levyquant.ai",
                       "SES_SMTP_HOST": "email-smtp.us-east-1.amazonaws.com", "SES_SMTP_USERNAME": "AKIAEXAMPLEOFFLINE01"}
        with patch("levyquant.subscription_mail.service_from_env") as subscriptions, \
                patch("levyquant.subscription_mail.admin_service_from_env") as admins, \
                patch("levyquant.subscription_mail.send_one") as gmail, self.assertRaises(SubscriptionError):
            subscription_mail.run(environment)
        subscriptions.assert_not_called(); admins.assert_not_called(); gmail.assert_not_called()

    def test_invalid_email_base_url_repository_and_corrupt_state_fail_closed(self):
        for email in ("Name <reader@example.org>", "reader@example.org\r\nBcc: x@example.org", ".reader@example.org", "a..b@example.org", "reader@-example.org", "reader@example.org,second@example.org"):
            with self.subTest(email=email), self.assertRaises(SubscriptionError):
                validate_email(email)
        for base in ("http://example-digest.hf.space", "https://other.example.org", "https://x.hf.space@evil.example.org", "https://x.hf.space/path", "https://x.hf.space:443"):
            with self.subTest(base=base), self.assertRaises(SubscriptionError):
                SubscriptionService(self.store, KEY, base)
        with patch("levyquant.subscriptions.GitHubStateStore") as remote:
            with self.assertRaises(SubscriptionError):
                service_from_env({"GITHUB_REPOSITORY": "other/repository"})
            remote.assert_not_called()
        self.store.load(REGISTRY_PATH)
        self.store.save(REGISTRY_PATH, {"schema_version": 1, "records": [], "limits": {}})
        with self.assertRaises(StateError):
            self.service.list_subscribers()


class ConfirmationWorkerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = LocalStateStore(Path(temporary.name))
        self.service = SubscriptionService(self.store, KEY, BASE, now=NOW)
        self.environment = {"SUBSCRIPTIONS_ENABLED": "true", "GITHUB_REPOSITORY": REPOSITORY,
                            "SMTP_USERNAME": "sender@example.org", "SMTP_APP_PASSWORD": "offline-password"}
        self.service.request_signup("reader@example.org")

    def test_claim_is_durable_before_smtp_and_accepted_is_not_resent(self):
        def transport(message, **kwargs):
            record = next(iter(self.store.load(REGISTRY_PATH)["records"].values()))
            self.assertEqual(record["confirmation"]["status"], "reserved")
            self.assertIsNone(self.service.claim_confirmation(record["id"]))
            self.assertEqual(str(message["To"]), "reader@example.org")
            self.assertIn("No subscription will start unless you confirm.", message.get_body(preferencelist=("plain",)).get_content())
            return {"status": "accepted", "smtp_code": 250}
        result = subscription_mail.run(self.environment, service=self.service, transport=transport)
        self.assertEqual(result["accepted"], 1)
        self.assertEqual(self.service.list_subscribers()[0]["status"], "pending")
        repeat = Mock()
        self.assertEqual(subscription_mail.run(self.environment, service=self.service, transport=repeat)["accepted"], 0)
        repeat.assert_not_called()

    def test_confirmation_copy_explains_identity_and_choice_in_both_formats(self):
        self.environment["SMTP_USERNAME"] = "sender&briefing@example.org"
        messages = []

        def transport(message, **kwargs):
            messages.append(message)
            return {"status": "accepted", "smtp_code": 250}

        result = subscription_mail.run(self.environment, service=self.service, transport=transport)
        self.assertEqual(result["accepted"], 1)
        self.assertEqual(len(messages), 1)
        message = messages[0]
        self.assertEqual(str(message["Subject"]), "Confirm your LévyQuant subscription")
        plain = message.get_body(preferencelist=("plain",)).get_content()
        html = message.get_body(preferencelist=("html",)).get_content()

        class ConfirmationParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.links, self.text, self.actions = [], [], []

            def handle_starttag(self, tag, attributes):
                if tag == "a":
                    self.links.append(dict(attributes).get("href"))
                if tag in ("form", "input", "script", "iframe"):
                    self.actions.append(tag)

            def handle_data(self, data):
                self.text.append(data)

        parsed = ConfirmationParser()
        parsed.feed(html)
        visible_html = " ".join(parsed.text)
        for sentence in (
            "This email address was entered on the LévyQuant subscription page.",
            "LévyQuant sends a morning briefing on macroeconomics, U.S. equities and quantitative research, around 7 a.m. New York time.",
            "To subscribe, open the page below and select Confirm.",
            "Review and confirm subscription",
            "This link expires 48 hours after the request.",
            "If you did not request this, ignore this email.",
            "No subscription will start unless you confirm.",
            "LévyQuant · sender&briefing@example.org",
        ):
            with self.subTest(sentence=sentence):
                self.assertIn(sentence, plain)
                self.assertIn(sentence, visible_html)
        self.assertEqual(parsed.actions, [])
        self.assertEqual(len(parsed.links), 1)
        confirmation_url = parsed.links[0]
        self.assertEqual(urlsplit(confirmation_url).path, "/confirm")
        self.assertEqual(plain.count(confirmation_url), 1)
        self.assertEqual(html.count('href="'), 1)
        self.assertIn("sender&amp;briefing@example.org", html)
        self.assertNotIn("sender&briefing@example.org", html)
        self.assertEqual(self.service.list_subscribers()[0]["status"], "pending")

    def test_uncertain_and_crash_reservations_cannot_be_automatically_replayed(self):
        uncertain = Mock(side_effect=DeliveryUncertain("private details", stage="data"))
        result = subscription_mail.run(self.environment, service=self.service, transport=uncertain)
        self.assertEqual(result["uncertain"], 1)
        repeat = Mock()
        subscription_mail.run(self.environment, service=self.service, transport=repeat)
        repeat.assert_not_called()
        self.service.request_signup("other@example.org")
        crash = Mock(side_effect=RuntimeError("private details"))
        with self.assertRaises(RuntimeError):
            subscription_mail.run(self.environment, service=self.service, transport=crash)
        subscription_mail.run(self.environment, service=self.service, transport=repeat)
        repeat.assert_not_called()

    def test_claim_failure_or_wrong_link_never_reaches_smtp(self):
        transport = Mock()
        with patch.object(self.service, "claim_confirmation", side_effect=StateError("not acknowledged")):
            with self.assertRaises(StateError):
                subscription_mail.run(self.environment, service=self.service, transport=transport)
        with patch.object(self.service, "claim_confirmation", return_value={"id": "x", "email": "reader@example.org", "reservation_id": "claim", "url": "https://evil.example.org/confirm?id=x&token=x"}):
            with self.assertRaises(SubscriptionError):
                subscription_mail.run(self.environment, service=self.service, transport=transport)
        transport.assert_not_called()

    def test_disabled_worker_and_error_stdout_expose_no_private_values(self):
        with patch("levyquant.subscription_mail.service_from_env") as factory, patch("levyquant.subscription_mail.send_one") as smtp:
            self.assertEqual(subscription_mail.run({})["status"], "disabled")
            factory.assert_not_called()
            smtp.assert_not_called()
        output = StringIO()
        with patch("levyquant.subscription_mail.run", side_effect=RuntimeError("reader@example.org private-token https://private.example.org")), redirect_stdout(output):
            self.assertEqual(subscription_mail.main(), 1)
        self.assertEqual(json.loads(output.getvalue()), {"status": "failed", "error_type": "RuntimeError"})


if __name__ == "__main__":
    unittest.main()
