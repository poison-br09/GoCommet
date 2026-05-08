import asyncio
import re
import smtplib
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import make_msgid, parseaddr

from app.core.config import settings


def _smtp_username() -> str | None:
    return settings.smtp_username or settings.imap_username or settings.imap_user or settings.imap_email


def _smtp_password() -> str | None:
    if settings.smtp_password is not None:
        return settings.smtp_password.get_secret_value()
    if settings.imap_password is not None:
        return settings.imap_password.get_secret_value()
    return None


def _from_email() -> str | None:
    return settings.smtp_from_email or _smtp_username()


def smtp_is_configured() -> bool:
    return bool(settings.smtp_enabled and settings.smtp_host and _smtp_username() and _smtp_password() and _from_email())


def smtp_configuration_status() -> str:
    if not settings.smtp_enabled:
        return "SMTP_ENABLED is false"
    missing: list[str] = []
    if not settings.smtp_host:
        missing.append("SMTP_HOST")
    if not _smtp_username():
        missing.append("SMTP_USERNAME or IMAP_USERNAME")
    if not _smtp_password():
        missing.append("SMTP_PASSWORD or IMAP_PASSWORD")
    if not _from_email():
        missing.append("SMTP_FROM_EMAIL or SMTP_USERNAME")
    if missing:
        return "missing " + ", ".join(missing)
    return "configured"


def split_subject_and_body(default_subject: str, approved_text: str) -> tuple[str, str]:
    lines = approved_text.splitlines()
    if lines and lines[0].lower().startswith("subject:"):
        subject = lines[0].split(":", 1)[1].strip() or default_subject
        body = "\n".join(lines[1:]).lstrip()
        return subject, body
    return default_subject, approved_text


def normalize_recipient(raw_recipient: str | None) -> str:
    name, address = parseaddr(raw_recipient or "")
    if not address:
        raise ValueError("Cannot send email: inbound sender address is missing or invalid")
    if not re.search(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", address):
        raise ValueError(f"Cannot send email: invalid recipient address {address!r}")
    return f"{name} <{address}>" if name else address


def _send_smtp_message(to_address: str, subject: str, body: str) -> dict[str, str]:
    username = _smtp_username()
    password = _smtp_password()
    from_email = _from_email()
    if not username or not password or not from_email:
        raise RuntimeError("SMTP is enabled but username, password, or from address is missing")

    message_id = make_msgid(domain=from_email.split("@")[-1] if "@" in from_email else None)
    message = EmailMessage()
    message["From"] = from_email
    message["To"] = to_address
    message["Subject"] = subject
    message["Message-ID"] = message_id
    message.set_content(body)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
        if settings.smtp_use_tls:
            smtp.starttls()
        smtp.login(username, password)
        smtp.send_message(message)

    return {
        "status": "sent",
        "delivery": "smtp",
        "message_id": message_id,
        "sent_at": datetime.now(UTC).isoformat(),
    }


async def send_review_email(to_address: str, subject: str, body: str) -> dict[str, str]:
    return await asyncio.to_thread(_send_smtp_message, to_address, subject, body)
