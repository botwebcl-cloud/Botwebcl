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

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
PREMIUM_PAYMENT_LINK = os.environ.get("PREMIUM_PAYMENT_LINK", "https://buy.stripe.com/tu-link-aqui")

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

PREMIUM_MESSAGE = (
    "⭐ Plan Premium — $4.99/mes\n\n"
    f"• Resúmenes ilimitados\n"
    f"• Hasta {sm.MAX_PAGES_PREMIUM} páginas o {sm.MAX_YOUTUBE_MINUTES_PREMIUM} min de vídeo\n"
    "• Formato flashcards además del resumen normal\n\n"
    f"Suscríbete aquí: {PREMIUM_PAYMENT_LINK}\n\n"
    "Cuando completes el pago, escribe /activar y tu cuenta se marcará como Premium."
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.get_or_create_user(user.id, user.username or "")
    await update.message.reply_text(WELCOME_MESSAGE)


async def premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(PREMIUM_MESSAGE)


async def activar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # NOTA: en producción esto debería verificarse contra un webhook de Stripe,
    # no activarse a mano. Aquí queda como placeholder simple para el MVP gratuito.
    user = update.effective_user
    db.get_or_create_user(user.id, user.username or "")
    await update.message.reply_text(
        "Para activar Premium de forma segura necesitamos confirmar tu pago. "
        "Por ahora, escríbenos y lo activamos manualmente mientras montamos el webhook automático."
    )


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
            f"Has llegado a tu límite gratuito de {db.FREE_LIMIT_PER_MONTH} resúmenes este mes.\n\n{PREMIUM_MESSAGE}"
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
            f"Has llegado a tu límite gratuito de {db.FREE_LIMIT_PER_MONTH} resúmenes este mes.\n\n{PREMIUM_MESSAGE}"
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
    app.add_handler(CommandHandler("activar", activar))
    app.add_handler(MessageHandler(filters.Document.PDF, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("ResumeBot arrancado.")
    app.run_polling()


if __name__ == "__main__":
    main()"""
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
PREMIUM_PAYMENT_LINK = os.environ.get("PREMIUM_PAYMENT_LINK", "https://buy.stripe.com/tu-link-aqui")

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

PREMIUM_MESSAGE = (
    "⭐ Plan Premium — $4.99/mes\n\n"
    f"• Resúmenes ilimitados\n"
    f"• Hasta {sm.MAX_PAGES_PREMIUM} páginas o {sm.MAX_YOUTUBE_MINUTES_PREMIUM} min de vídeo\n"
    "• Formato flashcards además del resumen normal\n\n"
    f"Suscríbete aquí: {PREMIUM_PAYMENT_LINK}\n\n"
    "Cuando completes el pago, escribe /activar y tu cuenta se marcará como Premium."
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.get_or_create_user(user.id, user.username or "")
    await update.message.reply_text(WELCOME_MESSAGE)


async def premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(PREMIUM_MESSAGE)


async def activar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # NOTA: en producción esto debería verificarse contra un webhook de Stripe,
    # no activarse a mano. Aquí queda como placeholder simple para el MVP gratuito.
    user = update.effective_user
    db.get_or_create_user(user.id, user.username or "")
    await update.message.reply_text(
        "Para activar Premium de forma segura necesitamos confirmar tu pago. "
        "Por ahora, escríbenos y lo activamos manualmente mientras montamos el webhook automático."
    )


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
            f"Has llegado a tu límite gratuito de {db.FREE_LIMIT_PER_MONTH} resúmenes este mes.\n\n{PREMIUM_MESSAGE}"
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
            f"Has llegado a tu límite gratuito de {db.FREE_LIMIT_PER_MONTH} resúmenes este mes.\n\n{PREMIUM_MESSAGE}"
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
    app.add_handler(CommandHandler("activar", activar))
    app.add_handler(MessageHandler(filters.Document.PDF, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("ResumeBot arrancado.")
    app.run_polling()


if __name__ == "__main__":
    main()
