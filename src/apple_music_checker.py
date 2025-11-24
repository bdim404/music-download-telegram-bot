from apple_music_downloader import Downloader
from urllib.parse import urlparse, parse_qs
from telegram import Update, InputMediaAudio
from telegram.ext import CallbackContext
from database import apple_music, get_session
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

downloader = Downloader()
downloader.setup_session()
downloader.setup_cdm()

class AppleMusicChecker:

    async def check_link_type(self, update: Update, context, url):
        logging.info("Checking the link type...")
        url = await downloader.get_final_url(url)
        logging.info(f"Final URL: {url}")
        url_regex_result = re.search(
            r"/([a-z]{2})/(album|playlist|song|music-video)/(.*)/([a-z]{2}\..*|[0-9]*)(?:\?i=)?([0-9a-z]*)",
            url,
        )
        catalog_resource_type = url_regex_result.group(2)
        catalog_id = url_regex_result.group(5) or url_regex_result.group(4)

        if catalog_resource_type == "song" or url_regex_result.group(5):
            logging.info("The link is a song.")
            await self.check_song_in_sql(update, url, context)

        elif catalog_resource_type == "music-video":
            logging.info("The link is a music-video.")
            await update.message.reply_text("Sorry, I can't download music vedio.")
            return
        elif catalog_resource_type == "album":
            logging.info("The link is an album.")
            await self.check_album_in_sql(update, url, context)

        elif catalog_resource_type == "playlist":
            if update.message.chat.type == "private":
                logging.info("The link is a playlist.")
                await self.check_playlist_in_sql(update, url, context)
            else:
                await update.message.reply_text("Sorry, I can't download playlist in group chat.")
        else:
            raise Exception("Invalid URL")

    async def check_song_in_sql(self, update: Update, url, context):
        reply_message = await update.message.reply_text("Finding the song in the database...")

        sql_session = get_session()

        parsed_url = urlparse(url)

        if '/song/' in parsed_url.path:
            path_parts = parsed_url.path.split('/')
            id = path_parts[-1] if len(path_parts) > 1 else None
        else:
            params = parse_qs(parsed_url.query)
            id = params['i'][0] if 'i' in params else None

        logging.info(f"ID: {id}")
        not_found_song = []
        media_group = []

        try:
            not_found_fount = 0

            song_item = sql_session.query(apple_music).filter_by(id=id).first()
            if song_item is not None:

                file_id = song_item.fileId
                logging.info(f"File ID: {file_id}")
                logging.info("Song found in the database.")

                await update.message.reply_audio(audio=file_id)
                logging.info("Song sent to the user.")
                await reply_message.edit_text("Find out, sent to you!")
                await reply_message.delete()

                if update.message.chat.type == "private":
                    await update.message.reply_text("Enjoy your music! If you like this bot, consider donating to the developer. /donate")
                return
            else:
                song_not_found_id = id
                not_found_fount += 1

                not_found_song.append((song_not_found_id))
                logging.info(f"No song item found for ID: {id}")
        except:
            pass
        finally:

            sql_session.close()

        await self.download_song(update, reply_message, not_found_song, not_found_fount, context, media_group)


    async def check_album_in_sql(self, update: Update, url, context):
        reply_message = await update.message.reply_text("Finding the album in the database...")

        sql_session = get_session()

        id = re.search(r"/([a-z]{2})/(album|playlist|song)/(.*)/([a-z]{2}\..*|[0-9]*)(?:\?i=)?([0-9a-z]*)", url).group(4)
        id = id.split('?')[0]
        logging.info(f"ID: {id}")

        songs = await downloader.get_album(id)

        if songs is not None:
            pass
        else:
            await update.message.reply_text(f"Sorry, connect to Apple Music is {downloader.error}, please try again later.")

        logging.info(f"Songs: {songs}")
        all_songs_found = True
        not_found_song = []
        try:
            media_group = []
            not_found_fount = 0  
            for song_id in songs:

                song_item = sql_session.query(apple_music).filter_by(id=song_id).first()
                if song_item is not None:
                    file_id = song_item.fileId
                    logging.info(f"File ID: {file_id}")

                    media = InputMediaAudio(media=file_id)
                    media_group.append(media)
                else:
                    song_not_found_id = song_id
                    not_found_song.append((song_not_found_id))
                    logging.info(f"No song item found for ID: {song_id}")

                    not_found_fount += 1  
                    all_songs_found = False
                    continue
            if all_songs_found:
                if len(media_group) > 10:
                    for i in range(0, len(media_group), 10):
                        sub_media_group = media_group[i:i+10]

                        for _ in range(5):
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
        except Exception as e:
            logging.error(f"Error: {e}")
        finally:

            sql_session.close()

        await self.download_song(update, reply_message, not_found_song, not_found_fount, context, media_group)

    async def check_playlist_in_sql(self, update: Update, url, context):
        reply_message = await update.message.reply_text("Finding the playlist in the database...")

        sql_session = get_session()
        id = re.search(r"/([a-z]{2})/(album|playlist|song)/(.*)/([a-z]{2}\..*|[0-9]*?)(?:\?i=)?([0-9a-z]*)", url).group(4)
        id = id.split('?')[0]
        logging.info(f"ID: {id}")

        songs = await downloader.get_playlist(id)

        if songs is not None:
            pass
        else:
            await update.message.reply_text(f"Sorry, connect to Apple Music is {downloader.error}, please try again later.")

        logging.info(f"Songs: {songs}")
        all_songs_found = True
        not_found_song = []
        try:
            media_group = []
            not_found_fount = 0  # 添加计数器
            for song_id in songs:

                song_item = sql_session.query(apple_music).filter_by(id=song_id).first()
                if song_item is not None:
                    file_id = song_item.fileId
                    logging.info(f"File ID: {file_id}")

                    media = InputMediaAudio(media=file_id)
                    media_group.append(media)
                else:

                    song_not_found_id = song_id
                    not_found_song.append((song_not_found_id))
                    logging.info(f"No song item found for ID: {song_id}")
                    not_found_fount += 1
                    all_songs_found = False
                    continue

            if all_songs_found:
                if len(media_group) > 10:

                    for i in range(0, len(media_group), 10):
                        sub_media_group = media_group[i:i+10]

                        for _ in range(5):
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
                                continue
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
                await reply_message.edit_text("Find out some songs, senting to you! and downloading the rest of the songs...")
        except Exception as e:
            logging.error(f"Error: {e}")
        finally:

            sql_session.close()
        logging.info(f"not_found_song: {not_found_song}")


        await self.download_song(update, reply_message, not_found_song, not_found_fount, context, media_group)

    async def download_song(self, update: Update, reply_message, not_found_song, not_found_fount, context, media_group):
        not_found_fountTotal = 0

        if not_found_fount == 1:
            await reply_message.edit_text("Donwloading the song...")
        else:
            await reply_message.edit_text(f"Donwloading {not_found_fountTotal}/{not_found_fount} songs...")

        songs = []
        for track_id in not_found_song:
            logging.info(f"Downloading song {track_id}...")
            try:
                webplayback = downloader.get_webplayback(track_id)

                cover_url = downloader.get_cover_url(webplayback)

                tags = downloader.get_tags_song(webplayback)

                save_cover = downloader.save_cover(tags, cover_url)
                final_location = downloader.get_final_location(tags)

                songs.append((track_id, final_location, save_cover, tags['title'], tags['artist']))

                stream_url = downloader.get_stream_url_song(webplayback)

                decryption_key = downloader.get_decryption_key_song(stream_url, track_id)

                encrypted_location = downloader.get_encrypted_location_audio(track_id)
                downloader.download_ytdlp(encrypted_location, stream_url)

                decrypted_location = downloader.get_decrypted_location_audio(track_id)            
                fixed_location = downloader.get_fixed_location(track_id, ".m4a")
                downloader.fixup_song_ffmpeg(encrypted_location, decryption_key, fixed_location)

                logging.info(f"Adding tags to {fixed_location}, {tags}, {cover_url}")
                downloader.apply_tags(fixed_location, tags, cover_url)

                downloader.move_to_final_location(fixed_location, final_location)
                not_found_fountTotal += 1

                await reply_message.edit_text(f"Donwloading {not_found_fountTotal}/{not_found_fount} songs...")

                if not_found_fountTotal % 10 == 0:
                    await self.send_song(update, songs, reply_message, not_found_fount, media_group, context)
                    songs = []
            except Exception as e:
                logging.error(f"Failed to get song {track_id}: {e}")
        if songs:
            await self.send_song(update, songs, reply_message, not_found_fount, media_group, context)
        logging.info("Downloaded the song.")

        downloader.cleanup_temp_path()
        await self.delete_song_file()
        await reply_message.delete()

        if update.message.chat.type == "private":
            await update.message.reply_text("Enjoy your music! If you like this bot, consider donating to the developer. /donate")

        return

    async def delete_song_file(self):
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
            except OSError as e:
                logging.info(f"Failed to delete {directory}: {e}")
            except Exception as e:
                logging.info(f"An error occurred: {e}")

    async def send_song(self, update: Update, songs, reply_message, not_found_fount, media_group, context):
        await reply_message.edit_text("Download successfully, sending to you! ")

        if not_found_fount == 1:
            file_id_dict = await self.send_singe_song(update, songs, reply_message)
        else:
            file_id_dict = await self.send_group_song(update, songs, reply_message, media_group, context)

        logging.info(f"File ID dict: {file_id_dict}")

        await self.save_song_info_to_sql(file_id_dict)
    
    async def send_singe_song(self, update: Update, songs, reply_message):
        try:
            file_id_dict = {}
            for song_id, song_path, cover_art_path, song_name, artist_name in songs:
               
                audiotime = AudioSegment.from_file(song_path)
                duration = audiotime.duration_seconds
                
                logging.info(f"audio={song_path}, thumbnail={cover_art_path}, duration={duration}, performer={artist_name}, title={song_name}")
                for _ in range(5):
                    try:
                        message = await update.message.reply_audio(audio=song_path, thumbnail=cover_art_path, duration=duration, performer=artist_name, title=song_name)
                        file_id = message.audio.file_id
                        file_id_dict[song_id] = file_id
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
        
            return file_id_dict
        except:
            logging.error(f"An error occurred while sending the song")
            return {}

    async def send_group_song(self, update: Update, songs, reply_message, media_group, context):
        file_id_dict = {}
        prosess = 0

        if len(media_group) > 10:
            for i in range(0, len(media_group), 10):
                sub_media_group = media_group[i:i+10]

                for _ in range(5):
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

        for song_id, song_path, cover_art_path, song_name, artist_name in songs:
            try:
                audio = AudioSegment.from_file(song_path)
                duration = audio.duration_seconds

                for _ in range(5):
                    try:
                        message = await context.bot.send_audio(chat_id=TELEGRAM_CHANNEL_ID, audio=song_path, thumbnail=cover_art_path, duration=duration, performer=artist_name, title=song_name)
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
        media_group.clear()
        logging.info(f"File ID dict: {file_id_dict}")
        return file_id_dict

    async def save_song_info_to_sql(self, file_id_dict):
        sql_session = get_session()

        logging.info(f"song info: {file_id_dict}")

        for song_id, file_id in file_id_dict.items():
            existing_song = sql_session.query(apple_music).filter_by(id=song_id).first()
            if existing_song is None:
                apple_music_item = apple_music(id=song_id, fileId=file_id)
                logging.info(f"New song: {apple_music_item}")
                sql_session.add(apple_music_item)
                logging.info(f"Saveing the {song_id} file_id {file_id}saved in the database.")
            else:
                logging.info(f"Song with ID {song_id} already exists, skipping")
        logging.info("Song saved in the database.")

        sql_session.commit()
        sql_session.close()

