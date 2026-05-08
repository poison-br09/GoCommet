import asyncio
import email
import imaplib
import os
import re
from email.message import Message
from pathlib import Path
from typing import Iterable

from app.core.config import settings
from app.core.logger import get_logger
from app.graph.workflow import create_graph_thread, run_email_pipeline_thread
from app.schemas.events import EmailPayload

log = get_logger(__name__)

SUPPORTED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".xls", ".xlsx"}


def _env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None or value == "":
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def imap_enabled() -> bool:
    return settings.imap_enabled


def _safe_filename(filename: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("._")
    return cleaned or "attachment"


def _decode_header_value(value: str | None) -> str:
    if not value:
        return ""
    decoded_parts = email.header.decode_header(value)
    chunks: list[str] = []
    for part, encoding in decoded_parts:
        if isinstance(part, bytes):
            chunks.append(part.decode(encoding or "utf-8", errors="replace"))
        else:
            chunks.append(part)
    return "".join(chunks)


def _iter_attachments(message: Message) -> Iterable[tuple[str, bytes]]:
    for part in message.walk():
        if part.is_multipart():
            continue
        disposition = part.get_content_disposition()
        filename = _decode_header_value(part.get_filename())
        if disposition != "attachment" and not filename:
            continue
        if not filename:
            filename = "attachment"
        if Path(filename).suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        payload = part.get_payload(decode=True)
        if payload:
            yield _safe_filename(filename), payload


def _fetch_unseen_payloads() -> list[EmailPayload]:
    host = settings.imap_host
    if not host:
        raise RuntimeError("Missing required environment variable: IMAP_HOST")
    port = settings.imap_port
    username = settings.imap_username or settings.imap_user or settings.imap_email
    if not username:
        raise RuntimeError("Missing required environment variable: IMAP_USERNAME")
    if settings.imap_password is None:
        raise RuntimeError("Missing required environment variable: IMAP_PASSWORD")
    password = settings.imap_password.get_secret_value()
    folder = settings.imap_folder
    search_criteria = settings.imap_search_criteria
    mark_seen = settings.imap_mark_seen
    attachments_root = Path(settings.imap_attachments_dir)

    payloads: list[EmailPayload] = []
    with imaplib.IMAP4_SSL(host, port) as mailbox:
        mailbox.login(username, password)
        mailbox.select(folder)

        status, data = mailbox.search(None, search_criteria)
        if status != "OK":
            raise RuntimeError(f"IMAP search failed with status {status}")

        message_ids = data[0].split()
        if message_ids:
            log.info("IMAP worker found %d message(s) matching %r", len(message_ids), search_criteria)

        for message_id in message_ids:
            status, fetch_data = mailbox.fetch(message_id, "(RFC822)")
            if status != "OK" or not fetch_data:
                log.warning("IMAP worker skipping message %r: fetch failed", message_id)
                continue

            raw_message = fetch_data[0][1]
            message = email.message_from_bytes(raw_message)
            sender = _decode_header_value(message.get("From"))
            subject = _decode_header_value(message.get("Subject"))
            message_dir = attachments_root / message_id.decode("ascii", errors="ignore")
            message_dir.mkdir(parents=True, exist_ok=True)

            attachment_paths: list[str] = []
            for filename, payload in _iter_attachments(message):
                path = message_dir / filename
                path.write_bytes(payload)
                attachment_paths.append(str(path))

            if not attachment_paths:
                log.info("IMAP worker message %s has no supported attachments; skipping", message_id.decode())
                continue

            payloads.append(EmailPayload(
                sender=sender,
                subject=subject or f"IMAP shipment documents - {len(attachment_paths)} attachment(s)",
                attachment_paths=attachment_paths,
            ))

            if mark_seen:
                mailbox.store(message_id, "+FLAGS", "\\Seen")

    return payloads


async def _trigger_payload(payload: EmailPayload) -> str:
    thread_id = await create_graph_thread(payload)
    asyncio.create_task(run_email_pipeline_thread(thread_id, payload))
    return thread_id


async def run_imap_worker(stop_event: asyncio.Event) -> None:
    interval_seconds = settings.imap_poll_interval_seconds
    log.info(
        "IMAP worker started  |  interval=%ss  folder=%s  search=%s",
        interval_seconds,
        settings.imap_folder,
        settings.imap_search_criteria,
    )

    while not stop_event.is_set():
        try:
            payloads = await asyncio.to_thread(_fetch_unseen_payloads)
            for payload in payloads:
                thread_id = await _trigger_payload(payload)
                log.info(
                    "IMAP worker triggered pipeline  |  thread_id=%s  subject=%r  attachments=%d",
                    thread_id,
                    payload.subject,
                    len(payload.attachment_paths),
                )
        except Exception as exc:
            log.exception("IMAP worker poll failed: %s", exc)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except asyncio.TimeoutError:
            continue

    log.info("IMAP worker stopped")
