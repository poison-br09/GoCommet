import logging
import logging.handlers
from pathlib import Path

# Logs land in  server/logs/  next to the app/ package
_LOG_DIR = Path(__file__).resolve().parents[2] / "logs"
LOG_FILE = _LOG_DIR / "nova_pipeline.log"

_FMT = "%(asctime)s  [%(levelname)-8s]  %(name)s  —  %(message)s"
_DATE_FMT = "%Y-%m-%d %H:%M:%S"


def _bootstrap() -> None:
    root = logging.getLogger("nova")
    if root.handlers:
        return

    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    root.setLevel(logging.DEBUG)

    # Rotating file: 10 MB per file, 5 backups kept
    fh = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(_FMT, _DATE_FMT))

    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter(_FMT, _DATE_FMT))

    root.addHandler(fh)
    root.addHandler(ch)


_bootstrap()


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the 'nova' root namespace."""
    return logging.getLogger(f"nova.{name}")
