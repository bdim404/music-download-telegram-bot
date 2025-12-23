from telegram import Update
from telegram.ext import ContextTypes


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Welcome to Apple Music Download Bot!\n\n"
        "Send me an Apple Music link (song, album, or playlist) and I'll download it for you.\n\n"
        "Supported links:\n"
        "- Songs: https://music.apple.com/.../song/.../...\n"
        "- Albums: https://music.apple.com/.../album/.../...\n"
        "- Playlists: https://music.apple.com/.../playlist/.../..."
    )
