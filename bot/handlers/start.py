from telegram import Update
from telegram.ext import ContextTypes

from ..services.audit import log_user_action


def help_text(is_admin: bool = False) -> str:
    text = (
        "Apple Music Download Bot\n\n"
        "Send me an Apple Music link and I'll download it for you.\n\n"
        "Supported links:\n"
        "- Songs: https://music.apple.com/.../song/.../...\n"
        "- Albums: https://music.apple.com/.../album/.../...\n"
        "- Playlists: https://music.apple.com/.../playlist/.../...\n\n"
        "Commands:\n"
        "- /help: show this help message\n"
        "- /codec: show your download codec\n"
        "- /codec aac: set your download codec"
    )

    if is_admin:
        text += (
            "\n\nAdmin commands:\n"
            "- /allow <user_id>: allow a user\n"
            "- /deny <user_id>: deny a user\n"
            "- /list: list whitelisted users"
        )

    return text


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await help_handler(update, context)


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    whitelist = context.bot_data.get('whitelist')
    is_admin = bool(user and whitelist and whitelist.check_admin(user.id))
    log_user_action(update, "command_help", is_admin=is_admin)
    await update.message.reply_text(help_text(is_admin))
