from AppleMusicDownloader import Downloader
from urllib.parse import urlparse, parse_qs
from telegram import Update, InputMediaAudio
from telegram.ext import CallbackContext
from Database import appleMusic, get_session
from sqlalchemy.orm import sessionmaker
from config import TELEGRAM_CHANNEL_ID
from get_cover_art import CoverFinder
from pydub import AudioSegment
from pathlib import Path
import subprocess, re
import time, shutil
import json, glob
import requests
import asyncio
import logging
import os

# Configure the downloader;
downloader = Downloader()
# Configure the session;
downloader.setup_session()
# Configure the CDM;
downloader.setup_cdm()

class AppleMusicChecker:

    # Check the link type;
    async def CheckLinkType(self, update: Update, context, url):
        logging.info("Checking the link type...")
        url_regex_result = re.search(
            r"/([a-z]{2})/(album|playlist|song|music-video)/(.*)/([a-z]{2}\..*|[0-9]*)(?:\?i=)?([0-9a-z]*)",
            url,
        )
        catalog_resource_type = url_regex_result.group(2)
        catalog_id = url_regex_result.group(5) or url_regex_result.group(4)

        # Check the link type;
        if catalog_resource_type == "song" or url_regex_result.group(5):
            logging.info("The link is a song.")
            await self.CheckSongInSql(update, url, context)
        # Ignone music-video;
        elif catalog_resource_type == "music-video":
            logging.info("The link is a music-video.")
            await update.message.reply_text("Sorry, I can't download music vedio.")
            return
        elif catalog_resource_type == "album":
            logging.info("The link is an album.")
            await self.CheckAlbumInSql(update, url, context)
        # Ignone playlist in group chat;
        elif catalog_resource_type == "playlist":
            if update.message.chat.type == "private":
                logging.info("The link is a playlist.")
                await self.CheckPlaylistInSql(update, url, context)
            else:
                await update.message.reply_text("Sorry, I can't download playlist in group chat.")
        else:
            raise Exception("Invalid URL")

    # Check if the song has been downloaded before from sql;
    async def CheckSongInSql(self, update: Update, url, context):
        replyMessage = await update.message.reply_text("Finding the song in the database...")
        sql_session = get_session()
        id = parse_qs(urlparse(url).query)['i'][0]
        logging.info(f"ID: {id}")
        notFoundSong = []
        mediaGroup = []
        # Check if the song has been downloaded before from sql;
        try:
            notFoundCount = 0
            songItem = sql_session.query(appleMusic).filter_by(id=id).first()
            if songItem is not None:
                fileId = songItem.fileId
                logging.info(f"File ID: {fileId}")
                logging.info("Song found in the database.")
                await update.message.reply_audio(audio=fileId)
                logging.info("Song sent to the user.")
                await replyMessage.edit_text("Find out, sent to you!")
                await replyMessage.delete()
                if update.message.chat.type == "private":
                    await update.message.reply_text("Enjoy your music! If you like this bot, consider donating to the developer. /donate")
                return
            else:
                songNotFoundId = id
                notFoundCount += 1
                # Remember the song that was not found;
                notFoundSong.append((songNotFoundId))
                logging.info(f"No song item found for ID: {id}")
        except:
            pass
        finally:
            sql_session.close()
        await self.DownloadSong(update, replyMessage, notFoundSong, notFoundCount, context, mediaGroup)


    # Check if the album has been downloaded before from sql;
    async def CheckAlbumInSql(self, update: Update, url, context):
        replyMessage = await update.message.reply_text("Finding the album in the database...")
        sql_session = get_session()
        id = re.search(r"/([a-z]{2})/(album|playlist|song)/(.*)/([a-z]{2}\..*|[0-9]*)(?:\?i=)?([0-9a-z]*)", url).group(4)
        logging.info(f"ID: {id}")
        # Get the songs info;
        songs = await downloader.GetAlbum(id)
        logging.info(f"Songs: {songs}")
        allSongsFound = True
        notFoundSong = []
        try:
            mediaGroup = []
            notFoundCount = 0  
            for songId in songs:
                songItem = sql_session.query(appleMusic).filter_by(id=songId).first()
                if songItem is not None:
                    fileId = songItem.fileId
                    logging.info(f"File ID: {fileId}")
                    # Use fileId build InputMediaAudio, and wait for the next step to send to user.
                    media = InputMediaAudio(media=fileId)
                    mediaGroup.append(media)
                else:
                    # Remember the song that was not found;
                    songNotFoundId = songId
                    notFoundSong.append((songNotFoundId))
                    logging.info(f"No song item found for ID: {songId}")
                    notFoundCount += 1  
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
        except Exception as e:
            logging.error(f"Error: {e}")
        finally:
            sql_session.close()

        await self.DownloadSong(update, replyMessage, notFoundSong, notFoundCount, context, mediaGroup)

    # Check if the playlist has been downloaded before from sql;    
    async def CheckPlaylistInSql(self, update: Update, url, context):
        replyMessage = await update.message.reply_text("Finding the playlist in the database...")
        sql_session = get_session()
        id = re.search(r"/([a-z]{2})/(album|playlist|song)/(.*)/([a-z]{2}\..*|[0-9]*)(?:\?i=)?([0-9a-z]*)", url).group(4)
        logging.info(f"ID: {id}")
        # Get the songs info;
        songs = await downloader.GetPlaylist(id)
        logging.info(f"Songs: {songs}")
        allSongsFound = True
        notFoundSong = []
        try:
            mediaGroup = []
            notFoundCount = 0  # 添加计数器
            for songId in songs:
                songItem = sql_session.query(appleMusic).filter_by(id=songId).first()
                if songItem is not None:
                    fileId = songItem.fileId
                    logging.info(f"File ID: {fileId}")
                    # Use fileId build InputMediaAudio, and wait for the next step to send to user.
                    media = InputMediaAudio(media=fileId)
                    mediaGroup.append(media)
                else:
                    # Remember the song that was not found;
                    songNotFoundId = songId
                    notFoundSong.append((songNotFoundId))
                    logging.info(f"No song item found for ID: {songId}")
                    notFoundCount += 1
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
                                continue
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
                await replyMessage.edit_text("Find out some songs, senting to you! and downloading the rest of the songs...")
        except Exception as e:
            logging.error(f"Error: {e}")
        finally:
            sql_session.close()
        logging.info(f"notFoundSong: {notFoundSong}")
        await self.DownloadSong(update, replyMessage, notFoundSong, notFoundCount, context, mediaGroup)

    # Download the song;
    async def DownloadSong(self, update: Update, replyMessage, notFoundSong, notFoundCount, context, mediaGroup):
        notFoundCountTotal = 0
        if notFoundCount == 1:
            await replyMessage.edit_text("Donwloading the song...")
        else:
            await replyMessage.edit_text(f"Donwloading {notFoundCountTotal}/{notFoundCount} songs...")

        # Download the not found song;
        songs = []
        for track_id in notFoundSong:
            logging.info(f"Downloading song {track_id}...")
            try:
                # Get the song info;
                webplayback = downloader.get_webplayback(track_id)

                # Get the cover art;
                cover_url = downloader.get_cover_url(webplayback)

                # Get the tags;
                tags = downloader.get_tags_song(webplayback)

                # Save the cover art;
                save_cover = downloader.save_cover(tags, cover_url)
                final_location = downloader.get_final_location(tags)

                # Add the song info to the list;
                songs.append((track_id, final_location, save_cover, tags['title'], tags['artist']))
                logging.info(f"track_id: {track_id}, final_location: {final_location}, save_cover: {save_cover}, title: {tags['title']}, artistName: {tags['artist']}")

                # Get the stream url;
                stream_url = downloader.get_stream_url_song(webplayback)

                # Get the decryption key;
                decryption_key = downloader.get_decryption_key_song(stream_url, track_id)

                # Download the song;
                encrypted_location = downloader.get_encrypted_location_audio(track_id)
                downloader.download_ytdlp(encrypted_location, stream_url)

                # Decrypt the song;
                decrypted_location = downloader.get_decrypted_location_audio(track_id)            
                fixed_location = downloader.get_fixed_location(track_id, ".m4a")
                downloader.fixup_song_ffmpeg(encrypted_location, decryption_key, fixed_location)

                # Move the song to the final location;
                downloader.move_to_final_location(fixed_location, final_location)
                notFoundCountTotal += 1

                # Update the message;
                await replyMessage.edit_text(f"Donwloading {notFoundCountTotal}/{notFoundCount} songs...")

                if notFoundCountTotal % 10 == 0:
                    await self.SendSong(update, songs, replyMessage, notFoundCount, mediaGroup, context)
                    songs = []
            except Exception as e:
                logging.error(f"Failed to get song {track_id}: {e}")
        if songs:
            await self.SendSong(update, songs, replyMessage, notFoundCount, mediaGroup, context)
        logging.info("Downloaded the song.")
        downloader.cleanup_temp_path()
        # Delete the song file;
        await self.DeleteSongFile()
        if update.message.chat.type == "private":
            await update.message.reply_text("Enjoy your music! If you like this bot, consider donating to the developer. /donate")

        return

    # Delete the song file;
    async def DeleteSongFile(self):
        directories = ["./Apple Music", "./temp", "./CoverArt"]
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

    # Send the song to the user; 
    async def SendSong(self, update: Update, songs, replyMessage, notFoundCount, mediaGroup, context):
        await replyMessage.edit_text("Download successfully, sending to you! ")

        # Based on the number of songs, send the song to the user;
        if notFoundCount == 1:
            fileIdDict = await self.SendSingeSong(update, songs, replyMessage)
        else:
            fileIdDict = await self.SendGroupSong(update, songs, replyMessage, mediaGroup, context)

        logging.info(f"File ID dict: {fileIdDict}")

        # Save the song info to sql;    
        await self.SaveSongInfoToSql(fileIdDict)
    
    # Send the single song to the user;
    async def SendSingeSong(self, update: Update, songs, replyMessage):
        try:
            fileIdDict = {}
            for songId, songPath, coverArtPath, songName, artistName in songs:
               
                # Get the audio duration;
                audiotime = AudioSegment.from_file(songPath)
                duration = audiotime.duration_seconds
                
                logging.info(f"audio={songPath}, thumbnail={coverArtPath}, duration={duration}, performer={artistName}, title={songName}")
                # Send the song to the user;
                for _ in range(5):
                    try:
                        message = await update.message.reply_audio(audio=songPath, thumbnail=coverArtPath, duration=duration, performer=artistName, title=songName)
                        # Get the fileId;
                        fileId = message.audio.file_id
                        fileIdDict[songId] = fileId
                        break
                    except Exception as e:
                        logging.error(f"Error: {e}")
                        if 'Timeout' in str(e):
                            time.sleep(5)
                            continue
                        break
                    except:
                        time.sleep(5)
                        continue
        
            return fileIdDict
        except:
            logging.error(f"An error occurred while sending the song")
            return {}

    # Send the group song to the user;
    async def SendGroupSong(self, update: Update, songs, replyMessage, mediaGroup, context):
        fileIdDict = {}
        prosess = 0

        # if the mediaGroup has more than 10 items, send the mediaGroup first and clear the mediaGroup.
        if len(mediaGroup) > 10:
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

        for songId, songPath, coverArtPath, songName, artistName in songs:
            try:
                # Get the audio duration;
                audio = AudioSegment.from_file(songPath)
                duration = audio.duration_seconds

                # Send to channel one byu one，and get fileId.
                for _ in range(5):
                    try:
                        message = await context.bot.send_audio(chat_id=TELEGRAM_CHANNEL_ID, audio=songPath, thumbnail=coverArtPath, duration=duration, performer=artistName, title=songName)
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

    #stone the song info to sql;
    async def SaveSongInfoToSql(self, fileIdDict):
        sql_session = get_session()

        logging.info(f"song info: {fileIdDict}")

        # Get the song info;    
        for songId, fileId in fileIdDict.items():
            # Check if the song exists;
            existing_song = sql_session.query(appleMusic).filter_by(id=songId).first()
            if existing_song is None:
                appleMusicItem = appleMusic(id=songId, fileId=fileId)
                logging.info(f"New song: {appleMusicItem}")
                sql_session.add(appleMusicItem)
                logging.info(f"Saveing the {songId} fileId {fileId}saved in the database.")
            else:
                logging.info(f"Song with ID {songId} already exists, skipping")
        logging.info("Song saved in the database.")

        sql_session.commit()
        sql_session.close()

