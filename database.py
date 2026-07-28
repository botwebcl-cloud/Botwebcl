"""
database.py
Maneja usuarios, su contador de uso mensual, y los códigos de activación
de pago en SQLite (cero coste, sin servidor externo).

El plan Premium se maneja con fecha de expiración (premium_until), porque
MercadoPago Checkout Pro no soporta suscripciones recurrentes automáticas
tan simple como Stripe. Cada pago extiende el Premium 30 días.
"""
import sqlite3
import secrets
from datetime import datetime, timedelta
from contextlib import contextmanager

DB_PATH = "resumebot.db"

FREE_LIMIT_PER_MONTH = 5 # resúmenes gratis por usuario y mes
PREMIUM_DURATION_DAYS = 30


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
                premium_until TEXT,
                usage_count INTEGER DEFAULT 0,
                usage_month TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS activation_codes (
                code TEXT PRIMARY KEY,
                user_id INTEGER,
                used INTEGER DEFAULT 0,
                created_at TEXT
            )
            """
        )


def _current_month():
    return datetime.utcnow().strftime("%Y-%m")


def _is_premium_active(premium_until: str) -> bool:
    if not premium_until:
        return False
    try:
        return datetime.fromisoformat(premium_until) > datetime.utcnow()
    except ValueError:
        return False


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
            return {"user_id": user_id, "premium_until": None, "is_premium": False, "usage_count": 0, "usage_month": month}
        data = dict(row)
        # Reinicia el contador si estamos en un mes nuevo
        if data["usage_month"] != month:
            conn.execute(
                "UPDATE users SET usage_count = 0, usage_month = ? WHERE user_id = ?",
                (month, user_id),
            )
            data["usage_count"] = 0
            data["usage_month"] = month
        data["is_premium"] = _is_premium_active(data["premium_until"])
        return data


def increment_usage(user_id: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET usage_count = usage_count + 1 WHERE user_id = ?",
            (user_id,),
        )


def can_use(user_data: dict) -> bool:
    if user_data["is_premium"]:
        return True
    return user_data["usage_count"] < FREE_LIMIT_PER_MONTH


def create_activation_code(user_id: int) -> str:
    """Genera un código único ligado a un usuario, para incluir en el link de pago."""
    code = secrets.token_hex(8) # ej. '4f3a9c1d8b2e7f60'
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO activation_codes (code, user_id, used, created_at) VALUES (?, ?, 0, ?)",
            (code, user_id, datetime.utcnow().isoformat()),
        )
    return code


def redeem_activation_code(code: str):
    """Busca el código, lo marca como usado y extiende el Premium 30 días
    para el usuario dueño. Devuelve el user_id activado, o None si el
    código no existe o ya se usó."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM activation_codes WHERE code = ? AND used = 0", (code,)
        ).fetchone()
        if row is None:
            return None
        user_id = row["user_id"]
        conn.execute("UPDATE activation_codes SET used = 1 WHERE code = ?", (code,))

        user_row = conn.execute(
            "SELECT premium_until FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        now = datetime.utcnow()
        current_until = None
        if user_row and user_row["premium_until"]:
            try:
                current_until = datetime.fromisoformat(user_row["premium_until"])
            except ValueError:
                current_until = None
        base = current_until if (current_until and current_until > now) else now
        new_until = base + timedelta(days=PREMIUM_DURATION_DAYS)

        conn.execute(
            "UPDATE users SET premium_until = ? WHERE user_id = ?",
            (new_until.isoformat(), user_id),
        )
        return user_id
