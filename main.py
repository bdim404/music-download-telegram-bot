# !/usr/bin/env python
# -*- coding: utf-8 -*

import logging,os,asyncio,shutil,re,glob,fnmatch,gamdl,subprocess,requests
from telegram.ext import ApplicationBuilder,CommandHandler,MessageHandler,filters
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from telegram import Update,Message

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
        await DownloadAppleMusicSong(update, context)

# Download the Apple Music song;
async def DownloadAppleMusicSong(update: Update, context):
    replyMessage = await  update.message.reply_text("Finding the song, please wait...")
    userId = update.message.from_user.id
    logging.info(f"User {userId} sent a Apple Music song.")

    # Get the URL of the song;
    songUrl = update.message.text
    logging.info(f"Song URL: {songUrl}")
    n =  get_track_numbers(songUrl)

    # Check if the song has been downloaded before
    try:
        artist, album, song = get_song_info(songUrl)
        logging.info(f"Song: {song} - Artist: {artist} - Album: {album}")
        i = ', '.join(map(str, n))
        try:
            songFile = open(f'./Apple Music/{artist}/{album}/{i} {song}.m4a', 'rb') 
            await update.message.reply_audio(audio=songFile)
            logging.info(f"Song sent successfully.")
            return
        except FileNotFoundError:
            logging.info(f"Song not downloaded yet.")
            pass
    except FileNotFoundError:
        logging.info(f"Song not downloaded yet.")
        pass

    # Download the song;
    command = ["gamdl"] + [songUrl]
    try:
        await replyMessage.edit_text("Downloading the song, please wait...")
        process = await asyncio.create_subprocess_exec(*command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await process.communicate()
        await process.wait()
        await replyMessage.edit_text("Song downloaded successfully! Sending the song to you...")
        logging.info(f"Song downloaded successfully.")
    except Exception as e:
        logging.error(f"An error occurred while downloading the song: {e}")
        await update.message.reply_text("An error occurred while downloading the song.")
        return
    await send_song(update,n,songUrl)
    
# Send the song to the user; 
async def send_song(update: Update ,n,songUrl):
    # Check if the song has been downloaded before
    artist, album, song = get_song_info(songUrl)
    logging.info(f"Song: {song} - Artist: {artist} - Album: {album}")
    i = ', '.join(map(str, n))
    try:
        songFile = open(f'./Apple Music/{artist}/{album}/{i} {song}.m4a', 'rb') 
        await update.message.reply_audio(audio=songFile)
        logging.info(f"Song sent successfully.")
        return 
    except FileNotFoundError:
        logging.info(f"Song sent fail.")


 # Get the song info and Send the song to the user;
def get_song_info(url):
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')
    title_element = soup.select_one('.headings__title.svelte-1la0y7y')
    meta_element = soup.select_one('meta[name="keywords"]')
    content = meta_element['content']
    keywords = content.split(', ')
    song = keywords[1]
    song = re.sub(r' - Single', '', song)
    artist = keywords[2]
    album = title_element.get_text(strip=True)
    return artist, album, song

# get the trank name
def get_track_numbers(url):
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')
    meta_tags = soup.find_all('meta', {'property': 'music:song:track'})
    track_numbers = [int(tag['content']) for tag in meta_tags]
    if len(track_numbers) == 1:
        if track_numbers[0] < 10:
            return ["{:02}".format(track_numbers[0])]
        else:
            return track_numbers[0]
    else:
        return ["{:02}".format(track_number) for track_number in track_numbers]
        return track_numbers

if __name__ == '__main__':
    bot = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    bot.add_handler(CommandHandler("start", handleStartMessage))
    bot.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handleRequest))
    bot.run_polling()
    logging.info("Bot application started")
