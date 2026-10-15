import json
import os
from pathlib import Path
from typing import Any

from filelock import FileLock


DEFAULT_DB_FILE = r"C:\jfrog-approval-data\approvals.json"

DB_FILE = Path(
    os.getenv(
        "APPROVAL_DB",
        DEFAULT_DB_FILE
    )
)

LOCK_FILE = Path(
    str(DB_FILE) + ".lock"
)


def ensure_database() -> None:
    DB_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    if not DB_FILE.exists():
        DB_FILE.write_text(
            "{}",
            encoding="utf-8"
        )


def load_database() -> dict[str, Any]:
    ensure_database()

    with FileLock(str(LOCK_FILE)):

        raw_content = DB_FILE.read_text(
            encoding="utf-8-sig"
        ).strip()

        if not raw_content:
            return {}

        return json.loads(
            raw_content
        )


def save_database(
    database: dict[str, Any]
) -> None:

    ensure_database()

    temporary_file = Path(
        str(DB_FILE) + ".tmp"
    )

    with FileLock(str(LOCK_FILE)):

        temporary_file.write_text(
            json.dumps(
                database,
                indent=2
            ),
            encoding="utf-8"
        )

        temporary_file.replace(
            DB_FILE
        )


def get_request(
    request_id: str
) -> dict[str, Any] | None:

    database = load_database()

    return database.get(
        request_id
    )


def save_request(
    request_id: str,
    record: dict[str, Any]
) -> None:

    database = load_database()

    database[
        request_id
    ] = record

    save_database(
        database
    )
