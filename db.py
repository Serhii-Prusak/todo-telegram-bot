import json
import sqlite3
from pathlib import Path

DB_PATH = Path("task_assistant.db")


def init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pending_tasks (
                chat_id TEXT PRIMARY KEY,
                original_text TEXT NOT NULL,
                parsed_json TEXT NOT NULL
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_modes (
                chat_id TEXT PRIMARY KEY,
                mode TEXT NOT NULL
            )
            """
        )


def save_pending_task(chat_id: int, original_text: str, parsed: dict) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO pending_tasks (chat_id, original_text, parsed_json)
            VALUES (?, ?, ?)
            """,
            (str(chat_id), original_text, json.dumps(parsed, ensure_ascii=False)),
        )


def get_pending_task(chat_id: int) -> dict | None:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            """
            SELECT original_text, parsed_json
            FROM pending_tasks
            WHERE chat_id = ?
            """,
            (str(chat_id),),
        ).fetchone()

    if not row:
        return None

    original_text, parsed_json = row

    return {
        "original_text": original_text,
        "parsed": json.loads(parsed_json),
    }


def clear_pending_task(chat_id: int) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            DELETE FROM pending_tasks
            WHERE chat_id = ?
            """,
            (str(chat_id),),
        )


def set_chat_mode(chat_id: int, mode: str) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO chat_modes (chat_id, mode)
            VALUES (?, ?)
            """,
            (str(chat_id), mode),
        )


def get_chat_mode(chat_id: int) -> str | None:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            """
            SELECT mode
            FROM chat_modes
            WHERE chat_id = ?
            """,
            (str(chat_id),),
        ).fetchone()

    if not row:
        return None

    return row[0]


def clear_chat_mode(chat_id: int) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            DELETE FROM chat_modes
            WHERE chat_id = ?
            """,
            (str(chat_id),),
        )
        