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
        notFoundSong = []
        mediaGroup = []
        try:
            notFoundCount = 0
            songItem = sql_session.query(musicSong).filter_by(id=id).first()
            if songItem is not None:
                fileId = songItem.fileId
                logging.info(f"File ID: {fileId}")
                logging.info("Song found in the database.")
                await update.message.reply_audio(audio=fileId)
                logging.info("Song sent to the user.")
                await replyMessage.edit_text("Find out, sent to you!")
                return
            else:
                songNotFoundId = id
                notFoundCount += 1
                notFoundSong.append((songNotFoundId))
                logging.info(f"No song item found for ID: {id}")
        except:
            pass
        finally:
            sql_session.close()
        await self.DownloadSong(update, url, replyMessage, notFoundCount)
        songs = await web_playback.GetSong(session, id)
        return await self.SendSong(update, songs, replyMessage, notFoundSong, notFoundCount, context, mediaGroup)


    #check if the album has been downloaded before from sql;
    async def CheckAlbumInSql(self, update: Update, url, context):
        replyMessage = await update.message.reply_text("Finding the album in the database...")
        sql_session = get_session()
        id = re.search(r"/([a-z]{2})/(album|playlist|song)/(.*)/([a-z]{2}\..*|[0-9]*)(?:\?i=)?([0-9a-z]*)", url).group(4)
        logging.info(f"ID: {id}")
        songs = await web_playback.GetAlbum(session, id)
        logging.info(f"Songs: {songs}")
        allSongsFound = True
        notFoundSong = []
        try:
            mediaGroup = []
            notFoundCount = 0  # 添加计数器
            for songId, trackNumber, songName, artistName in songs:
                songItem = sql_session.query(musicSong).filter_by(id=songId).first()
                if songItem is not None:
                    fileId = songItem.fileId
                    logging.info(f"File ID: {fileId}")
                    media = InputMediaAudio(media=fileId)
                    mediaGroup.append(media)
                else:
                    songNotFoundId = songId
                    notFoundSong.append((songNotFoundId))
                    logging.info(f"No song item found for ID: {songId}")
                    notFoundCount += 1  # 增加计数器的值
                    allSongsFound = False
                    continue
            if allSongsFound:
                await replyMessage.edit_text("Find out, senting to you!")
                await replyMessage.delete()
                await update.message.reply_media_group(media=mediaGroup)
                return
            else:
                await replyMessage.edit_text("Find out some songs and downloading the rest of the songs...")
        except Exception as e:
            logging.error(f"Error: {e}")
        finally:
            sql_session.close()

        await self.DownloadSong(update,url,replyMessage,notFoundCount)
        return await self.SendSong(update, songs, replyMessage, notFoundSong, notFoundCount, mediaGroup, context)

    #check if the playlist has been downloaded before from sql;
    async def CheckPlaylistInSql(self, update: Update, url, context):
        replyMessage = await update.message.reply_text("Finding the playlist in the database...")
        sql_session = get_session()
        id = re.search(r"/([a-z]{2})/(album|playlist|song)/(.*)/([a-z]{2}\..*|[0-9]*)(?:\?i=)?([0-9a-z]*)", url).group(4)
        logging.info(f"ID: {id}")
        songs = await web_playback.GetPlaylist(session, id)
        logging.info(f"Songs: {songs}")
        allSongsFound = True
        notFoundSong = []
        try:
            mediaGroup = []
            notFoundCount = 0  # 添加计数器
            for songId, trackNumber, songName, artistName in songs:
                songItem = sql_session.query(musicSong).filter_by(id=songId).first()
                if songItem is not None:
                    fileId = songItem.fileId
                    logging.info(f"File ID: {fileId}")
                    media = InputMediaAudio(media=fileId)
                    mediaGroup.append(media)
                else:
                    songNotFoundId = songId
                    notFoundSong.append((songNotFoundId))
                    logging.info(f"No song item found for ID: {songId}")
                    notFoundCount += 1
                    allSongsFound = False
                    continue
            if allSongsFound:
                await replyMessage.edit_text("Find out, senting to you!")
                await replyMessage.delete()
                await update.message.reply_media_group(media=mediaGroup)
                return
            else:
                await replyMessage.edit_text("Find out some songs, senting to you! and downloading the rest of the songs...")
        except Exception as e:
            logging.error(f"Error: {e}")
        finally:
            sql_session.close()
        logging.info(f"notFoundCount: {notFoundCount}")
        logging.info(f"notFoundSong: {notFoundSong}")
        replyMessage = await self.DownloadSong(update, url, replyMessage,notFoundCount)
        return await self.SendSong(update, songs, replyMessage, notFoundSong, notFoundCount, mediaGroup, context)

    #download the song;
    async def DownloadSong(self, update: Update, url, replyMessage, notFoundCount):
        if notFoundCount == 1:
            await replyMessage.edit_text("Donwloading the song...")
        else:
            await replyMessage.edit_text(f"Donwloading {notFoundCount} songs...")
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
    async def RenameSongFile(self, songs, notFoundSong):
        directory = "./Apple Music"  # Specify the directory to traverse
        renamedFiles = []
        logging.info(f"songs: {songs}")
        for root, dirs, files in os.walk(directory):
            for file in files:
                if file.endswith(".m4a"):
                    # 创建新的文件名
                    for song in songs:
                        songId = song[0]  # 假设 song 的第一个元素是 ID
                        if songId not in notFoundSong:  # 如果歌曲 ID 在 notFoundSong 中，跳过这首歌曲
                            continue
                        trackNumber = song[1]
                        songName = song[2]
                        artistName = f"{song[3]}"
                        new_songName = f"{trackNumber} {songName}"
                        # 去除文件扩展名
                        file_name_without_extension = os.path.splitext(file)[0]
                        # 如果新的歌曲名匹配文件名
                        if new_songName[:4] == file_name_without_extension[:4]:
                            new_file_name = f"{new_songName} - {artistName}.m4a"
                            # 创建新的文件路径
                            new_file_path = os.path.join(root, new_file_name)
                            # 创建旧的文件路径
                            old_file_path = os.path.join(root, file)
                            # 重命名文件
                            os.rename(old_file_path, new_file_path)
                            # 将新的文件路径添加到列表中
                            logging.info(f"New file path: {new_file_path}, Song name: {songName}, Artist name: {artistName}")
                            renamedFiles.append((new_file_path,songName,artistName))
                            break
        logging.info(f"Renamed files: {renamedFiles}")
        return renamedFiles

    #delete the song file;
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

    #send the song to the user; 
    async def SendSong(self, update: Update, songs, replyMessage, notFoundSong, notFoundCount, mediaGroup, context):
        await replyMessage.edit_text("Song downloaded successfully,sending to you!")
        renamedFiles = await self.RenameSongFile(songs, notFoundSong)
        if notFoundCount == 1:
            fileIdDict = await self.SendSingeSong(update, renamedFiles[0][0], renamedFiles[0][1], renamedFiles[0][2], replyMessage)
        else:
            fileIdDict = await self.SendGroupSong(update, renamedFiles, replyMessage, mediaGroup, context)
        await replyMessage.delete()
        logging.info(f"File ID dict: {fileIdDict}")
        await self.SaveSongInfoToSql(fileIdDict, songs)
    
    async def SendSingeSong(self, update: Update, songPath, songName, artistName, replyMessage):
        logging.info(f"songPath: {songPath} songName: {songName} artistName: {artistName}")
        try:
            # 获取音乐的时长
            audiotime = AudioSegment.from_file(songPath)
            duration = audiotime.duration_seconds
            # 遍历当前目录./CoverArt中的jpg文件
            for file in glob.glob(f"./CoverArt/*.jpg"):
                # 获取文件名 并与songName进行比较
                filename, _ = os.path.splitext(os.path.basename(file))
                if filename == songName:
                    logging.info(f"Checking files: {filename},Song name: {songName}")
                    coverArtPath = file
                    logging.info(f"Cover art path: {coverArtPath}")
                    break
            logging.info(f"audio={songPath}, thumbnail={coverArtPath}, duration={duration}, performer={artistName}, title={songName}")
            message = await update.message.reply_audio(audio=songPath, thumbnail=coverArtPath, duration=duration, performer=artistName, title=songName)
            fileId = message.audio.file_id
            os.remove(coverArtPath)
            songSendName = songName
            return {songSendName: fileId}
        except:
            logging.error(f"An error occurred while sending the song")
            return {}

    async def SendGroupSong(self, update: Update, renamedFiles, replyMessage, mediaGroup, context):
        fileIdDict = {}
        for songPath, songName, artistName in renamedFiles:
            try:
                # 获取音乐的时长
                audio = AudioSegment.from_file(songPath)
                duration = audio.duration_seconds
                # 遍历当前目录./CoverArt中的jpg文件
                for file in glob.glob(f"./CoverArt/*.jpg"):
                    # 获取文件名 并与songName进行比较
                    filename, _ = os.path.splitext(os.path.basename(file))
                    if filename == songName:
                        logging.info(f"Checking files: {filename},Song name: {songName}")
                        coverArtPath = file
                        logging.info(f"Cover art path: {coverArtPath}")
                # 先将音频一个一个发送到channel，然后获取fileId
                message = await context.bot.send_audio(chat_id='@applemusicachive', audio=songPath, thumbnail=coverArtPath, duration=duration, performer=artistName, title=songName)
                fileId = message.audio.file_id
                # 使用fileId创建InputMediaAudio对象
                media = InputMediaAudio(media=fileId)
                mediaGroup.append(media)
                songSendName = songName
                fileIdDict[songSendName] = fileId
            except:
                logging.error(f"An error occurred while sending the song", exc_info=True)
        logging.info(f"Media group: {mediaGroup}")
        # 通过发送group的方式统一发送给用户
        await update.message.reply_media_group(media=mediaGroup)
        return fileIdDict

    #stone the song info to sql;
    async def SaveSongInfoToSql(self, fileIdDict, songs):
        sql_session = get_session()
        logging.info(f"songs: {songs}")
        logging.info("save song info to sql")
        logging.info(f"song info: {fileIdDict}")
        for songSendName, fileId in fileIdDict.items():
            logging.info(f"Song name: {songSendName} File ID: {fileId}")
            for songId, trackNumber, songName, artistName in songs:
                if songSendName == songName:
                    song_all_name = f"{trackNumber} {songName} - {artistName}"
                    logging.info(f"Song name: {songName} File ID: {fileId}")
                    existing_song = sql_session.query(musicSong).filter_by(id=songId).first()
                    if existing_song is None:
                        musicSongItem = musicSong(id=songId, fileId=fileId, songName=song_all_name)
                        logging.info(f"New song: {musicSongItem}")
                        sql_session.add(musicSongItem)
                        logging.info(f"Saveing the {songId} songName {songName} fileId {fileId}saved in the database.")
                    else:
                        logging.info(f"Song with ID {songId} already exists, skipping")
        logging.info("Song saved in the database.")

        sql_session.commit()
        sql_session.close()
        await self.DeleteSongFile()