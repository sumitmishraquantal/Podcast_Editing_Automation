"""Load .env from the project root into os.environ (setdefault — won't override existing)."""
from __future__ import annotations

import os
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_dotenv() -> None:
    env_file = HERE / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)
