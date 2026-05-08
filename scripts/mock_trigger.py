import os
import sys
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
API_KEY = os.getenv("API_KEY", "your_secret_api_key")
ATTACHMENTS_DIR = Path(os.getenv("ATTACHMENTS_DIR", ROOT))
SUPPORTED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".xls", ".xlsx"}


def discover_attachments() -> list[Path]:
    return sorted(
        path
        for path in ATTACHMENTS_DIR.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    )


def select_attachments(candidates: list[Path]) -> list[Path]:
    print("Available attachments:")
    for index, path in enumerate(candidates, start=1):
        print(f"  {index}. {path.name}")

    raw_selection = input(
        "\nSelect file numbers separated by commas, ranges like 1-3, or press Enter for all: "
    ).strip()
    if not raw_selection:
        return candidates

    selected_indexes: set[int] = set()
    for part in raw_selection.split(","):
        token = part.strip()
        if not token:
            continue
        if "-" in token:
            start_text, end_text = token.split("-", 1)
            start = int(start_text)
            end = int(end_text)
            selected_indexes.update(range(start, end + 1))
        else:
            selected_indexes.add(int(token))

    selected = [
        candidates[index - 1]
        for index in sorted(selected_indexes)
        if 1 <= index <= len(candidates)
    ]
    if not selected:
        raise ValueError("No valid files selected.")
    return selected


def main() -> None:
    if len(sys.argv) > 1:
        attachments = [Path(arg).expanduser().resolve() for arg in sys.argv[1:]]
        missing = [str(path) for path in attachments if not path.is_file()]
        if missing:
            raise FileNotFoundError(f"Selected attachment(s) not found: {', '.join(missing)}")
    else:
        attachments = discover_attachments()
        if attachments:
            attachments = select_attachments(attachments)

    if not attachments:
        raise FileNotFoundError(
            f"No supported attachments found in {ATTACHMENTS_DIR}. "
            f"Supported extensions: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    payload = {
        "sender": "shipping.unit@example.com",
        "subject": f"Shipment documents for CG validation - {len(attachments)} attachment(s)",
        "attachment_paths": [str(path) for path in attachments],
    }

    print(f"Posting one email event with {len(payload['attachment_paths'])} attachments...")
    response = requests.post(
        f"{API_BASE_URL}/api/v1/webhook/incoming-email",
        headers={"x-api-key": API_KEY},
        json=payload,
        timeout=30,
    )
    response.raise_for_status()
    print(response.json())


if __name__ == "__main__":
    main()
