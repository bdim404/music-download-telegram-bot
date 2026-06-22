from telegram import Update
from telegram.ext import ContextTypes


MAX_MESSAGE_LENGTH = 3900


def _format_codecs(codecs: list[str]) -> str:
    return ", ".join(f"`{codec}`" for codec in codecs)


def _target_user_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    if update.message and update.message.reply_to_message:
        user = update.message.reply_to_message.from_user
        return user.id if user else None

    if context.args:
        try:
            return int(context.args[0])
        except ValueError:
            return None

    return None


def _format_user_row(user: dict) -> str:
    name = user.get('username') or user.get('first_name') or "-"
    if user.get('username'):
        name = f"@{name}"
    codec = user.get('download_codec') or "-"
    downloads = user.get('download_count') or 0
    last_activity = user.get('last_activity') or "-"
    return f"- {user['user_id']} {name} codec={codec} downloads={downloads} last={last_activity}"


async def codec_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or not update.message:
        return

    cache = context.bot_data['cache']
    config = context.bot_data['config']
    downloader = context.bot_data['downloader']

    current_codec = await cache.get_user_codec(user.id, config.song_codec)
    current_codec = downloader.effective_codec(current_codec)

    if not context.args:
        await update.message.reply_text(
            "Current codec: "
            f"`{current_codec}`\n\n"
            "Set codec with `/codec <codec>`.\n"
            f"Available codecs: {_format_codecs(downloader.supported_codecs)}",
            parse_mode="Markdown"
        )
        return

    requested_codec = downloader.normalize_codec(context.args[0])
    if requested_codec != context.args[0].lower():
        await update.message.reply_text(
            "Unknown codec.\n"
            f"Available codecs: {_format_codecs(downloader.supported_codecs)}",
            parse_mode="Markdown"
        )
        return

    if not downloader.is_codec_available(requested_codec):
        await update.message.reply_text(
            f"`{requested_codec}` requires wrapper mode. Enable `use_wrapper: true` first.",
            parse_mode="Markdown"
        )
        return

    await cache.set_user_codec(
        user.id,
        requested_codec,
        user.username,
        user.first_name
    )
    await update.message.reply_text(
        f"Download codec set to `{requested_codec}`.",
        parse_mode="Markdown"
    )


async def allow_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or not update.message:
        return

    whitelist = context.bot_data['whitelist']
    if not whitelist.check_admin(user.id):
        await update.message.reply_text("Only administrators can allow users.")
        return

    target_user_id = _target_user_id(update, context)
    if not target_user_id:
        await update.message.reply_text("Usage: /allow <telegram_user_id> or reply with /allow")
        return

    target_user = update.message.reply_to_message.from_user if update.message.reply_to_message else None
    await context.bot_data['cache'].set_user_whitelist(
        target_user_id,
        True,
        target_user.username if target_user else None,
        target_user.first_name if target_user else None
    )
    await update.message.reply_text(f"Allowed user `{target_user_id}`.", parse_mode="Markdown")


async def deny_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or not update.message:
        return

    whitelist = context.bot_data['whitelist']
    if not whitelist.check_admin(user.id):
        await update.message.reply_text("Only administrators can deny users.")
        return

    target_user_id = _target_user_id(update, context)
    if not target_user_id:
        await update.message.reply_text("Usage: /deny <telegram_user_id> or reply with /deny")
        return

    await context.bot_data['cache'].set_user_whitelist(target_user_id, False)
    await update.message.reply_text(f"Denied user `{target_user_id}`.", parse_mode="Markdown")


async def list_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or not update.message:
        return

    whitelist = context.bot_data['whitelist']
    if not whitelist.check_admin(user.id):
        await update.message.reply_text("Only administrators can list users.")
        return

    config = context.bot_data['config']
    cache = context.bot_data['cache']
    db_users = await cache.list_whitelisted_users()

    lines = ["Whitelisted users"]

    admin_users = getattr(config, 'admin_users', [])
    if admin_users:
        lines.append("\nConfig admins:")
        lines.extend(f"- {user_id}" for user_id in admin_users)

    config_users = getattr(config, 'whitelist_users', [])
    if config_users:
        lines.append("\nConfig whitelist:")
        lines.extend(f"- {user_id}" for user_id in config_users)

    lines.append("\nDatabase whitelist:")
    if db_users:
        lines.extend(_format_user_row(db_user) for db_user in db_users)
    else:
        lines.append("- empty")

    text = "\n".join(lines)
    if len(text) <= MAX_MESSAGE_LENGTH:
        await update.message.reply_text(text)
        return

    chunks = []
    current = []
    current_len = 0
    for line in lines:
        line_len = len(line) + 1
        if current and current_len + line_len > MAX_MESSAGE_LENGTH:
            chunks.append("\n".join(current))
            current = []
            current_len = 0
        current.append(line)
        current_len += line_len
    if current:
        chunks.append("\n".join(current))

    for chunk in chunks:
        await update.message.reply_text(chunk)
