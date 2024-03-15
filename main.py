# !/usr/bin/env python
# -*- coding: utf-8 -*

from telegram.ext import ApplicationBuilder,CommandHandler,MessageHandler,filters
from AppleMusicDownloader import AppleMusicDownloader
from telegram import Update,Message
from dotenv import load_dotenv
import logging,os,asyncio,re

# Configure the logging;
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Load the environment variables;
load_dotenv()

# Get the environment variables;
try:
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
except:
    logging.error("The TELEGRAM_BOT_TOKEN environment variable is not set.")
    exit(1)
try:
    ADMIN_USER_IDS = list(map(int, os.getenv("ADMIN_USER_IDS").split(",")))
except:
    logging.error("The ADMIN_USER_IDS environment variable is not set.")
    exit(1)
try:
    ALLOWED_TELEGRAM_USER_IDS = list(map(int, os.getenv("ALLOWED_TELEGRAM_USER_IDS").split(",")))
except:
    ALLOWED_TELEGRAM_USER_IDS = []
logging.info("Environment variables loaded.")



# Start message handler;
async def handleStartMessage(update, context):
    userId = update.message.from_user.id
    logging.info(f"User {userId} started the bot.")
    if userId in ADMIN_USER_IDS:
        await update.message.reply_text("Hey boss, I'm ready to serve you :)")
    elif userId in ALLOWED_TELEGRAM_USER_IDS:
        await update.message.reply_text("Hello! I'm apple music download bot,send me the link of the song you want to download.")
    else:
        await update.message.reply_text("Sorry, you are not allowed to use this bot, please contact admin to get the permission.")
    return

# Request handler;
async def handleRequest(update: Update, context):
    userId = update.message.from_user.id
    logging.info(f"User {userId} sent a message.")
    if update.message.chat.type == "private":
        if userId not in ADMIN_USER_IDS and userId not in ALLOWED_TELEGRAM_USER_IDS:
            await update.message.reply_text("Sorry, you are not allowed to use this bot, please contact admin to get the permission.")
            return

    # Message entities handler;
    entityUrl = ""
    if update.message.entities:
        for entity in update.message.entities:
            if entity.type == "text_link":
                entityUrl = entity.url
                logging.info(f"Entity URL: {entityUrl}")

    # Check if the message is a link including Apple Music;
    if "https://music.apple.com" in update.message.text :
        downloader = AppleMusicDownloader()
        await downloader.CheckLinkType(update, context)
    elif update.message.chat.type == "private":
        await update.message.reply_text("Please send me the link of the song you want to download.")
    else:
        logging.info("The message is not a link including Apple Music.")

if __name__ == '__main__':
    bot = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    bot.add_handler(CommandHandler("start", handleStartMessage))
    bot.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handleRequest))
    bot.run_polling(timeout=40, allowed_updates=Update.ALL_TYPES)
    logging.info("Bot application started")