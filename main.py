"""
main.py
ResumeBot - Bot de Telegram que resume PDFs, artículos web y vídeos de YouTube.
100% gratuito de operar: usa resumen extractivo local (sin API de pago).

Antes de ejecutar:
1. Crea el bot con @BotFather en Telegram y copia el token.
2. Exporta la variable de entorno TELEGRAM_BOT_TOKEN con ese token.
3. pip install -r requirements.txt
4. python main.py
"""
import os
import logging
import tempfile
import threading
from typing import Optional

import requests
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

import database as db
import summarizer as sm
from webhook_server import run_webhook_server

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
MP_ACCESS_TOKEN = os.environ.get("MP_ACCESS_TOKEN", "")
# URL pública de tu bot en Railway, ej: https://tu-app.up.railway.app (sin barra al final)
PUBLIC_URL = os.environ.get("PUBLIC_URL", "")
PREMIUM_PRICE_CLP = int(os.environ.get("PREMIUM_PRICE_CLP", "4990"))

WELCOME_MESSAGE = (
    "👋 ¡Hola! Soy ResumeBot.\n\n"
    "Mándame:\n"
    "📄 Un PDF\n"
    "🔗 El link de un artículo\n"
    "▶️ El link de un vídeo de YouTube\n\n"
    "Y te devuelvo un resumen en segundos.\n\n"
    f"Plan gratuito: {db.FREE_LIMIT_PER_MONTH} resúmenes al mes "
    f"(hasta {sm.MAX_PAGES_FREE} páginas o {sm.MAX_YOUTUBE_MINUTES_FREE} min de vídeo).\n"
    "Usa /premium para ver el plan sin límites."
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.get_or_create_user(user.id, user.username or "")
    await update.message.reply_text(WELCOME_MESSAGE)


def _create_mercadopago_preference(code: str) -> Optional[str]:
    """Crea una preferencia de pago en MercadoPago para este código de activación.
    Devuelve la URL de pago (init_point), o None si algo falla."""
    if not MP_ACCESS_TOKEN:
        logger.error("Falta MP_ACCESS_TOKEN.")
        return None

    url = "https://api.mercadopago.com/checkout/preferences"
    headers = {
        "Authorization": f"Bearer {MP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "items": [
            {
                "title": "ResumeBot Premium (30 días)",
                "quantity": 1,
                "currency_id": "CLP",
                "unit_price": PREMIUM_PRICE_CLP,
            }
        ],
        "external_reference": code,
        "notification_url": f"{PUBLIC_URL}/mercadopago-webhook" if PUBLIC_URL else None,
        "back_urls": {
            "success": "https://t.me/",
            "failure": "https://t.me/",
            "pending": "https://t.me/",
        },
    }
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=10)
        if resp.status_code not in (200, 201):
            logger.error("Error creando preferencia MP: %s", resp.text)
            return None
        data = resp.json()
        return data.get("init_point")
    except requests.RequestException as e:
        logger.error("Error de red creando preferencia MP: %s", e)
        return None


async def premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_data = db.get_or_create_user(user.id, user.username or "")

    if user_data["is_premium"]:
        await update.message.reply_text("✅ Ya tienes el plan Premium activo. ¡Gracias!")
        return

    code = db.create_activation_code(user.id)
    payment_url = _create_mercadopago_preference(code)

    if not payment_url:
        await update.message.reply_text(
            "Hubo un problema generando el link de pago. Inténtalo de nuevo en unos minutos."
        )
        return

    message = (
        f"⭐ Plan Premium — ${PREMIUM_PRICE_CLP} CLP / 30 días\n\n"
        f"• Resúmenes ilimitados\n"
        f"• Hasta {sm.MAX_PAGES_PREMIUM} páginas o {sm.MAX_YOUTUBE_MINUTES_PREMIUM} min de vídeo\n"
        "• Formato flashcards además del resumen normal\n\n"
        f"Paga aquí: {payment_url}\n\n"
        "En cuanto completes el pago, tu cuenta se activa sola — no hace falta que hagas nada más."
    )
    await update.message.reply_text(message)


def _usage_footer(user_data: dict) -> str:
    if user_data["is_premium"]:
        return ""
    restantes = db.FREE_LIMIT_PER_MONTH - user_data["usage_count"] - 1
    return f"\n\n📊 Te quedan {max(restantes, 0)} resúmenes gratis este mes."


async def _handle_result(update: Update, user_data: dict, text: str):
    try:
        summary = sm.summarize_text(text)
    except Exception as e:
        logger.exception("Error al resumir")
        await update.message.reply_text("Hubo un error generando el resumen. Inténtalo de nuevo.")
        return
    db.increment_usage(user_data["user_id"])
    await update.message.reply_text(f"📝 Resumen:\n\n{summary}{_usage_footer(user_data)}")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_data = db.get_or_create_user(user.id, user.username or "")

    if not db.can_use(user_data):
        await update.message.reply_text(
            f"Has llegado a tu límite gratuito de {db.FREE_LIMIT_PER_MONTH} resúmenes este mes.\n\nUsa /premium para suscribirte y seguir sin límites."
        )
        return

    doc = update.message.document
    if not doc.file_name.lower().endswith(".pdf"):
        await update.message.reply_text("Por ahora solo puedo leer archivos PDF.")
        return

    await update.message.reply_text("📄 Procesando tu PDF...")
    with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
        file = await context.bot.get_file(doc.file_id)
        await file.download_to_drive(tmp.name)
        try:
            text = sm.extract_from_pdf(tmp.name, bool(user_data["is_premium"]))
        except sm.ExtractionError as e:
            await update.message.reply_text(f"⚠️ {e}")
            return

    await _handle_result(update, user_data, text)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_data = db.get_or_create_user(user.id, user.username or "")
    message_text = update.message.text.strip()

    if not message_text.startswith("http"):
        await update.message.reply_text(
            "Mándame un PDF, o un link de un artículo o de YouTube. Usa /start para ver cómo funciono."
        )
        return

    if not db.can_use(user_data):
        await update.message.reply_text(
            f"Has llegado a tu límite gratuito de {db.FREE_LIMIT_PER_MONTH} resúmenes este mes.\n\nUsa /premium para suscribirte y seguir sin límites."
        )
        return

    is_youtube = "youtube.com" in message_text or "youtu.be" in message_text

    await update.message.reply_text("🔎 Procesando...")
    try:
        if is_youtube:
            text = sm.extract_from_youtube(message_text, bool(user_data["is_premium"]))
        else:
            text = sm.extract_from_url(message_text)
    except sm.ExtractionError as e:
        await update.message.reply_text(f"⚠️ {e}")
        return

    await _handle_result(update, user_data, text)


def main():
    if not TOKEN:
        raise RuntimeError("Falta la variable de entorno TELEGRAM_BOT_TOKEN")

    db.init_db()

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("premium", premium))
    app.add_handler(MessageHandler(filters.Document.PDF, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Arranca el servidor del webhook de pagos en un hilo aparte,
    # para que corra en paralelo al bot sin bloquearlo.
    webhook_thread = threading.Thread(target=run_webhook_server, daemon=True)
    webhook_thread.start()

    logger.info("ResumeBot arrancado (bot + webhook de pagos).")
    app.run_polling()


if __name__ == "__main__":
    main()
