"""
Günlük log yapılandırması.

Konsol ve logs/log-YYYY-MM-DD.txt dosyasına yazar.
Gece yarısı dosya adı yeni güne döner.
"""

import logging
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path


def setup_logging(log_dir: Path) -> logging.Logger:
    """gdm logger'ına konsol ve döner dosya işleyicisi bağlar."""
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("gdm")
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    today = datetime.now().strftime("%Y-%m-%d")
    file_handler = TimedRotatingFileHandler(
        filename=log_dir / f"log-{today}.txt",
        when="midnight",
        backupCount=30,
        encoding="utf-8",
    )
    file_handler.suffix = "%Y-%m-%d"
    file_handler.namer = _dated_log_name
    file_handler.setFormatter(formatter)

    console = logging.StreamHandler()
    console.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console)
    logger.propagate = False
    return logger


def _dated_log_name(default_name: str) -> str:
    """Dönen dosyayı log-YYYY-MM-DD.txt biçimine çevirir."""
    parent = Path(default_name).parent
    date = default_name.rsplit(".", 1)[-1]
    return str(parent / f"log-{date}.txt")
