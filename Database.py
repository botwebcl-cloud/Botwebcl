"""
database.py
Maneja usuarios y su contador de uso mensual en SQLite (cero coste, sin servidor externo).
"""
import sqlite3
from datetime import datetime
from contextlib import contextmanager

DB_PATH = "resumebot.db"

FREE_LIMIT_PER_MONTH = 5  # resúmenes gratis por usuario y mes


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                is_premium INTEGER DEFAULT 0,
                usage_count INTEGER DEFAULT 0,
                usage_month TEXT
            )
            """
        )


def _current_month():
    return datetime.utcnow().strftime("%Y-%m")


def get_or_create_user(user_id: int, username: str):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        month = _current_month()
        if row is None:
            conn.execute(
                "INSERT INTO users (user_id, username, usage_count, usage_month) VALUES (?, ?, 0, ?)",
                (user_id, username, month),
            )
            return {"user_id": user_id, "is_premium": 0, "usage_count": 0, "usage_month": month}
        # Reinicia el contador si estamos en un mes nuevo
        if row["usage_month"] != month:
            conn.execute(
                "UPDATE users SET usage_count = 0, usage_month = ? WHERE user_id = ?",
                (month, user_id),
            )
            return {"user_id": user_id, "is_premium": row["is_premium"], "usage_count": 0, "usage_month": month}
        return dict(row)


def increment_usage(user_id: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET usage_count = usage_count + 1 WHERE user_id = ?",
            (user_id,),
        )


def set_premium(user_id: int, is_premium: bool = True):
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET is_premium = ? WHERE user_id = ?",
            (1 if is_premium else 0, user_id),
        )


def can_use(user_data: dict) -> bool:
    if user_data["is_premium"]:
        return True
    return user_data["usage_count"] < FREE_LIMIT_PER_MONTH
