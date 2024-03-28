#!/usr/bin/env python3
from config import SPOTIPY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, TELEGRAM_CHANNEL_ID
import time, requests, yt_dlp, json, sys, logging, spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from Database import spotifyMusic, get_session
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

async def GetUrlType(update: Update, context):
    url = update.message.text
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
    replyMessage = await update.message.reply_text(f"Finding the {item_type} in the database...")

    #get the songs list
    songsList = fetch_tracks(sp, item_type, item_id)
    logging.info(f"Songs list: {songsList}")

    #check the songs in the sqlite
    await CheckSongsInSql(update, songsList, replyMessage, context)



async def CheckSongsInSql(update: Update, songsList, replyMessage, context):
    notFoundCount = 0
    sql_session = get_session()
    allSongsFound = True
    mediaGroup = []
    notfoundsongs = []
    #check the songs in the sqlite
    for song in songsList:
        songId = song['spotify_id']
        logging.info(f"Song ID: {songId}")
        song_item = sql_session.query(spotifyMusic).filter(spotifyMusic.id == songId).first()
        logging.info(f"Song item: {song_item}")
        if song_item is not None:
            fileId = song_item.fileId
            logging.info(f"File ID: {fileId}")
            # Use fileId build InputMediaAudio, and wait for the next step to send to user.
            media = InputMediaAudio(media=fileId)
            mediaGroup.append(media)
        else:
            notFoundCount += 1
            logging.info(f"No song item found for ID: {song['spotify_id']}")
            notfoundsongs.append({'name': song['name'], 'artist': song['artist'], 'cover': song['cover'], 'spotifyId': song['spotify_id']})
            allSongsFound = False
            continue
    if allSongsFound:
        if len(mediaGroup) > 10:
            # Split mediaGroup into groups of 10 and send each group.
            for i in range(0, len(mediaGroup), 10):
                subMediaGroup = mediaGroup[i:i+10]

                # Retry sending media group up to 5 times in case of failure.
                for _ in range(5):
                    try:
                        await update.message.reply_media_group(media=subMediaGroup)
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
            # If mediaGroup has less than 10 items, send it directly.
            for _ in range(5):
                try:
                    await update.message.reply_media_group(media=mediaGroup)
                    break
                except Exception as e:
                    logging.error(f"Error: {e}")
                    if 'Timeout' in str(e):
                        time.sleep(5)
                        continue
                    break
                except:
                    time.sleep(5)

        await replyMessage.delete()
        
        if update.message.chat.type == "private":
            await update.message.reply_text("Enjoy your music! If you like this bot, consider donating to the developer. /donate")
        return
    else:
        await replyMessage.edit_text("Find out some songs and downloading the rest of the songs...")

    sql_session.close()
    await downloadSongs(update, mediaGroup, notfoundsongs, notFoundCount, replyMessage, context)
        

async def downloadSongs(update: Update, mediaGroup, notfoundsongs, notFoundCount, replyMessage, context):
    if notFoundCount == 1:
        return await replyMessage.edit_text("Downloading song from YouTube...")
    else:
        await replyMessage.edit_text(f"Downloading {notFoundCount} songs from YouTube...")
    downloadedCount = 0
    downloadedSongs = []
    for i, song in enumerate(notfoundsongs, start=1):
        # Format number as two digits
        num = "{:02}".format(i)

        # Download song
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': f"./Spotify/{song['artist']}/{num} {song['name']} - {song['artist']}",  # Use num here
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'default_search': 'ytsearch',
            'retries': 10,
            'socket_timeout': 10,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([f"{song['name']} {song['artist']}"])

        # Create cover directory if not exists
        if not os.path.exists('./CoverArt'):
            os.makedirs('./CoverArt')

        # Download cover
        response = requests.get(song['cover'])
        img = Image.open(BytesIO(response.content))
        safe_song_name = song['name'].replace("/", "-")  # Replace / with -
        coverPath = f"./CoverArt/{safe_song_name}.jpg"
        img.save(coverPath)

        # Add song info to downloadedSongs
        downloadedSongs.append({
            'name': song['name'],
            'artist': song['artist'],
            'songPath': f"./Spotify/{song['artist']}/{num} {song['name']} - {song['artist']}.mp3",  # Use num here
            'coverPath': coverPath,
            'spotifyId': song['spotifyId']
        })
        downloadedCount += 1
        await replyMessage.edit_text(f"Downloaded {downloadedCount}/{notFoundCount} songs from YouTube...")

        # If 10 songs have been downloaded, send them and clear the list
        if downloadedCount % 10 == 0:
            await sendSong(update, mediaGroup, downloadedSongs, downloadedCount, replyMessage, context)
            downloadedSongs = []

    # Send any remaining songs
    if downloadedSongs:
        await sendSong(update, mediaGroup, downloadedSongs, downloadedCount, replyMessage, context)

    await delete_files()
    if update.message.chat.type == "private":
        await update.message.reply_text("Enjoy your music! If you like this bot, consider donating to the developer. /donate")
    return 

async def sendSong(update, mediaGroup, downloadedSongs, notFoundCount, replyMessage, context):

    # Based on the number of songs, send the song to the user;
    if notFoundCount == 1:
        fileIdDict = await sendSingeSong(update, downloadedSongs, replyMessage)
    else:
        fileIdDict = await sendGroupSongS(update, downloadedSongs, replyMessage, mediaGroup, context)

    logging.info(f"File ID dict: {fileIdDict}")


    # Save the song info to sql;    
    await SaveSongInfoToSql(fileIdDict)

async def sendSingeSong(update, downloadedSongs, replyMessage):
    fileIdDict = {}
    for song in downloadedSongs:
        songPath = song['songPath']
        coverPath = song['coverPath']
        songName = song['name']
        artistName = song['artist']
        songId = song['spotifyId']
        logging.info(f"Sending songpath {songPath} coverpath {coverPath} songname {songName} artistname {artistName} songid {songId}")
        # Get the audio duration
        audio = AudioSegment.from_file(songPath)
        duration = audio.duration_seconds

        # Send the song to the user
        message = await update.message.reply_audio(audio=songPath, thumbnail=coverPath, duration=duration, performer=artistName, title=songName)

        # Get the fileId
        fileId = message.audio.file_id
        fileIdDict[songId] = fileId
    return fileIdDict

async def sendGroupSongS(update, downloadedSongs, replyMessage, mediaGroup, context):
    fileIdDict = {}
    prosess = 0

    if len(mediaGroup) > 11:
        # Split mediaGroup into groups of 10 and send each group.
        for i in range(0, len(mediaGroup), 10):
            subMediaGroup = mediaGroup[i:i+10]

            # Retry sending media group up to 5 times in case of failure.
            for _ in range(5):
                try:
                    await update.message.reply_media_group(media=subMediaGroup)
                    break
                except Exception as e:
                    logging.error(f"Error: {e}")
                    if 'Timeout' in str(e):
                        time.sleep(5)
                        continue
                    break
                except:
                    time.sleep(5)
        mediaGroup.clear()


    for song in downloadedSongs:
        try:
            songPath = song['songPath']
            coverPath = song['coverPath']
            songName = song['name']
            artistName = song['artist']
            songId = song['spotifyId']

            logging.info(f"Sending songpath {songPath} coverpath {coverPath} songname {songName} artistname {artistName} songid {songId}")
            # Get the audio duration
            audio = AudioSegment.from_file(songPath)
            duration = audio.duration_seconds

            # Send the song to the user
            for _ in range(5):
                try:
                    message = await context.bot.send_audio(chat_id=TELEGRAM_CHANNEL_ID, audio=songPath, thumbnail=coverPath, duration=duration, performer=artistName, title=songName)
                    fileId = message.audio.file_id
                    break
                except Exception as e:
                    logging.error(f"Error: {e}")
                    if 'Timeout' in str(e):
                        time.sleep(5)
                        continue

            # Use fileId build InputMediaAudio.
            media = InputMediaAudio(media=fileId)
            mediaGroup.append(media)
            fileIdDict[songId] = fileId
            logging.info(f"File ID: {fileId}")
            prosess += 1
            await replyMessage.edit_text(f"Loading {prosess}.")

            if len(mediaGroup) == 10:
                for _ in range(5):
                    try:
                        # If mediaGroup has 10 items, send them and clear mediaGroup.
                        await update.message.reply_media_group(media=mediaGroup)
                        mediaGroup.clear()
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
    logging.info(f"Media group: {mediaGroup}")

    await replyMessage.edit_text("Loaded successfully, sending to you!")
    # Send remaining songs in mediaGroup.
    if mediaGroup:
        for _ in range(3):
            try:
                logging.info(f"Media group: {mediaGroup}")
                await update.message.reply_media_group(media=mediaGroup)
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

    logging.info(f"File ID dict: {fileIdDict}")
    return fileIdDict


async def SaveSongInfoToSql(fileIdDict):
    sql_session = get_session()
    logging.info(f"File ID dict: {fileIdDict}")

    for spotifyId, fileId in fileIdDict.items():
        # Check if the song exists;
        existing_song = sql_session.query(spotifyMusic).filter(id == spotifyId).first()
        if existing_song is None:
            song_item = spotifyMusic(id=spotifyId, fileId=fileId)
            logging.info(f"Saving song with ID {spotifyId} to the database.")
            sql_session.add(song_item)
        else:
            logging.info(f"Song with ID {songId} already exists, skipping")
    
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