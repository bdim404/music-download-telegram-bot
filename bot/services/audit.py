import logging
from telegram import Update


logger = logging.getLogger(__name__)


def user_label(update: Update) -> str:
    user = update.effective_user
    chat = update.effective_chat
    message = update.effective_message

    user_id = user.id if user else "-"
    username = f"@{user.username}" if user and user.username else "-"
    chat_id = chat.id if chat else "-"
    chat_type = chat.type if chat else "-"
    message_id = message.message_id if message else "-"
    return (
        f"user_id={user_id} username={username} "
        f"chat_id={chat_id} chat_type={chat_type} message_id={message_id}"
    )


def log_user_action(update: Update, action: str, **details):
    detail_text = " ".join(f"{key}={value}" for key, value in details.items())
    suffix = f" {detail_text}" if detail_text else ""
    logger.info(f"{action}: {user_label(update)}{suffix}")
