import logging,os,asyncio,shutil,re,glob,subprocess
from AppleMusicWebPlayback import WebPlayback
from urllib.parse import urlparse, parse_qs
from sqlalchemy.orm import sessionmaker
from db import musicSong, get_session
from get_cover_art import CoverFinder
from pydub import AudioSegment
from telegram import Update

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
            await self.CheckSongInSql(update, url)
        elif catalog_resource_type == "music-video":
            logging.info("The link is a music-video.")
            await update.message.reply_text("Sorry, I can't download music vedio.")
            return
        elif catalog_resource_type == "album":
            logging.info("The link is an album.")
            await self.CheckAlbumInSql(update, url)
        elif catalog_resource_type == "playlist":
            logging.info("The link is a playlist.")
            await self.CheckPlaylistInSql(update, url)
        else:
            raise Exception("Invalid URL")

    #check if the song has been downloaded before from sql;
    async def CheckSongInSql(self, update: Update, url):
        replyMessage = await update.message.reply_text("Finding the song in the database...")
        message_chat_id = replyMessage.chat.id
        message_message_id = replyMessage.message_id   
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
            await replyMessage.edit_text("Find out, sent to you!")
            await replyMessage.delete()
            return
        except:
            await replyMessage.delete()
            pass
        finally:
            sql_session.close()
        await self.download_song(update,url)
        songs = await web_playback.get_song(session, id)
        return await self.send_song(update, songs)


    #check if the album has been downloaded before from sql;
    async def CheckAlbumInSql(self, update: Update, url):
        replyMessage = await update.message.reply_text("Finding the album in the database...")
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
                await replyMessage.edit_text("Find out, senting to you!")
                return
            else:
                await replyMessage.delete()
        except Exception as e:
            logging.error(f"Error: {e}")
        finally:
            sql_session.close()

        await self.download_song(update,url)
        return await self.send_song(update, songs)

    #check if the playlist has been downloaded before from sql;
    async def CheckPlaylistInSql(self, update: Update ,url):
        replyMessage = await update.message.reply_text("Finding the playlist in the database...")
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
                await replyMessage.edit_text("Find out, senting to you!")
                return
            else:
                await replyMessage.delete()
        except Exception as e:
            logging.error(f"Error: {e}")
        finally:
            sql_session.close()
        
        await self.download_song(update, url)
        return await self.send_song(update, songs)

    #download the song;
    async def download_song(self, update: Update,url):
        replyMessage = await update.message.reply_text("Donwloading the song...")
        command = ["gamdl"] + [url]
        logging.info(f"Command: {' '.join(command)}")
        try:
            process = await asyncio.create_subprocess_exec(*command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            stdout, stderr = await process.communicate()
            await process.wait()  
            logging.info(f"Song downloaded successfully.")
            await replyMessage.delete()
        except Exception as e:
            logging.error(f"An error occurred while downloading the song: {e}")
            return

    #rename the song file;
    async def rename_song_file(self):
        directory = "./Apple Music"  # Specify the directory to traverse
        renamed_files = []
        for root, dirs, files in os.walk(directory):
            for file in files:
                if file.endswith(".m4a"):
                    # 解析出歌手名
                    artist_name = os.path.basename(os.path.dirname(root))
                    # 创建新的文件名
                    new_file_name = f"{os.path.splitext(file)[0].replace('_', '')} -{artist_name}.m4a"
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
    async def send_song(self, update: Update, songs):
        replyMessage = await update.message.reply_text("Song downloaded successfully,sending to you!")
        renamed_files = await self.rename_song_file()
        file_id_dict = {}
        for song_path in renamed_files:
            song_name = os.path.basename(song_path)
            logging.info(f"Song_path: {song_path} Song_name: {song_name}")
            cover_art_path = os.path.basename(song_path).replace('.m4a', '')
            #从路径中提取去除.m4a的文件名
            song_name_without_extension = os.path.splitext(song_name)[0]
            try:
                # 下载封面艺术
                options = {
                    'verbose': True,
                    'no-skip': True,
                    'force': True,
                    'art-dest': './CoverArt',
                    'art-dest-filename': cover_art_path + '.jpg',
                    'path': song_path
                }
                logging.info(f"Options: {options}")
                await self.download_cover_art(song_name_without_extension, options)
                
                # 获取封面艺术的路径
                cover_art_paths = glob.glob("./CoverArt/*.jpg")
                cover_art_path = cover_art_paths[0] if cover_art_paths else None
                logging.info(f"Cover art path: {cover_art_path}")
                
                song_name_without_number = song_name_without_extension[2:]
                logging.info(f"Song name without number: {song_name_without_number}")
                # 使用 '-' 拆分 song_name_without_number
                title, performer = song_name_without_number.rsplit('-', 1)

                # 去除前后的空格
                title = title.strip()
                performer = performer.strip()
                # 获取音乐的时长
                audio = AudioSegment.from_file(song_path)
                duration = audio.duration_seconds
                logging.info(f"Title: {title} Performer: {performer}")
                message = await update.message.reply_audio(audio=song_path, thumbnail=cover_art_path, duration=duration,performer=performer, title=title)
                file_id = message.audio.file_id
                os.remove(cover_art_path)
            except:
                logging.error(f"An error occurred while sending the song")
                break
            logging.info(f"File ID: {file_id}")
            song_name = song_name.replace('.m4a', '')
            file_id_dict[song_name] = file_id
        await replyMessage.delete()
        logging.info(f"File ID dict: {file_id_dict}")
        await self.SaveSongInfoToSql(file_id_dict,songs)
        
    #download the cover art;
    async def download_cover_art(self,song_name_without_extension, options):
        finder = CoverFinder(options)
        finder.scan_file(options['path'])
        jpg_files = glob.glob("./CoverArt/*.jpg")

        # 如果存在 .jpg 文件
        if jpg_files:
            # 获取第一个 .jpg 文件
            jpg_file = jpg_files[0]
            # 创建新的文件名
            new_file_name = f"./CoverArt/{song_name_without_extension}.jpg"
            # 重命名文件
            os.rename(jpg_file, new_file_name)

    #stone the song info to sql;
    async def SaveSongInfoToSql(self, file_id_dict, songs):
        sql_session = get_session()
        logging.info(f"songs: {songs}")
        logging.info("save song info to sql")
        logging.info(f"song info: {file_id_dict}")
        for song_name, file_id in file_id_dict.items():
            logging.info(f"Song name: {song_name} File ID: {file_id}")
            for song in songs:
                logging.info(f"Checking song: {song[1]}")
                if song_name[:4] == song[1][:4] or song_name[-4:] == song[1][-4:]:
                    logging.info(f"Song: {song[1]} song_name: {song_name}")
                    song_id = song[0]
                    logging.info(f"Song ID: {song_id}")
                    existing_song = sql_session.query(musicSong).filter_by(id=song_id).first()
                    if existing_song is None:
                        musicSongItem = musicSong(id=song_id, file_id=file_id)
                        logging.info(f"New song: {musicSongItem}")
                        sql_session.add(musicSongItem)
                        logging.info(f"Saveing the {song_id} song_name {song_name} file_id {file_id}saved in the database.")
                    else:
                        logging.info(f"Song with ID {song_id} already exists, skipping")
        logging.info("Song saved in the database.")

        sql_session.commit()
        sql_session.close()
        await self.delete_song_file()