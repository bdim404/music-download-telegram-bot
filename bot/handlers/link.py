from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import TimedOut, NetworkError
from pathlib import Path
import logging
import asyncio
from gamdl.downloader.constants import ALBUM_MEDIA_TYPE



logger = logging.getLogger(__name__)


async def send_message_with_retry(message, text, max_retries=3):
    for attempt in range(max_retries):
        try:
            return await message.reply_text(text)
        except (TimedOut, NetworkError) as e:
            if attempt == max_retries - 1:
                logger.error(f"Failed to send message after {max_retries} attempts: {e}")
                raise
            logger.warning(f"Retry {attempt + 1}/{max_retries} sending message: {e}")
            await asyncio.sleep(2 ** attempt)


class FileTooLargeError(Exception):
    pass


async def safe_edit_status(status_msg, text):
    try:
        await status_msg.edit_text(text)
    except (TimedOut, NetworkError) as e:
        logger.warning(f"Failed to edit status message: {e}")
    except Exception as e:
        if "message is not modified" not in str(e).lower():
            logger.warning(f"Failed to edit status message: {e}")


async def safe_delete_status(status_msg):
    try:
        await status_msg.delete()
    except (TimedOut, NetworkError) as e:
        logger.warning(f"Failed to delete status message: {e}")


async def delete_status_after_delay(status_msg, delay: float = 3.0):
    try:
        await asyncio.sleep(delay)
        await safe_delete_status(status_msg)
    except Exception as e:
        logger.warning(f"Failed to delete status after delay: {e}")


def has_apple_music_domain(url: str) -> bool:
    url_lower = url.lower()
    return 'music.apple.com' in url_lower or 'apple.co' in url_lower


def is_group_chat(chat_id: int) -> bool:
    return chat_id < 0


async def safe_delete_user_message(user_msg):
    try:
        await user_msg.delete()
    except (TimedOut, NetworkError) as e:
        logger.warning(f"Failed to delete user message: {e}")
    except Exception as e:
        if "message can't be deleted" not in str(e).lower() and \
           "message to delete not found" not in str(e).lower():
            logger.warning(f"Failed to delete user message: {e}")


async def link_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    url = update.message.text.strip()
    chat_id = update.effective_chat.id

    downloader = context.bot_data['downloader']
    cache = context.bot_data['cache']
    sender = context.bot_data['sender']
    concurrency = context.bot_data['concurrency']
    whitelist = context.bot_data['whitelist']
    config = context.bot_data['config']

    if is_group_chat(chat_id):
        logger.info(f"Group message detected: chat_id={chat_id}, user_id={user_id}")
        logger.info(f"Whitelisted groups: {whitelist.whitelist_groups}")
        if not whitelist.check_group(chat_id):
            logger.info(f"Group {chat_id} not in whitelist, ignoring")
            return
        logger.info(f"Group {chat_id} is whitelisted, checking for Apple Music domain")
        if not has_apple_music_domain(url):
            logger.info(f"Ignoring non-Apple Music message in group {chat_id}")
            return
        logger.info(f"Processing Apple Music link in group {chat_id}")
    else:
        if not await whitelist(update, context):
            return

    status_msg = None
    if has_apple_music_domain(url):
        status_msg = await send_message_with_retry(update.message, "正在验证链接...")

    url_info = downloader.parse_url(url)
    if not url_info:
        error_text = "Invalid Apple Music URL. Please send a valid song, album, or playlist link."
        if status_msg:
            await safe_edit_status(status_msg, error_text)
        else:
            await send_message_with_retry(update.message, error_text)
        return

    is_album_request = (
        (url_info.type in ALBUM_MEDIA_TYPE) or
        (url_info.library_type in ALBUM_MEDIA_TYPE) or
        ('/album/' in url.lower())
    )

    if status_msg:
        await safe_edit_status(status_msg, "正在获取歌曲信息...")

    try:
        download_queue = await downloader.get_download_queue(url_info)

        if not download_queue:
            await send_message_with_retry(
                update.message,
                "Unable to fetch song information. Please check the URL and try again."
            )
            return

        if len(download_queue) > 1:
            await handle_collection(update, context, download_queue, status_msg, is_album_request)
        else:
            await handle_single_track(update, context, download_queue[0], status_msg)

    except Exception as e:
        logger.exception(f"Error processing link: {url}")
        try:
            await send_message_with_retry(
                update.message,
                f"An error occurred: {str(e)}"
            )
        except Exception:
            logger.error("Failed to send error message to user")


async def handle_single_track(update: Update, context: ContextTypes.DEFAULT_TYPE, item, status_msg=None):
    downloader = context.bot_data['downloader']
    cache = context.bot_data['cache']
    sender = context.bot_data['sender']
    concurrency = context.bot_data['concurrency']
    config = context.bot_data['config']

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    if item.error:
        await send_message_with_retry(
            update.message,
            f"Unable to download this track: {str(item.error)}"
        )
        return

    apple_music_id = item.media_metadata['id']

    if not status_msg:
        status_msg = await send_message_with_retry(update.message, "正在获取歌曲信息...")

    cached = await cache.get_cached_song(apple_music_id)
    if cached:
        logger.info(f"Cache hit for {apple_music_id}")
        await safe_delete_status(status_msg)
        await sender.send_cached_audio(context, chat_id, cached['file_id'], cached)
        await cache.update_user_activity(
            user_id,
            update.effective_user.username,
            update.effective_user.first_name
        )
        return

    file_path = None
    try:
        await concurrency.acquire(user_id)

        await safe_edit_status(status_msg, "正在下载...")

        file_path = await downloader.download_track(item)

        if not file_path or not Path(file_path).exists():
            raise FileNotFoundError(f"Downloaded file not found at: {file_path}")

        file_size = Path(file_path).stat().st_size
        max_size = config.max_file_size_mb * 1024 * 1024

        if file_size > max_size:
            raise FileTooLargeError(
                f"File is too large ({file_size / 1024 / 1024:.1f}MB). "
                f"Maximum size is {config.max_file_size_mb}MB."
            )

        await safe_edit_status(status_msg, "正在上传...")

        metadata = downloader.extract_metadata(item)
        message = await sender.send_audio(context, chat_id, file_path, metadata)

        await cache.store_song(
            metadata,
            message.audio.file_id,
            message.audio.file_unique_id,
            file_size
        )

        await cache.update_user_activity(
            user_id,
            update.effective_user.username,
            update.effective_user.first_name
        )

        await safe_delete_status(status_msg)

    except FileTooLargeError as e:
        await safe_delete_status(status_msg)
        await send_message_with_retry(update.message, str(e))
    except Exception as e:
        await safe_delete_status(status_msg)
        logger.exception(f"Error downloading track {apple_music_id}")
        try:
            await send_message_with_retry(update.message, f"Download failed: {str(e)}")
        except Exception:
            logger.error("Failed to send error message to user")
    finally:
        concurrency.release(user_id)
        if file_path and Path(file_path).exists():
            Path(file_path).unlink()


async def process_track_item(
    item,
    idx: int,
    total: int,
    user_id: int,
    chat_id: int,
    downloader,
    cache,
    sender,
    concurrency,
    config,
    context,
    progress_counter: dict
):
    if item.error:
        progress_counter['failed'] += 1
        return

    try:
        apple_music_id = item.media_metadata['id']

        cached = await cache.get_cached_song(apple_music_id)
        if cached:
            await sender.send_cached_audio(context, chat_id, cached['file_id'], cached)
            progress_counter['processed'] += 1
            return

        file_path = None
        try:
            await concurrency.acquire(user_id)

            file_path = await downloader.download_track(item)

            if not file_path or not Path(file_path).exists():
                raise FileNotFoundError(f"Downloaded file not found at: {file_path}")

            file_size = Path(file_path).stat().st_size
            max_size = config.max_file_size_mb * 1024 * 1024

            if file_size > max_size:
                logger.warning(f"Skipping {item.media_tags.title}: file too large")
                progress_counter['failed'] += 1
                return

            metadata = downloader.extract_metadata(item)
            message = await sender.send_audio(context, chat_id, file_path, metadata)

            await cache.store_song(
                metadata,
                message.audio.file_id,
                message.audio.file_unique_id,
                file_size
            )

            progress_counter['processed'] += 1

        finally:
            concurrency.release(user_id)
            if file_path and Path(file_path).exists():
                Path(file_path).unlink()

    except Exception as e:
        logger.exception(f"Error processing track {idx}/{total}")
        progress_counter['failed'] += 1


async def handle_album_media_group(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    download_queue: list,
    status_msg,
    total: int
):
    downloader = context.bot_data['downloader']
    cache = context.bot_data['cache']
    sender = context.bot_data['sender']
    concurrency = context.bot_data['concurrency']
    config = context.bot_data['config']

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    await safe_edit_status(status_msg, f"找到 {total} 首歌曲, 将以合辑发送...")

    prepared_entries = []
    failed = 0
    max_size = config.max_file_size_mb * 1024 * 1024
    archive_channel = getattr(config, 'archive_channel', '@applemusicachive')

    def cleanup_entries(entries):
        for entry in entries:
            try:
                file_path = entry.get('file_path')
                if file_path:
                    path_obj = Path(file_path)
                    if path_obj.exists():
                        path_obj.unlink()
            except Exception as e:
                logger.warning(f"Failed to clean up temp file: {e}")

    async def send_entries_individually(entries):
        processed = 0
        for entry in entries:
            try:
                metadata = entry['metadata']
                if entry.get('needs_upload'):
                    message = await sender.send_audio(
                        context,
                        chat_id,
                        entry['file_id'],
                        metadata
                    )
                    if message and message.audio:
                        await cache.store_song(
                            metadata,
                            message.audio.file_id,
                            message.audio.file_unique_id,
                            entry.get('file_size', 0)
                        )
                else:
                    await sender.send_cached_audio(context, chat_id, entry['file_id'], metadata)
                processed += 1
            except Exception as e:
                logger.exception(f"Failed to send track individually: {e}")
        return processed

    for item in download_queue:
        if item.error:
            failed += 1
            continue

        metadata = downloader.extract_metadata(item)
        apple_music_id = metadata['apple_music_id']

        cached = await cache.get_cached_song(apple_music_id)
        if cached and cached.get('file_id'):
            prepared_entries.append({
                'metadata': metadata,
                'file_id': cached['file_id'],
                'is_cached': True
            })
            continue

        file_path = None
        acquired = False
        
        try:
            await concurrency.acquire(user_id)
            acquired = True

            file_path = await downloader.download_track(item)
            path_obj = Path(file_path)

            if not path_obj.exists():
                raise FileNotFoundError(f"Downloaded file not found at: {file_path}")

            file_size = path_obj.stat().st_size

            if file_size > max_size:
                logger.warning(f"Skipping {metadata['title']}: file too large for group send")
                failed += 1
                path_obj.unlink()
                continue

            channel_message = None
            try:
                channel_message = await sender.send_audio(
                    context,
                    archive_channel,
                    file_path,
                    metadata
                )
            except Exception as upload_err:
                logger.warning(f"Upload to archive channel failed, will send directly: {upload_err}")

            if channel_message and channel_message.audio:
                prepared_entries.append({
                    'metadata': metadata,
                    'file_id': channel_message.audio.file_id,
                    'file_path': file_path,
                    'file_size': file_size
                })

                await cache.store_song(
                    metadata,
                    channel_message.audio.file_id,
                    channel_message.audio.file_unique_id,
                    file_size
                )
            else:
                prepared_entries.append({
                    'metadata': metadata,
                    'file_id': file_path,
                    'file_path': file_path,
                    'file_size': file_size,
                    'needs_upload': True
                })

        except Exception as e:
            failed += 1
            logger.exception(f"Error preparing track for album group: {e}")
            if file_path and Path(file_path).exists():
                Path(file_path).unlink()
        finally:
            if acquired:
                concurrency.release(user_id)

    if not prepared_entries:
        cleanup_entries(prepared_entries)
        await safe_edit_status(status_msg, f"完成! 已处理: 0个, 失败: {failed}")
        return

    if len(prepared_entries) < 2:
        await safe_edit_status(status_msg, "可发送歌曲少于2首，逐条发送...")
        processed = await send_entries_individually(prepared_entries)
        cleanup_entries(prepared_entries)

        failed_total = failed + (len(prepared_entries) - processed)
        await cache.update_user_activity(
            user_id,
            update.effective_user.username,
            update.effective_user.first_name
        )
        await safe_edit_status(status_msg, f"完成! 已处理: {processed}个, 失败: {failed_total}")
        asyncio.create_task(delete_status_after_delay(status_msg))
        return

    processed = 0
    send_failures = 0
    try:
        await safe_edit_status(status_msg, f"已准备 {len(prepared_entries)} 首歌曲, 正在上传...")
        media_group = [
            await sender.build_input_media_audio(
                entry['metadata'],
                entry['file_id'],
                file_path=entry.get('file_path'),
                include_thumbnail=not entry.get('is_cached')
            )
            for entry in prepared_entries
        ]

        responses = await context.bot.send_media_group(
            chat_id=chat_id,
            media=media_group
        )

        processed = len(responses)
        if processed < len(prepared_entries):
            send_failures = len(prepared_entries) - processed

        for message, entry in zip(responses, prepared_entries):
            if not entry.get('is_cached'):
                metadata = entry['metadata']
                await cache.store_song(
                    metadata,
                    message.audio.file_id,
                    message.audio.file_unique_id,
                    entry['file_size']
                )

    except Exception as e:
        logger.exception(f"Failed to send media group, falling back to individual sends: {e}")
        processed = await send_entries_individually(prepared_entries)
        send_failures = len(prepared_entries) - processed
    finally:
        cleanup_entries(prepared_entries)

    failed_total = failed + send_failures

    await cache.update_user_activity(
        user_id,
        update.effective_user.username,
        update.effective_user.first_name
    )

    await safe_edit_status(
        status_msg,
        f"完成! 已处理: {processed}个, 失败: {failed_total}"
    )
    asyncio.create_task(delete_status_after_delay(status_msg))


async def handle_collection(update: Update, context: ContextTypes.DEFAULT_TYPE, download_queue: list, status_msg=None, is_album: bool = False):
    downloader = context.bot_data['downloader']
    cache = context.bot_data['cache']
    sender = context.bot_data['sender']
    concurrency = context.bot_data['concurrency']
    config = context.bot_data['config']

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    total = len(download_queue)
    if is_album and 1 < total <= 10:
        await handle_album_media_group(update, context, download_queue, status_msg, total)
        return
    if not status_msg:
        status_msg = await send_message_with_retry(
            update.message,
            "正在获取歌曲信息..."
        )

    progress_counter = {'processed': 0, 'failed': 0}

    async def update_progress():
        last_text = None
        while True:
            try:
                completed = progress_counter['processed'] + progress_counter['failed']
                if completed < total:
                    new_text = f"Progress: {completed}/{total} (Processed: {progress_counter['processed']}, Failed: {progress_counter['failed']})"
                    if new_text != last_text:
                        try:
                            await status_msg.edit_text(new_text)
                            last_text = new_text
                        except (TimedOut, NetworkError) as e:
                            logger.warning(f"Failed to edit status message: {e}")
                        except Exception as e:
                            if "message is not modified" not in str(e).lower():
                                logger.warning(f"Failed to edit status message: {e}")
                    await asyncio.sleep(2)
                else:
                    break
            except Exception as e:
                logger.warning(f"Error in progress update: {e}")
                break

    await safe_edit_status(status_msg, f"找到 {total} 首歌曲,正在下载...")

    progress_task = asyncio.create_task(update_progress())

    tasks = [
        process_track_item(
            item, idx, total, user_id, chat_id,
            downloader, cache, sender, concurrency, config, context,
            progress_counter
        )
        for idx, item in enumerate(download_queue, 1)
    ]

    await asyncio.gather(*tasks, return_exceptions=True)

    progress_task.cancel()
    try:
        await progress_task
    except asyncio.CancelledError:
        pass

    await cache.update_user_activity(
        user_id,
        update.effective_user.username,
        update.effective_user.first_name
    )

    await safe_edit_status(
        status_msg,
        f"完成! 已处理: {progress_counter['processed']}个, 失败: {progress_counter['failed']}个"
    )
    asyncio.create_task(delete_status_after_delay(status_msg))
