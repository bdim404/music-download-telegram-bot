from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import TimedOut, NetworkError
from pathlib import Path
import logging
import asyncio



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


def has_apple_music_domain(url: str) -> bool:
    url_lower = url.lower()
    return 'music.apple.com' in url_lower or 'apple.co' in url_lower


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

    downloader = context.bot_data['downloader']
    cache = context.bot_data['cache']
    sender = context.bot_data['sender']
    concurrency = context.bot_data['concurrency']
    whitelist = context.bot_data['whitelist']
    config = context.bot_data['config']

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
            await handle_collection(update, context, download_queue, status_msg)
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


async def handle_collection(update: Update, context: ContextTypes.DEFAULT_TYPE, download_queue: list, status_msg=None):
    downloader = context.bot_data['downloader']
    cache = context.bot_data['cache']
    sender = context.bot_data['sender']
    concurrency = context.bot_data['concurrency']
    config = context.bot_data['config']

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    total = len(download_queue)
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
