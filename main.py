# !/usr/bin/env python
# -*- coding: utf-8 -*

import logging,os,asyncio,shutil,re,glob,fnmatch,gamdl,subprocess,requests
from telegram.ext import ApplicationBuilder,CommandHandler,MessageHandler,filters
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from telegram import Update,Message
from urllib.parse import urlparse, parse_qs
from http.cookiejar import MozillaCookieJar
from pydub import AudioSegment

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
    artist, album, disc, album_sort = await webplayback.get_webplayback(songUrl)
    # Check if the song has been downloaded before
    try:
        logging.info(f"/Apple Music/{artist}/{album}/{disc} {album_sort}")
        try:
            songFile = open(f'./Apple Music/{artist}/{album}/{disc} {album_sort}.m4a', 'rb') 
            await update.message.reply_audio(audio=songFile)
            await replyMessage.edit_text("Song sent successfully.")
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
    logging.info(f"Command: {' '.join(command)}")
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
    await send_song(update,artist,album,disc,album_sort)
    
# Send the song to the user; 
async def send_song(update: Update ,artist,album,disc,album_sort):

    logging.info(f"/Apple Music/{artist}/{album}/{disc} {album_sort}")
    try:
        songFile = open(f'./Apple Music/{artist}/{album}/{disc} {album_sort}.m4a', 'rb') 
        await update.message.reply_audio(audio=songFile)
        logging.info(f"Song sent successfully.")
        await replyMessage.reply_text("Song sent successfully.")
        return 
    except FileNotFoundError:
        logging.info(f"Song sent fail.")



class WebPlayback:
    def __init__(self, cookies_location):
        self.cookies_location = cookies_location
        self.session = requests.Session()

    def setup_session(self) -> None:
        cookies = MozillaCookieJar(self.cookies_location)
        cookies.load(ignore_discard=True, ignore_expires=True)
        self.session.cookies.update(cookies)
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:95.0) Gecko/20100101 Firefox/95.0",
                "Accept": "application/json",
                "Accept-Language": "en-US,en;q=0.5",
                "Accept-Encoding": "gzip, deflate, br",
                "content-type": "application/json",
                "Media-User-Token": self.session.cookies.get_dict()["media-user-token"],
                "x-apple-renewal": "true",
                "DNT": "1",
                "Connection": "keep-alive",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-site",
                "origin": "https://beta.music.apple.com",
            }
        )
        home_page = self.session.get("https://beta.music.apple.com").text
        index_js_uri = re.search(r"/(assets/index-legacy-[^/]+\.js)", home_page).group(1)
        index_js_page = self.session.get(f"https://beta.music.apple.com/{index_js_uri}").text
        token = re.search('(?=eyJh)(.*?)(?=")', index_js_page).group(1)
        self.session.headers.update({"authorization": f"Bearer {token}"})

    async def get_webplayback(self, url: str) -> dict:
        parsed_url = urlparse(url)
        query_params = parse_qs(parsed_url.query)
        track_id = query_params.get('i', [''])[0]

        json_data = {
            "salableAdamId": track_id,
            "language": "en-US",
        }

        response = self.session.post(
            "https://play.itunes.apple.com/WebObjects/MZPlay.woa/wa/webPlayback",
            json=json_data,
        )

        response_json = response.json()

        song_list = response_json.get('songList', [{}])
        assets = song_list[0].get('assets', [{}])
        metadata = assets[0].get('metadata', {})

        album = metadata.get('playlistName')
        artist = metadata.get('playlistArtistName')
        album_sort = metadata.get('itemName')
        disc = metadata.get('trackNumber')
        disc = "{:02}".format(disc)

        print(response_json)
        response = requests.get(url, stream=True)
        return artist, album, disc, album_sort

if __name__ == '__main__':
    bot = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    bot.add_handler(CommandHandler("start", handleStartMessage))
    bot.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handleRequest))
    webplayback = WebPlayback("cookies.txt")
    webplayback.setup_session()
    bot.run_polling()
    logging.info("Bot application started")