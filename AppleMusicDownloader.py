import logging,os,asyncio,shutil,re,glob,subprocess
from AppleMusicWebPlayback import WebPlayback
from urllib.parse import urlparse, parse_qs
from sqlalchemy.orm import sessionmaker
from db import musicSong, get_session
from get_cover_art import CoverFinder
from pydub import AudioSegment
from telegram import Update,InputMediaAudio
from telegram.ext import CallbackContext
import time


web_playback = WebPlayback()
session = web_playback.setup_session("cookies.txt")

class AppleMusicDownloader:
    async def CheckLinkType(self, update: Update, context):
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
            await self.CheckSongInSql(update, url, context)
        elif catalog_resource_type == "music-video":
            logging.info("The link is a music-video.")
            await update.message.reply_text("Sorry, I can't download music vedio.")
            return
        elif catalog_resource_type == "album":
            logging.info("The link is an album.")
            await self.CheckAlbumInSql(update, url, context)
        elif catalog_resource_type == "playlist":
            if update.message.chat.type == "private":
                logging.info("The link is a playlist.")
                await self.CheckPlaylistInSql(update, url, context)
            else:
                await update.message.reply_text("Sorry, I can't download playlist in group chat.")
        else:
            raise Exception("Invalid URL")

    #check if the song has been downloaded before from sql;
    async def CheckSongInSql(self, update: Update, url, context):
        replyMessage = await update.message.reply_text("Finding the song in the database...")
        sql_session = get_session()
        id = parse_qs(urlparse(url).query)['i'][0]
        logging.info(f"ID: {id}")
        not_found_song = []
        mediagroup = []
        try:
            not_found_count = 0
            song_item = sql_session.query(musicSong).filter_by(id=id).first()
            if song_item is not None:
                file_id = song_item.file_id
                logging.info(f"File ID: {file_id}")
                logging.info("Song found in the database.")
                await update.message.reply_audio(audio=file_id)
                logging.info("Song sent to the user.")
                await replyMessage.edit_text("Find out, sent to you!")
                return
            else:
                song_not_found_id = id
                not_found_count += 1
                not_found_song.append((song_not_found_id))
                logging.info(f"No song item found for ID: {id}")
        except:
            pass
        finally:
            sql_session.close()
        await self.download_song(update, url, replyMessage, not_found_count)
        songs = await web_playback.get_song(session, id)
        return await self.send_song(update, songs, replyMessage, not_found_song, not_found_count, context, mediagroup)


    #check if the album has been downloaded before from sql;
    async def CheckAlbumInSql(self, update: Update, url, context):
        replyMessage = await update.message.reply_text("Finding the album in the database...")
        sql_session = get_session()
        id = re.search(r"/([a-z]{2})/(album|playlist|song)/(.*)/([a-z]{2}\..*|[0-9]*)(?:\?i=)?([0-9a-z]*)", url).group(4)
        logging.info(f"ID: {id}")
        songs = await web_playback.get_album(session, id)
        logging.info(f"Songs: {songs}")
        all_songs_found = True
        not_found_song = []
        try:
            mediagroup = []
            not_found_count = 0  # 添加计数器
            for song_id, track_number, song_name, artist_name in songs:
                song_item = sql_session.query(musicSong).filter_by(id=song_id).first()
                if song_item is not None:
                    file_id = song_item.file_id
                    logging.info(f"File ID: {file_id}")
                    media = InputMediaAudio(media=file_id)
                    mediagroup.append(media)
                else:
                    song_not_found_id = song_id
                    not_found_song.append((song_not_found_id))
                    logging.info(f"No song item found for ID: {song_id}")
                    not_found_count += 1  # 增加计数器的值
                    all_songs_found = False
                    continue
            if all_songs_found:
                await replyMessage.edit_text("Find out, senting to you!")
                await replyMessage.delete()
                await update.message.reply_media_group(media=mediagroup)
                return
            else:
                await replyMessage.edit_text("Find out some songs and downloading the rest of the songs...")
        except Exception as e:
            logging.error(f"Error: {e}")
        finally:
            sql_session.close()

        await self.download_song(update,url,replyMessage,not_found_count)
        return await self.send_song(update, songs, replyMessage, not_found_song, not_found_count, mediagroup, context)

    #check if the playlist has been downloaded before from sql;
    async def CheckPlaylistInSql(self, update: Update, url, context):
        replyMessage = await update.message.reply_text("Finding the playlist in the database...")
        sql_session = get_session()
        id = re.search(r"/([a-z]{2})/(album|playlist|song)/(.*)/([a-z]{2}\..*|[0-9]*)(?:\?i=)?([0-9a-z]*)", url).group(4)
        logging.info(f"ID: {id}")
        songs = await web_playback.get_playlist(session, id)
        logging.info(f"Songs: {songs}")
        all_songs_found = True
        not_found_song = []
        try:
            mediagroup = []
            not_found_count = 0  # 添加计数器
            for song_id, track_number, song_name, artist_name in songs:
                song_item = sql_session.query(musicSong).filter_by(id=song_id).first()
                if song_item is not None:
                    file_id = song_item.file_id
                    logging.info(f"File ID: {file_id}")
                    media = InputMediaAudio(media=file_id)
                    mediagroup.append(media)
                else:
                    song_not_found_id = song_id
                    not_found_song.append((song_not_found_id))
                    logging.info(f"No song item found for ID: {song_id}")
                    not_found_count += 1
                    all_songs_found = False
                    continue
            if all_songs_found:
                await replyMessage.edit_text("Find out, senting to you!")
                await replyMessage.delete()
                await update.message.reply_media_group(media=mediagroup)
                return
            else:
                await replyMessage.edit_text("Find out some songs, senting to you! and downloading the rest of the songs...")
        except Exception as e:
            logging.error(f"Error: {e}")
        finally:
            sql_session.close()
        logging.info(f"not_found_count: {not_found_count}")
        logging.info(f"not_found_song: {not_found_song}")
        replyMessage = await self.download_song(update, url, replyMessage,not_found_count)
        return await self.send_song(update, songs, replyMessage, not_found_song, not_found_count, mediagroup, context)

    #download the song;
    async def download_song(self, update: Update, url, replyMessage, not_found_count):
        if not_found_count == 1:
            await replyMessage.edit_text("Donwloading the song...")
        else:
            await replyMessage.edit_text(f"Donwloading {not_found_count} songs...")
        command = ["gamdl"] + [url]
        logging.info(f"Command: {' '.join(command)}")
        try:
            process = await asyncio.create_subprocess_exec(*command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            stdout, stderr = await process.communicate()
            await process.wait()  
            logging.info(f"Song downloaded successfully.")
            return replyMessage
        except Exception as e:
            logging.error(f"An error occurred while downloading the song: {e}")
            return

    #rename the song file;
    async def rename_song_file(self, songs, not_found_song):
        directory = "./Apple Music"  # Specify the directory to traverse
        renamed_files = []
        logging.info(f"songs: {songs}")
        for root, dirs, files in os.walk(directory):
            for file in files:
                if file.endswith(".m4a"):
                    # 创建新的文件名
                    for song in songs:
                        song_id = song[0]  # 假设 song 的第一个元素是 ID
                        if song_id not in not_found_song:  # 如果歌曲 ID 在 not_found_song 中，跳过这首歌曲
                            continue
                        track_number = song[1]
                        song_name = song[2]
                        artist_name = f"{song[3]}"
                        new_song_name = f"{track_number} {song_name}"
                        # 去除文件扩展名
                        file_name_without_extension = os.path.splitext(file)[0]
                        # 如果新的歌曲名匹配文件名
                        if new_song_name[:4] == file_name_without_extension[:4]:
                            new_file_name = f"{new_song_name} - {artist_name}.m4a"
                            # 创建新的文件路径
                            new_file_path = os.path.join(root, new_file_name)
                            # 创建旧的文件路径
                            old_file_path = os.path.join(root, file)
                            # 重命名文件
                            os.rename(old_file_path, new_file_path)
                            # 将新的文件路径添加到列表中
                            logging.info(f"New file path: {new_file_path}, Song name: {song_name}, Artist name: {artist_name}")
                            renamed_files.append((new_file_path,song_name,artist_name))
                            break
        logging.info(f"Renamed files: {renamed_files}")
        return renamed_files

    #delete the song file;
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
            except Exception as e:
                logging.info(f"An error occurred: {e}")

    #send the song to the user; 
    async def send_song(self, update: Update, songs, replyMessage, not_found_song, not_found_count, mediagroup, context):
        await replyMessage.edit_text("Song downloaded successfully,sending to you!")
        renamed_files = await self.rename_song_file(songs, not_found_song)
        if not_found_count == 1:
            file_id_dict = await self.send_singer_song(update, renamed_files[0][0], renamed_files[0][1], renamed_files[0][2], replyMessage)
        else:
            file_id_dict = await self.send_group_song(update, renamed_files, replyMessage, mediagroup, context)
        await replyMessage.delete()
        logging.info(f"File ID dict: {file_id_dict}")
        await self.SaveSongInfoToSql(file_id_dict, songs)
    
    async def send_singer_song(self, update: Update, song_path, song_name, artist_name, replyMessage):
        logging.info(f"Song_path: {song_path} Song_name: {song_name} Artist_name: {artist_name}")
        try:
            # 获取音乐的时长
            audiotime = AudioSegment.from_file(song_path)
            duration = audiotime.duration_seconds
            # 遍历当前目录./CoverArt中的jpg文件
            for file in glob.glob(f"./CoverArt/*.jpg"):
                # 获取文件名 并与song_name进行比较
                filename, _ = os.path.splitext(os.path.basename(file))
                if filename == song_name:
                    logging.info(f"Checking files: {filename},Song name: {song_name}")
                    cover_art_path = file
                    logging.info(f"Cover art path: {cover_art_path}")
                    break
            logging.info(f"audio={song_path}, thumbnail={cover_art_path}, duration={duration}, performer={artist_name}, title={song_name}")
            message = await update.message.reply_audio(audio=song_path, thumbnail=cover_art_path, duration=duration, performer=artist_name, title=song_name)
            file_id = message.audio.file_id
            os.remove(cover_art_path)
            song_send_name = song_name
            return {song_send_name: file_id}
        except:
            logging.error(f"An error occurred while sending the song")
            return {}

    async def send_group_song(self, update: Update, renamed_files, replyMessage, mediagroup, context):
        file_id_dict = {}
        for song_path, song_name, artist_name in renamed_files:
            try:
                # 获取音乐的时长
                audio = AudioSegment.from_file(song_path)
                duration = audio.duration_seconds
                # 遍历当前目录./CoverArt中的jpg文件
                for file in glob.glob(f"./CoverArt/*.jpg"):
                    # 获取文件名 并与song_name进行比较
                    filename, _ = os.path.splitext(os.path.basename(file))
                    if filename == song_name:
                        logging.info(f"Checking files: {filename},Song name: {song_name}")
                        cover_art_path = file
                        logging.info(f"Cover art path: {cover_art_path}")
                # 先将音频一个一个发送到channel，然后获取file_id
                message = await context.bot.send_audio(chat_id='@applemusicachive', audio=song_path, thumbnail=cover_art_path, duration=duration, performer=artist_name, title=song_name)
                file_id = message.audio.file_id
                # 使用file_id创建InputMediaAudio对象
                media = InputMediaAudio(media=file_id)
                mediagroup.append(media)
                song_send_name = song_name
                file_id_dict[song_send_name] = file_id
            except:
                logging.error(f"An error occurred while sending the song", exc_info=True)
        logging.info(f"Media group: {mediagroup}")
        # 通过发送group的方式统一发送给用户
        await update.message.reply_media_group(media=mediagroup)
        return file_id_dict

    #stone the song info to sql;
    async def SaveSongInfoToSql(self, file_id_dict, songs):
        sql_session = get_session()
        logging.info(f"songs: {songs}")
        logging.info("save song info to sql")
        logging.info(f"song info: {file_id_dict}")
        for song_send_name, file_id in file_id_dict.items():
            logging.info(f"Song name: {song_send_name} File ID: {file_id}")
            for song_id, track_number, song_name, artist_name in songs:
                if song_send_name == song_name:
                    song_all_name = f"{track_number} {song_name} - {artist_name}"
                    logging.info(f"Song name: {song_name} File ID: {file_id}")
                    existing_song = sql_session.query(musicSong).filter_by(id=song_id).first()
                    if existing_song is None:
                        musicSongItem = musicSong(id=song_id, file_id=file_id, song_name=song_all_name)
                        logging.info(f"New song: {musicSongItem}")
                        sql_session.add(musicSongItem)
                        logging.info(f"Saveing the {song_id} song_name {song_name} file_id {file_id}saved in the database.")
                    else:
                        logging.info(f"Song with ID {song_id} already exists, skipping")
        logging.info("Song saved in the database.")

        sql_session.commit()
        sql_session.close()
        await self.delete_song_file()