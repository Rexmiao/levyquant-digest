"""Single-recipient Gmail SMTP delivery, with explicit uncertain outcomes.

The caller supplies a password obtained from its environment secret store. This
module never reads n8n credentials, environment variables, or subscriber files.
An accepted SMTP response means the relay accepted the message, not that it has
arrived in an inbox. No operation retries a message once its data may have been
handed over; SMTPSession only reopens a dropped, reused connection before DATA.
"""

from __future__ import annotations

from email import policy
from email.message import EmailMessage
from email.utils import formataddr, formatdate, getaddresses
import hashlib
import re
import smtplib
import ssl
from urllib.parse import parse_qs, urlsplit


SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465
SMTP_TIMEOUT_SECONDS = 45
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
# Hosts allowed in emailed confirm/unsubscribe links and DIGEST_PUBLIC_BASE_URL:
# the Space's own *.hf.space host, or an exact custom domain attached to it.
# Kept as an explicit allowlist because these links carry signed tokens.
PUBLIC_CUSTOM_HOSTS = frozenset({"daily.levyquant.ai"})
_HF_SPACE_HOST = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.hf\.space")


def is_public_site_host(hostname: str) -> bool:
    return isinstance(hostname, str) and (hostname in PUBLIC_CUSTOM_HOSTS
                                          or _HF_SPACE_HOST.fullmatch(hostname) is not None)
_ADDRESS = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\Z")


class DeliveryError(RuntimeError):
    """A known failure: the SMTP relay has not accepted this message.

    retry_safe only means a retry would not duplicate an accepted submission;
    it does not mean the failure is transient or that retrying would succeed.
    """

    uncertain = False
    retry_safe = True

    def __init__(
        self,
        description: str,
        *,
        stage: str,
        smtp_code: int | None = None,
        recipient: str = "",
        message_id: str = "",
    ) -> None:
        super().__init__(description)
        self.stage = stage
        self.smtp_code = smtp_code
        self.recipient = recipient
        self.message_id = message_id


class DeliveryUncertain(DeliveryError):
    """The connection failed during DATA; the relay may have accepted it.

    Persist this outcome and investigate before another delivery attempt. A
    deterministic Message-ID helps reconciliation but is not a deduplication
    guarantee supplied by Gmail.
    """

    uncertain = True
    retry_safe = False


def _header(value: str, label: str) -> str:
    if not isinstance(value, str) or _CONTROL.search(value):
        raise DeliveryError(f"{label} contains invalid header text.", stage="validation")
    return value


def _address(value: str, label: str) -> str:
    value = _header(value, label).strip()
    if len(value) > 254 or not _ADDRESS.fullmatch(value):
        raise DeliveryError(f"{label} must be one plain email address.", stage="validation")
    local, domain = value.rsplit("@", 1)
    if local.startswith(".") or local.endswith(".") or ".." in value:
        raise DeliveryError(f"{label} is invalid.", stage="validation")
    if any(not part or part.startswith("-") or part.endswith("-") for part in domain.split(".")):
        raise DeliveryError(f"{label} is invalid.", stage="validation")
    return value.lower()


def _edition(value: str) -> str:
    value = _header(value, "Edition ID").strip()
    if not value or len(value) > 256:
        raise DeliveryError("Edition ID must contain 1 to 256 characters.", stage="validation")
    return value


def _message_id(edition_id: str, recipient: str, sender: str) -> str:
    key = f"levyquant\x00{edition_id}\x00{recipient}".encode("utf-8")
    digest = hashlib.sha256(key).hexdigest()
    domain = sender.rsplit("@", 1)[1]
    return f"<levyquant.{digest}@{domain}>"


def prepare_message(
    subject: str,
    html: str,
    text: str,
    sender: str,
    recipient: str,
    edition_id: str,
    *, unsubscribe_url: str | None = None,
) -> EmailMessage:
    """Build one UTF-8 email; sender and recipient are bare email addresses.

    Pass the sender address configured in the SMTP_USERNAME repository secret.
    Subject and edition are supplied by the caller, never treated as commands.
    The Message-ID is deterministic for an edition and normalized recipient.
    """
    subject = _header(subject, "Subject")
    sender = _address(sender, "Sender")
    recipient = _address(recipient, "Recipient")
    edition_id = _edition(edition_id)
    if not subject.strip():
        raise DeliveryError("Subject cannot be empty.", stage="validation")
    if not isinstance(text, str) or not isinstance(html, str):
        raise DeliveryError("Text and HTML bodies must be strings.", stage="validation")
    message = EmailMessage(policy=policy.SMTP)
    message["From"] = formataddr(("LévyQuant", sender))
    message["To"] = recipient
    message["Subject"] = subject
    message["Date"] = formatdate(localtime=False)
    message["Message-ID"] = _message_id(edition_id, recipient, sender)
    message["X-LevyQuant-Edition"] = edition_id
    if unsubscribe_url is not None:
        unsubscribe_url = _one_click_url(unsubscribe_url)
        message["List-Unsubscribe"] = "<" + unsubscribe_url + ">"
        message["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    # Keep the wire data 7-bit clean even when the original titles are Chinese.
    message.set_content(text, charset="utf-8", cte="quoted-printable")
    message.add_alternative(html, subtype="html", charset="utf-8", cte="quoted-printable")
    if unsubscribe_url is not None:
        # Keep the ASCII URL literal rather than RFC 2047 encoded words. Body
        # transfer encoding was already generated with ordinary SMTP policy.
        message.policy = policy.SMTP.clone(max_line_length=998)
    return message


def _one_click_url(value: str) -> str:
    value = _header(value, "Unsubscribe URL")
    try:
        parsed = urlsplit(value)
        parameters = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
        valid = (len(value) <= 500 and parsed.scheme == "https" and parsed.username is None and parsed.password is None
                 and parsed.port is None and parsed.netloc == parsed.hostname
                 and is_public_site_host(parsed.hostname or "")
                 and parsed.path == "/one-click-unsubscribe" and not parsed.fragment
                 and set(parameters) == {"id", "token"}
                 and len(parameters["id"]) == len(parameters["token"]) == 1
                 and re.fullmatch(r"[A-Za-z0-9_-]{24}", parameters["id"][0])
                 and re.fullmatch(r"[A-Za-z0-9_-]{43}", parameters["token"][0]))
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise DeliveryError("A valid fixed-site one-click unsubscribe URL is required.", stage="validation")
    return value


def _single_address(message: EmailMessage, field: str) -> str:
    values = message.get_all(field, [])
    if len(values) != 1:
        raise DeliveryError(f"Exactly one {field} header is required.", stage="validation")
    value = _header(str(values[0]), field)
    parsed = getaddresses([value])
    if len(parsed) != 1:
        raise DeliveryError(f"Exactly one {field} address is required.", stage="validation")
    return _address(parsed[0][1], field)


def _envelope(message: EmailMessage, username: str) -> tuple[str, str, str, bytes]:
    if not isinstance(message, EmailMessage):
        raise DeliveryError("Use prepare_message to create the message.", stage="validation")
    for name, value in message.raw_items():
        _header(name, "Header name")
        _header(str(value), name)
    if message.get_all("Bcc") or message.get_all("Cc") or any(name.lower().startswith("resent-") for name in message.keys()):
        raise DeliveryError("Single-recipient delivery does not allow Cc, Bcc, or Resent headers.", stage="validation")
    for field in ("Subject", "Message-ID", "X-LevyQuant-Edition"):
        if len(message.get_all(field, [])) != 1:
            raise DeliveryError(f"Exactly one {field} header is required.", stage="validation")
    _header(str(message["Subject"]), "Subject")
    sender = _single_address(message, "From")
    recipient = _single_address(message, "To")
    if sender != username:
        raise DeliveryError("SMTP username must match the message's From address.", stage="validation")
    edition_id = _edition(str(message["X-LevyQuant-Edition"]))
    message_id = str(message["Message-ID"])
    if message_id != _message_id(edition_id, recipient, sender):
        raise DeliveryError("Message-ID does not match the edition and recipient.", stage="validation")
    wire_policy = policy.SMTP.clone(max_line_length=998) if message.get("List-Unsubscribe") is not None else policy.SMTP
    return sender, recipient, message_id, message.as_bytes(policy=wire_policy)


def _validated_password(password) -> str:
    if not isinstance(password, str) or not password.strip() or _CONTROL.search(password):
        raise DeliveryError("A non-empty SMTP application password is required.", stage="validation")
    return password


def _open_client():
    return smtplib.SMTP_SSL(
        SMTP_HOST,
        SMTP_PORT,
        context=ssl.create_default_context(),
        timeout=SMTP_TIMEOUT_SECONDS,
    )


class _StaleConnection(Exception):
    """A reused connection dropped before any message data was handed over."""


class SMTPSession:
    """Reuse one verified TLS login for several single-recipient submissions.

    Every message is still its own MAIL/RCPT/DATA transaction with one
    recipient. The connection is closed after any failure, and replaced after
    MAX_MESSAGES_PER_CONNECTION accepted messages, so no broken or long-lived
    transaction state carries over to the next recipient.

    A reused connection that drops before DATA starts (for example an idle
    timeout on the relay) is reopened once for that message: nothing was handed
    over, so this cannot duplicate a submission. Any failure during or after
    DATA is never retried and keeps the DeliveryUncertain contract.
    """

    MAX_MESSAGES_PER_CONNECTION = 20

    def __init__(self, username: str, password: str) -> None:
        self.username = _address(username, "SMTP username")
        self._password = _validated_password(password)
        self._client = None
        self._sent_on_connection = 0
        self.connections_opened = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()
        return False

    def close(self) -> None:
        client, self._client, self._sent_on_connection = self._client, None, 0
        if client is not None:
            try:
                # Do not let a failed QUIT turn an acknowledged delivery into an
                # apparent failure. Closing requires no additional SMTP exchange.
                client.close()
            except Exception:
                pass

    def send(self, message: EmailMessage, *, username: str | None = None, password: str | None = None) -> dict:
        """Same contract as send_one; username/password, if given, must match the session."""
        if username is not None and _address(username, "SMTP username") != self.username:
            raise DeliveryError("SMTP username must match the session account.", stage="validation")
        if password is not None and _validated_password(password) != self._password:
            raise DeliveryError("SMTP password must match the session account.", stage="validation")
        sender, recipient, message_id, wire = _envelope(message, self.username)
        try:
            return self._transact(sender, recipient, message_id, wire)
        except _StaleConnection:
            self.close()
            return self._transact(sender, recipient, message_id, wire, allow_stale_retry=False)

    def _transact(self, sender, recipient, message_id, wire, *, allow_stale_retry=True) -> dict:
        stage = "connect"
        reused = False
        try:
            if self._client is not None and self._sent_on_connection >= self.MAX_MESSAGES_PER_CONNECTION:
                self.close()
            if self._client is None:
                self._client = _open_client()
                self.connections_opened += 1
                stage = "greeting"
                self._client.ehlo_or_helo_if_needed()
                stage = "auth"
                self._client.login(self.username, self._password)
            else:
                reused = True
            client = self._client
            stage = "mail"
            code, _ = client.mail(sender)
            if code != 250:
                raise DeliveryError(
                    "SMTP rejected the envelope sender.", stage=stage, smtp_code=code,
                    recipient=recipient, message_id=message_id,
                )
            stage = "recipient"
            code, _ = client.rcpt(recipient)
            if code not in (250, 251):
                raise DeliveryError(
                    "SMTP rejected the recipient.", stage=stage, smtp_code=code,
                    recipient=recipient, message_id=message_id,
                )
            stage = "data"
            code, _ = client.data(wire)
            if code == 250:
                self._sent_on_connection += 1
                return {"status": "accepted", "recipient": recipient, "message_id": message_id, "smtp_code": 250}
            if 400 <= code <= 599:
                raise DeliveryError(
                    "SMTP rejected the message data.", stage=stage, smtp_code=code,
                    recipient=recipient, message_id=message_id,
                )
            raise DeliveryUncertain(
                "SMTP returned an unexpected DATA acknowledgement; do not retry without checking delivery.",
                stage=stage, smtp_code=code, recipient=recipient, message_id=message_id,
            )
        except DeliveryError:
            self.close()
            raise
        except smtplib.SMTPResponseException as exc:
            self.close()
            # A 4xx/5xx response is an explicit refusal, including a DATA rejection.
            # Never expose the raw provider response: it may contain a credential.
            error = DeliveryUncertain if stage == "data" and not 400 <= exc.smtp_code <= 599 else DeliveryError
            raise error(
                "SMTP explicitly refused the request." if error is DeliveryError else
                "SMTP DATA outcome is uncertain; do not retry without checking delivery.",
                stage=stage, smtp_code=exc.smtp_code, recipient=recipient, message_id=message_id,
            ) from None
        except Exception as exc:
            self.close()
            if (allow_stale_retry and reused and stage in ("mail", "recipient")
                    and isinstance(exc, (smtplib.SMTPServerDisconnected, ConnectionError, TimeoutError))):
                raise _StaleConnection() from None
            error = DeliveryUncertain if stage == "data" else DeliveryError
            raise error(
                "SMTP connection failed before message data was submitted." if error is DeliveryError else
                "SMTP connection failed during DATA; delivery may have succeeded. Do not retry without checking.",
                stage=stage, recipient=recipient, message_id=message_id,
            ) from None


def send_one(message: EmailMessage, *, username: str, password: str) -> dict:
    """Submit one prepared email over verified TLS to smtp.gmail.com:465.

    Return status='accepted', recipient, message_id, and smtp_code=250 only after
    the relay's final DATA acknowledgement. Explicit SMTP rejections raise
    DeliveryError. A transport/protocol failure during DATA raises
    DeliveryUncertain, since the final acknowledgement may have been lost.
    Caller-supplied password is normally os.environ['GMAIL_APP_PASSWORD'].
    This opens and closes its own connection and never retries.
    """
    with SMTPSession(username, password) as session:
        return session.send(message)
