from telegram import Update
from telegram.ext import ContextTypes
import logging

from ..services.health import notify_admins

logger = logging.getLogger(__name__)


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error {context.error}", exc_info=context.error)
    await notify_admins(
        context.application,
        f"Bot handler error: {type(context.error).__name__}: {context.error}"
    )

    if update and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "An unexpected error occurred. Please try again later."
            )
        except Exception as e:
            logger.error(f"Failed to send error message: {e}")
