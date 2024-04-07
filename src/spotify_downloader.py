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

# Set the Spotify client id and client secret;
client_id = SPOTIPY_CLIENT_ID
client_secret = SPOTIFY_CLIENT_SECRET

# Create a Spotify client;
sp = spotipy.Spotify(
    auth_manager=SpotifyClientCredentials(
        client_id=client_id, client_secret=client_secret
    )
)

async def get_url_type(update: Update, context, url):
    #check the url type
    item_type, item_id = parse_spotify_url(url)
    logging.info(f"item_type: {item_type}, item_id: {item_id}")
    if item_type is None or item_id is None:
        await update.message.reply_text("Invalid Spotify URL.")
        return
    if item_type == "playlist":
        if update.message.chat.type != "private":
            await update.message.reply_text("Please send the Spotify playlist URL in private chat.")
            return

    #get the item name
    reply_message = await update.message.reply_text(f"Finding the {item_type} in the database...")

    #get the songs list
    songs_list = fetch_tracks(sp, item_type, item_id)
    logging.info(f"Songs list: {songs_list}")

    #check the songs in the sqlite
    await check_songs_in_sql(update, songs_list, reply_message, context)



async def check_songs_in_sql(update: Update, songs_list, reply_message, context):
    not_found_count = 0
    sql_session = get_session()
    all_songs_found = True
    media_group = []
    not_found_songs = []

    #check the songs in the sqlite
    for song in songs_list:
        song_id = song['spotify_id']
        logging.info(f"Song ID: {song_id}")
        song_item = sql_session.query(spotify_music).filter(spotify_music.id == song_id).first()
        logging.info(f"Song item: {song_item}")
        if song_item is not None:
            file_id = song_item.fileId
            logging.info(f"File ID: {file_id}")

            # Use file_id build InputMediaAudio, and wait for the next step to send to user.
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

            # Split media_group into groups of 10 and send each group.
            for i in range(0, len(media_group), 10):
                sub_media_group = media_group[i:i+10]

                # Retry sending media group up to 5 times in case of failure.
                for _ in range(10):
                    try:
                        await update.message.reply_media_group(media=sub_media_group)
                        break  # If sending is successful, exit the retry loop immediately.
                    except Exception as e:
                        logging.error(f"Error: {e}")
                        if 'Timeout' in str(e):
                            time.sleep(5)
                            continue
                        break  # If the message has already been sent, exit the retry loop immediately.
                    except:
                        time.sleep(5)
        else:
            # If media_group has less than 10 items, send it directly.
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

        # if the chat type is private, send the message to the user;
        if update.message.chat.type == "private":
            await update.message.reply_text("Enjoy your music! If you like this bot, consider donating to the developer. /donate")
        return
    else:
        await reply_message.edit_text("Find out some songs and downloading the rest of the songs...")

    # If not all songs are found, download the missing songs from YouTube.
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
        # Format number as two digits
        num = "{:02}".format(i)

        # Download song
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': f"./Spotify/{song['artist']}/{num} {song['name']} - {song['artist']}",  # Use num here
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '320',
            }],
            'default_search': 'ytsearch',
            'retries': 10, # Number of retries
            'socket_timeout': 10, # Socket timeout
        }

        # Download the song from YouTube
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([f"{song['name']} {song['artist']}"])

        # Create cover directory if not exists
        if not os.path.exists('./CoverArt'):
            os.makedirs('./CoverArt')

        # Download cover
        response = requests.get(song['cover'])
        img = Image.open(BytesIO(response.content))
        safe_song_name = song['name'].replace("/", "-")  # Replace / with -
        cover_path = f"./CoverArt/{safe_song_name}.jpg"
        img.save(cover_path)

        # Add song info to downloaded_songs
        downloaded_songs.append({
            'name': song['name'],
            'artist': song['artist'],
            'song_path': f"./Spotify/{song['artist']}/{num} {song['name']} - {song['artist']}.mp3",  # Use num here
            'cover_path': cover_path,
            'spotify_id': song['spotify_id']
        })
        downloaded_count += 1
        await reply_message.edit_text(f"Downloaded {downloaded_count}/{not_found_count} songs from YouTube...")

        # If 10 songs have been downloaded, send them and clear the list
        if downloaded_count % 10 == 0:
            await send_song(update, media_group, downloaded_songs, downloaded_count, reply_message, context)
            # Clear the list
            downloaded_songs = []

    # Send any remaining songs
    if downloaded_songs:
        await send_song(update, media_group, downloaded_songs, downloaded_count, reply_message, context)

    await delete_files()
    await reply_message.delete()

    # if the chat type is private, send the message to the user;
    if update.message.chat.type == "private":
        await update.message.reply_text("Enjoy your music! If you like this bot, consider donating to the developer. /donate")
    return 

async def send_song(update, media_group, downloaded_songs, not_found_count, reply_message, context):

    # Based on the number of songs, send the song to the user;
    if not_found_count == 1:
        file_id_dict = await send_singe_song(update, downloaded_songs, reply_message)
    else:
        file_id_dict = await send_group_songs(update, downloaded_songs, reply_message, media_group, context)

    logging.info(f"File ID dict: {file_id_dict}")


    # Save the song info to sql;    
    await save_song_info_to_sql(file_id_dict)

async def send_singe_song(update, downloaded_songs, reply_message):
    file_id_dict = {}
    for song in downloaded_songs:

        # Get the song info
        song_path = song['song_path']
        cover_path = song['cover_path']
        song_name = song['name']
        artist_name = song['artist']
        song_id = song['spotify_id']
        logging.info(f"Sending song_path {song_path} cover_path {cover_path} song_name {song_name} artist_name {artist_name} song_id {song_id}")
        
        # Get the audio duration
        audio = AudioSegment.from_file(song_path)
        duration = audio.duration_seconds

        # Send the song to the user
        message = await update.message.reply_audio(audio=song_path, thumbnail=cover_path, duration=duration, performer=artist_name, title=song_name)

        # Get the file_id
        file_id = message.audio.file_id
        file_id_dict[song_id] = file_id

    return file_id_dict

async def send_group_songs(update, downloaded_songs, reply_message, media_group, context):
    file_id_dict = {}
    prosess = 0

    if len(media_group) > 10:
        # Split media_group into groups of 10 and send each group.
        for i in range(0, len(media_group), 10):
            sub_media_group = media_group[i:i+10]

            # Retry sending media group up to 5 times in case of failure.
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

    # Send the songs to the user
    for song in downloaded_songs:
        try:

            # Get the song info
            song_path = song['song_path']
            cover_path = song['cover_path']
            song_name = song['name']
            artist_name = song['artist']
            song_id = song['spotify_id']

            logging.info(f"Sending song_path {song_path} cover_path {cover_path} song_name {song_name} artist_name {artist_name} song_id {song_id}")
            # Get the audio duration
            audio = AudioSegment.from_file(song_path)
            duration = audio.duration_seconds

            # Send the song to the user
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

            # Use file_id build InputMediaAudio.
            media = InputMediaAudio(media=file_id)
            media_group.append(media)
            file_id_dict[song_id] = file_id
            logging.info(f"File ID: {file_id}")
            prosess += 1
            await reply_message.edit_text(f"Loading {prosess}.")

            # If media_group has 10 items, send them and clear media_group.
            if len(media_group) == 10:
                for _ in range(5):
                    try:
                        # If media_group has 10 items, send them and clear media_group.
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

    # Send remaining songs in media_group.
    if media_group:

        # deal with the time out error
        for _ in range(3):
            try:
                logging.info(f"Media group: {media_group}")
                await update.message.reply_media_group(media=media_group)
                break
            except Exception as e:
                logging.error(f"error: {e}")

                # If the error is a timeout error, wait for 5 seconds and try again.
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

        # Check if the song exists;
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

    
# Delete the files;
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