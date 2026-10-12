"""Read the Anthropic API key from the repository's .env file.

The key is read by the harness alone. It is never printed, logged, or written
into any record.
"""

from __future__ import annotations

import os
from pathlib import Path

KEY_NAME = "ANTHROPIC_API_KEY"


def read_dotenv(path: Path) -> dict[str, str]:
    """Parse KEY=VALUE lines; blank lines and # comments are ignored."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def load_api_key(dotenv_path: Path = Path(".env")) -> str:
    """Return the API key, preferring .env over the process environment.

    .env wins so that a key exported for some other tool in the shell can never
    silently bill this harness's runs to a different account.
    """
    key = read_dotenv(dotenv_path).get(KEY_NAME) or os.environ.get(KEY_NAME)
    if not key:
        raise SystemExit(
            f"No {KEY_NAME} found. Put it in {dotenv_path} as {KEY_NAME}=... "
            "(the file is gitignored)."
        )
    return key
