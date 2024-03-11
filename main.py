# !/usr/bin/env python
# -*- coding: utf-8 -*

from telegram.ext import ApplicationBuilder,CommandHandler,MessageHandler,filters
import logging,os,asyncio,shutil,re,glob,fnmatch,gamdl,subprocess,requests
from urllib.parse import urlparse, parse_qs
from http.cookiejar import MozillaCookieJar
from db import get_session,musicSong
from telegram import Update,Message
from pydub import AudioSegment
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from retrying import retry

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

# set the retrying decorator;
def retry_if_connection_error(exception):
    return isinstance(exception, requests.exceptions.ConnectionError)

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
        await CheckLinkType(update, context)
    elif update.message.chat.type == "private":
        await update.message.reply_text("Please send me the link of the song you want to download.")
    else:
        logging.info("The message is not a link including Apple Music.")

#check the link is a song or a album or a playlist
async def CheckLinkType(update: Update, context):
    logging.info("Checking the link type...")
    url = update.message.text
    url_regex_result = re.search(
        r"/([a-z]{2})/(album|playlist|song|music-video)/(.*)/([a-z]{2}\..*|[0-9]*)(?:\?i=)?([0-9a-z]*)",
        url,
    )
    catalog_resource_type = url_regex_result.group(2)
    catalog_id = url_regex_result.group(5) or url_regex_result.group(4)

    if catalog_resource_type == "song" or url_regex_result.group(5):
        logging.info("The link is a song.")
        await CheckSongInSql(update, url)
    elif catalog_resource_type == "music-video":
        logging.info("The link is a music-video.")
        await update.message.reply_text("Sorry, I can't download music vedio.")
        return
    elif catalog_resource_type == "album":
        logging.info("The link is an album.")
        await CheckAlbumInSql(update, url)
    elif catalog_resource_type == "playlist":
        logging.info("The link is a playlist.")
        await CheckPlaylistInSql(update, url)
    else:
        raise Exception("Invalid URL")

#check if the song has been downloaded before from sql;
async def CheckSongInSql(update: Update, url):
    await update.message.reply_text("Finding the song in the database...")
    sql_session = get_session()
    id = parse_qs(urlparse(url).query)['i'][0]
    logging.info(f"ID: {id}")
    songs = await web_playback.get_song(session, id)
    logging.info(f"Songs: {songs}")
    try:
        song = songs[0]
        song_item = sql_session.query(musicSong).filter_by(id=song[0]).first()
        file_id = song_item.file_id
        logging.info(f"File ID: {file_id}")
        logging.info("Song found in the database.")
        await update.message.reply_audio(audio=file_id)
        logging.info("Song sent to the user.")
        return
    except:
        pass
    finally:
        sql_session.close()
    
    await download_song(update,url)
    songs = await web_playback.get_song(session, id)
    return await send_song(update, songs)


#check if the album has been downloaded before from sql;
async def CheckAlbumInSql(update: Update, url):
    await update.message.reply_text("Finding the album in the database...")
    sql_session = get_session()
    id = re.search(r"/([a-z]{2})/(album|playlist|song)/(.*)/([a-z]{2}\..*|[0-9]*)(?:\?i=)?([0-9a-z]*)", url).group(4)
    logging.info(f"ID: {id}")
    songs = await web_playback.get_album(session, id)
    logging.info(f"Songs: {songs}")
    all_songs_found = True
    try:
        for song in songs:
            song_item = sql_session.query(musicSong).filter_by(id=song[0]).first()
            if song_item is not None:
                file_id = song_item.file_id
                logging.info(f"File ID: {file_id}")
                await update.message.reply_audio(audio=file_id)
            else:
                logging.info(f"No song item found for ID: {song[0]}")
                all_songs_found = False
                continue
        if all_songs_found:
            return
    except Exception as e:
        logging.error(f"Error: {e}")
    finally:
        sql_session.close()

    await download_song(update,url)
    return await send_song(update, songs)

#check if the playlist has been downloaded before from sql;
async def CheckPlaylistInSql(update: Update ,url):
    await update.message.reply_text("Finding the album in the database...")
    sql_session = get_session()
    id = re.search(r"/([a-z]{2})/(album|playlist|song)/(.*)/([a-z]{2}\..*|[0-9]*)(?:\?i=)?([0-9a-z]*)", url).group(4)
    logging.info(f"ID: {id}")
    songs = await web_playback.get_playlist(session, id)
    logging.info(f"Songs: {songs}")
    all_songs_found = True
    try:
        for song in songs:
            song_item = sql_session.query(musicSong).filter_by(id=song[0]).first()
            if song_item is not None:
                file_id = song_item.file_id
                logging.info(f"File ID: {file_id}")
                await update.message.reply_audio(audio=file_id)
            else:
                logging.info(f"No song item found for ID: {song[0]}")
                all_songs_found = False
                continue
        if all_songs_found:
            return
    except Exception as e:
        logging.error(f"Error: {e}")
    finally:
        sql_session.close()
    
    await download_song(update, url)
    return await send_song(update, songs)

#download the song;
async def download_song(update: Update,url):
    await update.message.reply_text("Song downloading...")
    command = ["gamdl"] + [url]
    logging.info(f"Command: {' '.join(command)}")
    try:
        process = await asyncio.create_subprocess_exec(*command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await process.communicate()
        await process.wait()  
        logging.info(f"Song downloaded successfully.")
    except Exception as e:
        logging.error(f"An error occurred while downloading the song: {e}")
        return

#rename the song file;
async def rename_song_file():
    directory = "./Apple Music"  # Specify the directory to traverse
    renamed_files = []
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.endswith(".m4a"):
                # 解析出歌手名
                artist_name = os.path.basename(os.path.dirname(root))
                # 创建新的文件名
                new_file_name = f"{os.path.splitext(file)[0]} -{artist_name}.m4a"
                # 创建新的文件路径
                new_file_path = os.path.join(root, new_file_name)
                # 创建旧的文件路径
                old_file_path = os.path.join(root, file)
                # 重命名文件
                os.rename(old_file_path, new_file_path)
                # 将新的文件路径添加到列表中
                renamed_files.append(new_file_path)
    logging.info(f"Renamed files: {renamed_files}")
    return renamed_files

#delete the song file;
async def delete_song_file():
    directories = ["./Apple Music", "./temp"]
    for directory in directories:
        try:
            if os.path.exists(directory):
                shutil.rmtree(directory)
            else:
                logging.info(f"The directory {directory} does not exist")
        except PermissionError:
            logging.info("Permission denied")
        except Exception as e:
            logging.info(f"An error occurred: {e}")

#send the song to the user; 
async def send_song(update: Update, songs):
    renamed_files = await rename_song_file()
    file_id_dict = {}
    for song_path in renamed_files:
        song_name = os.path.basename(song_path)
        logging.info(f"Song_path: {song_path} Song_name: {song_name}")
        try:
            with open(song_path, 'rb') as audio_file:
                message = await update.message.reply_audio(audio=audio_file)
            file_id = message.audio.file_id
        except:
            logging.error(f"An error occurred while sending the song")
            await delete_song_file()
            break
        logging.info(f"File ID: {file_id}")
        song_name = song_name.replace('.m4a', '')
        file_id_dict[song_name] = file_id
    logging.info(f"File ID dict: {file_id_dict}")
    await SaveSongInfoToSql(file_id_dict,songs)
    

#stone the song info to sql;
async def SaveSongInfoToSql(file_id_dict, songs):
    sql_session = get_session()
    logging.info(f"songs: {songs}")
    logging.info("save song info to sql")
    logging.info(f"song info: {file_id_dict}")
    for song_name, file_id in file_id_dict.items():
        logging.info(f"Song name: {song_name} File ID: {file_id}")
        for song in songs:
            logging.info(f"Checking song: {song[1]}")
            if song[1] == song_name:
                logging.info(f"Song: {song[1]} song_name: {song_name}")
                song_id = song[0]
                logging.info(f"Song ID: {song_id}")
                existing_song = sql_session.query(musicSong).filter_by(id=song_id).first()
                if existing_song is None:
                    musicSongItem = musicSong(id=song_id, file_id=file_id)
                    logging.info(f"New song: {musicSongItem}")
                    sql_session.add(musicSongItem)
                else:
                    logging.info(f"Song with ID {song_id} already exists, skipping")
    logging.info("Song saved in the database.")

    sql_session.commit()
    sql_session.close()
    await delete_song_file()

class WebPlayback:
    def setup_session(self, cookies_location: str) -> requests.Session:
        cookies = MozillaCookieJar(cookies_location)
        cookies.load(ignore_discard=True, ignore_expires=True)
        session = requests.Session()
        session.cookies.update(cookies)
        session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:95.0) Gecko/20100101 Firefox/95.0",
                "Accept": "application/json",
                "Accept-Language": "en-US,en;q=0.5",
                "Accept-Encoding": "gzip, deflate, br",
                "content-type": "application/json",
                "Media-User-Token": session.cookies.get_dict()["media-user-token"],
                "x-apple-renewal": "true",
                "DNT": "1",
                "Connection": "keep-alive",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-site",
                "origin": "https://beta.music.apple.com",
            }
        )
        home_page = session.get("https://beta.music.apple.com").text
        index_js_uri = re.search(r"/(assets/index-legacy-[^/]+\.js)", home_page).group(
            1
        )
        index_js_page = session.get(
            f"https://beta.music.apple.com/{index_js_uri}"
        ).text
        token = re.search('(?=eyJh)(.*?)(?=")', index_js_page).group(1)
        session.headers.update({"authorization": f"Bearer {token}"})
        return session

    @retry(retry_on_exception=retry_if_connection_error, stop_max_attempt_number=5)
    async def get_song(self, session: requests.Session, song_id: str) -> list:
        response = session.get(f"https://api.music.apple.com/v1/catalog/us/songs/{song_id}")
        response_json = response.json()
        song_data = response_json["data"][0]
        song_id = song_data["id"]
        song_name = song_data["attributes"]["name"]
        artist_name = song_data["attributes"]["artistName"]
        track_number = str(song_data["attributes"]["trackNumber"]).zfill(2)

        songs = [[song_id, f"{track_number} {song_name} -{artist_name}"]]
        return songs

    @retry(retry_on_exception=retry_if_connection_error, stop_max_attempt_number=5)
    async def get_album(self, session: requests.Session, album_id: str) -> dict:
        response = session.get(f"https://api.music.apple.com/v1/catalog/us/albums/{album_id}")
        response_json = response.json()
        album_data = response_json["data"][0]
        album_songs = album_data['relationships']['tracks']['data']

        songs = []
        for song in album_songs:
            attributes = song.get('attributes', {})
            play_params = attributes.get('playParams', {})
            kind = play_params.get('kind')
            if kind != 'song':  # 如果 kind 不是 'song'，则跳过这首歌曲
                continue
            song_id = song['id']
            song_name = song['attributes']['name']
            track_number = str(song['attributes']['trackNumber']).zfill(2)
            artist_name = album_data["attributes"]["artistName"]
            song_name = f"{track_number} {song_name} - {artist_name}"
            songs.append((song_id, song_name))  # 将歌曲的 id 和名称作为一个元组添加到列表中
    
        return songs

    @retry(retry_on_exception=retry_if_connection_error, stop_max_attempt_number=5)
    async def get_playlist(self, session: requests.Session, playlist_id: str) -> dict:
        response = session.get(f"https://api.music.apple.com/v1/catalog/us/playlists/{playlist_id}")
        response_json = response.json()
        playlist_data = response_json["data"][0]
        playlist_songs = playlist_data['relationships']['tracks']['data']

        songs = []
        for song in playlist_songs:
            attributes = song.get('attributes', {})
            play_params = attributes.get('playParams', {})
            kind = play_params.get('kind')
            if kind != 'song':  # 如果 kind 不是 'song'，则跳过这首歌曲
                continue
            song_id = song['id']
            song_name = song['attributes']['name']
            track_number = str(song['attributes']['trackNumber']).zfill(2)
            artist_name = playlist_data["attributes"]["artistName"]
            song_name = f"{track_number} {song_name} - {artist_name}"
            songs.append((song_id, song_name))  # 将歌曲的 id 和名称作为一个元组添加到列表中
    
        return songs


if __name__ == '__main__':
    bot = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    bot.add_handler(CommandHandler("start", handleStartMessage))
    bot.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handleRequest))
    web_playback = WebPlayback()
    session = web_playback.setup_session("cookies.txt")
    bot.run_polling()
    logging.info("Bot application started")