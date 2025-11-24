#!/usr/bin/env python3
from config import SPOTIPY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, TELEGRAM_CHANNEL_ID
import time, requests, yt_dlp, json, sys, logging, spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from database import spotify_music, get_session
from telegram import Update, InputMediaAudio
from telegram.ext import CallbackContext
from sqlalchemy.orm import sessionmaker
from pathlib import Path, PurePath
from pydub import AudioSegment
from io import BytesIO
from PIL import Image
import os,shutil
import asyncio
from spotify import (
    fetch_tracks,
    parse_spotify_url,
    get_item_name,
)

client_id = SPOTIPY_CLIENT_ID
client_secret = SPOTIFY_CLIENT_SECRET

sp = spotipy.Spotify(
    auth_manager=SpotifyClientCredentials(
        client_id=client_id, client_secret=client_secret
    )
)

async def get_url_type(update: Update, context, url):
    item_type, item_id = parse_spotify_url(url)
    logging.info(f"item_type: {item_type}, item_id: {item_id}")
    if item_type is None or item_id is None:
        await update.message.reply_text("Invalid Spotify URL.")
        return
    if item_type == "playlist":
        if update.message.chat.type != "private":
            await update.message.reply_text("Please send the Spotify playlist URL in private chat.")
            return

    reply_message = await update.message.reply_text(f"Finding the {item_type} in the database...")

    songs_list = fetch_tracks(sp, item_type, item_id)
    logging.info(f"Songs list: {songs_list}")

    await check_songs_in_sql(update, songs_list, reply_message, context)



async def check_songs_in_sql(update: Update, songs_list, reply_message, context):
    not_found_count = 0
    sql_session = get_session()
    all_songs_found = True
    media_group = []
    not_found_songs = []

    for song in songs_list:
        song_id = song['spotify_id']
        logging.info(f"Song ID: {song_id}")
        song_item = sql_session.query(spotify_music).filter(spotify_music.id == song_id).first()
        logging.info(f"Song item: {song_item}")
        if song_item is not None:
            file_id = song_item.fileId
            logging.info(f"File ID: {file_id}")

            media = InputMediaAudio(media=file_id)
            media_group.append(media)
        else:
            not_found_count += 1
            logging.info(f"No song item found for ID: {song['spotify_id']}")
            not_found_songs.append({'name': song['name'], 'artist': song['artist'], 'cover': song['cover'], 'spotify_id': song['spotify_id']})
            all_songs_found = False
            continue
    if all_songs_found:
        if len(media_group) > 10:

            for i in range(0, len(media_group), 10):
                sub_media_group = media_group[i:i+10]

                for _ in range(10):
                    try:
                        await update.message.reply_media_group(media=sub_media_group)
                        break
                    except Exception as e:
                        logging.error(f"Error: {e}")
                        if 'Timeout' in str(e):
                            time.sleep(5)
                            continue
                        break
                    except:
                        time.sleep(5)
        else:
            for _ in range(5):
                try:
                    await update.message.reply_media_group(media=media_group)
                    break
                except Exception as e:
                    logging.error(f"Error: {e}")
                    if 'Timeout' in str(e):
                        time.sleep(5)
                        continue
                    break
                except:
                    time.sleep(5)

        await reply_message.delete()

        if update.message.chat.type == "private":
            await update.message.reply_text("Enjoy your music! If you like this bot, consider donating to the developer. /donate")
        return
    else:
        await reply_message.edit_text("Find out some songs and downloading the rest of the songs...")

    sql_session.close()
    await download_songs(update, media_group, not_found_songs, not_found_count, reply_message, context)
        

async def download_songs(update: Update, media_group, not_found_songs, not_found_count, reply_message, context):
    if not_found_count == 1:
        await reply_message.edit_text("Downloading song from YouTube...")
    else:
        await reply_message.edit_text(f"Downloading {not_found_count} songs from YouTube...")
    downloaded_count = 0
    downloaded_songs = []
    for i, song in enumerate(not_found_songs, start=1):
        num = "{:02}".format(i)

        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': f"./Spotify/{song['artist']}/{num} {song['name']} - {song['artist']}",
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '320',
            }],
            'default_search': 'ytsearch',
            'retries': 10,
            'socket_timeout': 10,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([f"{song['name']} {song['artist']}"])

        if not os.path.exists('./CoverArt'):
            os.makedirs('./CoverArt')

        response = requests.get(song['cover'])
        img = Image.open(BytesIO(response.content))
        safe_song_name = song['name'].replace("/", "-")
        cover_path = f"./CoverArt/{safe_song_name}.jpg"
        img.save(cover_path)

        downloaded_songs.append({
            'name': song['name'],
            'artist': song['artist'],
            'song_path': f"./Spotify/{song['artist']}/{num} {song['name']} - {song['artist']}.mp3",
            'cover_path': cover_path,
            'spotify_id': song['spotify_id']
        })
        downloaded_count += 1
        await reply_message.edit_text(f"Downloaded {downloaded_count}/{not_found_count} songs from YouTube...")

        if downloaded_count % 10 == 0:
            await send_song(update, media_group, downloaded_songs, downloaded_count, reply_message, context)
            downloaded_songs = []

    if downloaded_songs:
        await send_song(update, media_group, downloaded_songs, downloaded_count, reply_message, context)

    await delete_files()
    await reply_message.delete()

    if update.message.chat.type == "private":
        await update.message.reply_text("Enjoy your music! If you like this bot, consider donating to the developer. /donate")
    return

async def send_song(update, media_group, downloaded_songs, not_found_count, reply_message, context):

    if not_found_count == 1:
        file_id_dict = await send_singe_song(update, downloaded_songs, reply_message)
    else:
        file_id_dict = await send_group_songs(update, downloaded_songs, reply_message, media_group, context)

    logging.info(f"File ID dict: {file_id_dict}")

    await save_song_info_to_sql(file_id_dict)

async def send_singe_song(update, downloaded_songs, reply_message):
    file_id_dict = {}
    for song in downloaded_songs:

        song_path = song['song_path']
        cover_path = song['cover_path']
        song_name = song['name']
        artist_name = song['artist']
        song_id = song['spotify_id']
        logging.info(f"Sending song_path {song_path} cover_path {cover_path} song_name {song_name} artist_name {artist_name} song_id {song_id}")

        audio = AudioSegment.from_file(song_path)
        duration = audio.duration_seconds

        message = await update.message.reply_audio(audio=song_path, thumbnail=cover_path, duration=duration, performer=artist_name, title=song_name)

        file_id = message.audio.file_id
        file_id_dict[song_id] = file_id

    return file_id_dict

async def send_group_songs(update, downloaded_songs, reply_message, media_group, context):
    file_id_dict = {}
    prosess = 0

    if len(media_group) > 10:
        for i in range(0, len(media_group), 10):
            sub_media_group = media_group[i:i+10]

            for _ in range(10):
                try:
                    await update.message.reply_media_group(media=sub_media_group)
                    break
                except Exception as e:
                    logging.error(f"Error: {e}")
                    if 'Timeout' in str(e):
                        time.sleep(5)
                        continue
                    break
                except:
                    time.sleep(5)
        media_group.clear()

    for song in downloaded_songs:
        try:

            song_path = song['song_path']
            cover_path = song['cover_path']
            song_name = song['name']
            artist_name = song['artist']
            song_id = song['spotify_id']

            logging.info(f"Sending song_path {song_path} cover_path {cover_path} song_name {song_name} artist_name {artist_name} song_id {song_id}")
            audio = AudioSegment.from_file(song_path)
            duration = audio.duration_seconds

            for _ in range(5):
                try:
                    message = await context.bot.send_audio(chat_id=TELEGRAM_CHANNEL_ID, audio=song_path, thumbnail=cover_path, duration=duration, performer=artist_name, title=song_name)
                    file_id = message.audio.file_id
                    break
                except Exception as e:
                    logging.error(f"Error: {e}")
                    if 'Timeout' in str(e):
                        time.sleep(5)
                        continue

            media = InputMediaAudio(media=file_id)
            media_group.append(media)
            file_id_dict[song_id] = file_id
            logging.info(f"File ID: {file_id}")
            prosess += 1
            await reply_message.edit_text(f"Loading {prosess}.")

            if len(media_group) == 10:
                for _ in range(5):
                    try:
                        await update.message.reply_media_group(media=media_group)
                        media_group.clear()
                        break
                    except Exception as e:
                        logging.error(f"error: {e}")
                        if 'Timeout' in str(e):
                            time.sleep(5)
                            continue
                    except:
                        time.sleep(5)
                        continue
        except:
            logging.error(f"An error occurred while sending the song", exc_info=True)
    logging.info(f"Media group: {media_group}")

    await reply_message.edit_text("Loaded successfully, sending to you!")

    if media_group:

        for _ in range(3):
            try:
                logging.info(f"Media group: {media_group}")
                await update.message.reply_media_group(media=media_group)
                break
            except Exception as e:
                logging.error(f"error: {e}")

                if 'Timeout' in str(e):
                    time.sleep(5)
                    continue
            except:
                logging.error(f"An error occurred while sending the song", exc_info=True)
                time.sleep(5)
                continue

    logging.info(f"File ID dict: {file_id_dict}")
    return file_id_dict


async def save_song_info_to_sql(file_id_dict):
    sql_session = get_session()
    logging.info(f"File ID dict: {file_id_dict}")

    for spotify_id, file_id in file_id_dict.items():

        existing_song = sql_session.query(spotify_music).filter(id == spotify_id).first()

        if existing_song is None:
            song_item = spotify_music(id=spotify_id, fileId=file_id)
            logging.info(f"Saving song with ID {spotify_id} to the database.")
            sql_session.add(song_item)
        else:
            logging.info(f"Song with ID {song_id} already exists, skipping")
    
    logging.info("Song saved in the database.")
    sql_session.commit()
    sql_session.close()

async def delete_files():
    directories = ["./Spotify", "./CoverArt"]
    for directory in directories:
        try:
            if os.path.exists(directory):
                shutil.rmtree(directory)
                logging.info(f"The directory {directory} has been deleted")
            else:
                logging.info(f"The directory {directory} does not exist")
        except PermissionError:
            logging.info("Permission denied")
        except Exception as e:
            logging.info(f"An error occurred: {e}")