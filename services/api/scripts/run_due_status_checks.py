"""Run one batch of due scheduled source-status checks.

For a dependable schedule on serverless/free web hosting, invoke this script
from a scheduler that can run independently of API process sleep. Set
DATABASE_URL to the same PostgreSQL URI (SQLAlchemy psycopg driver form).
"""
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if not os.environ.get("DATABASE_URL"):
    print("DATABASE_URL is not configured; no source monitoring checks were run.", file=sys.stderr)
    raise SystemExit(2)

from app.services.status_monitor import run_due_status_checks  # noqa: E402


async def main() -> int:
    results = await run_due_status_checks()
    print(json.dumps({"processed": len(results), "results": results}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
