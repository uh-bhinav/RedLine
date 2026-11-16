"""
Start (or reuse) a local embedded Postgres 16 -- for machines without Docker.

    python scripts/dev_db.py

Data lives in ./.pgdata (gitignored). The server keeps running after this script exits and
the connection string is written to .env as DATABASE_URL, along with sane dev defaults
for any other settings that are missing.
"""
import re
import secrets
from pathlib import Path

import pgserver

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".env"


def set_env(lines: list[str], key: str, value: str, only_if_missing: bool = False) -> list[str]:
    pattern = re.compile(rf"^{key}=")
    for i, line in enumerate(lines):
        if pattern.match(line):
            if not only_if_missing:
                lines[i] = f"{key}={value}"
            return lines
    lines.append(f"{key}={value}")
    return lines


def main() -> None:
    server = pgserver.get_server(str(ROOT / ".pgdata"), cleanup_mode=None)
    uri = server.get_uri().replace("postgresql://", "postgresql+psycopg2://", 1)

    lines = ENV.read_text(encoding="utf-8").splitlines() if ENV.exists() else []
    lines = set_env(lines, "DATABASE_URL", uri)
    lines = set_env(lines, "JWT_SECRET_KEY", secrets.token_urlsafe(48), only_if_missing=True)
    lines = set_env(lines, "GEMINI_API_KEY", "", only_if_missing=True)
    ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Postgres ready: {uri}\n.env updated.")


if __name__ == "__main__":
    main()
