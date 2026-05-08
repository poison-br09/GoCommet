import argparse
import email
import imaplib
import os
import re
from email.message import Message
from pathlib import Path
from typing import Iterable

import requests


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / "server" / ".env"
ATTACHMENTS_ROOT = Path(os.getenv("IMAP_ATTACHMENTS_DIR", "/tmp/gocomet_imap_attachments"))
SUPPORTED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".xls", ".xlsx"}


def load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None or value == "":
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def safe_filename(filename: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("._")
    return cleaned or "attachment"


def decode_header_value(value: str | None) -> str:
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


def iter_attachments(message: Message) -> Iterable[tuple[str, bytes]]:
    for part in message.walk():
        if part.is_multipart():
            continue
        disposition = part.get_content_disposition()
        filename = decode_header_value(part.get_filename())
        if disposition != "attachment" and not filename:
            continue
        if not filename:
            filename = "attachment"
        if Path(filename).suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        payload = part.get_payload(decode=True)
        if payload:
            yield safe_filename(filename), payload


def post_email_event(sender: str, subject: str, attachment_paths: list[Path]) -> None:
    api_base_url = os.getenv("API_BASE_URL", "http://localhost:8000")
    api_key = env("API_KEY")
    payload = {
        "sender": sender,
        "subject": subject or f"IMAP shipment documents - {len(attachment_paths)} attachment(s)",
        "attachment_paths": [str(path) for path in attachment_paths],
    }
    response = requests.post(
        f"{api_base_url}/api/v1/webhook/incoming-email",
        headers={"x-api-key": api_key},
        json=payload,
        timeout=30,
    )
    response.raise_for_status()
    print(f"Triggered pipeline: {response.json()}")


def process_unseen_once(mark_seen: bool) -> int:
    host = env("IMAP_HOST")
    port = int(os.getenv("IMAP_PORT", "993"))
    username = os.getenv("IMAP_USERNAME") or os.getenv("IMAP_USER") or os.getenv("IMAP_EMAIL")
    if not username:
        raise RuntimeError("Missing required environment variable: IMAP_USERNAME")
    password = env("IMAP_PASSWORD")
    folder = os.getenv("IMAP_FOLDER", "INBOX")
    search_criteria = os.getenv("IMAP_SEARCH_CRITERIA", "UNSEEN")

    processed = 0
    with imaplib.IMAP4_SSL(host, port) as mailbox:
        mailbox.login(username, password)
        mailbox.select(folder)

        status, data = mailbox.search(None, search_criteria)
        if status != "OK":
            raise RuntimeError(f"IMAP search failed with status {status}")

        message_ids = data[0].split()
        print(f"Found {len(message_ids)} message(s) matching {search_criteria!r}.")

        for message_id in message_ids:
            status, fetch_data = mailbox.fetch(message_id, "(RFC822)")
            if status != "OK" or not fetch_data:
                print(f"Skipping message {message_id!r}: fetch failed.")
                continue

            raw_message = fetch_data[0][1]
            message = email.message_from_bytes(raw_message)
            sender = decode_header_value(message.get("From"))
            subject = decode_header_value(message.get("Subject"))
            message_dir = ATTACHMENTS_ROOT / message_id.decode("ascii", errors="ignore")
            message_dir.mkdir(parents=True, exist_ok=True)

            attachment_paths: list[Path] = []
            for filename, payload in iter_attachments(message):
                path = message_dir / filename
                path.write_bytes(payload)
                attachment_paths.append(path)

            if not attachment_paths:
                print(f"Message {message_id.decode()} has no supported attachments; skipping.")
                continue

            print(f"Posting message {message_id.decode()} with {len(attachment_paths)} attachment(s).")
            post_email_event(sender, subject, attachment_paths)
            processed += 1

            if mark_seen:
                mailbox.store(message_id, "+FLAGS", "\\Seen")

    return processed


def main() -> None:
    load_env_file(ENV_PATH)
    parser = argparse.ArgumentParser(description="Trigger the pipeline from unseen IMAP emails.")
    parser.add_argument("--mark-seen", action="store_true", help="Mark processed messages as seen.")
    args = parser.parse_args()
    processed = process_unseen_once(mark_seen=args.mark_seen)
    print(f"Processed {processed} email(s).")


if __name__ == "__main__":
    main()
