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

    url_info = downloader.parse_url(url)
    if not url_info:
        await send_message_with_retry(
            update.message,
            "Invalid Apple Music URL. Please send a valid song, album, or playlist link."
        )
        return

    try:
        download_queue = await downloader.get_download_queue(url_info)

        if not download_queue:
            await send_message_with_retry(
                update.message,
                "Unable to fetch song information. Please check the URL and try again."
            )
            return

        if len(download_queue) > 1:
            await handle_collection(update, context, download_queue)
        else:
            await handle_single_track(update, context, download_queue[0])

    except Exception as e:
        logger.exception(f"Error processing link: {url}")
        try:
            await send_message_with_retry(
                update.message,
                f"An error occurred: {str(e)}"
            )
        except Exception:
            logger.error("Failed to send error message to user")


async def handle_single_track(update: Update, context: ContextTypes.DEFAULT_TYPE, item):
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

    cached = await cache.get_cached_song(apple_music_id)
    if cached:
        logger.info(f"Cache hit for {apple_music_id}")
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

        status_msg = await send_message_with_retry(update.message, "Downloading...")

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

        try:
            await status_msg.edit_text("Uploading...")
        except (TimedOut, NetworkError) as e:
            logger.warning(f"Failed to edit status message: {e}")

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

        try:
            await status_msg.delete()
        except (TimedOut, NetworkError) as e:
            logger.warning(f"Failed to delete status message: {e}")

    except FileTooLargeError as e:
        await send_message_with_retry(update.message, str(e))
    except Exception as e:
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


async def handle_collection(update: Update, context: ContextTypes.DEFAULT_TYPE, download_queue: list):
    downloader = context.bot_data['downloader']
    cache = context.bot_data['cache']
    sender = context.bot_data['sender']
    concurrency = context.bot_data['concurrency']
    config = context.bot_data['config']

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    total = len(download_queue)
    status_msg = await send_message_with_retry(
        update.message,
        f"Found {total} tracks. Processing..."
    )

    progress_counter = {'processed': 0, 'failed': 0}

    async def update_progress():
        while True:
            try:
                completed = progress_counter['processed'] + progress_counter['failed']
                if completed < total:
                    try:
                        await status_msg.edit_text(
                            f"Progress: {completed}/{total} (Processed: {progress_counter['processed']}, Failed: {progress_counter['failed']})"
                        )
                    except (TimedOut, NetworkError) as e:
                        logger.warning(f"Failed to edit status message: {e}")
                    await asyncio.sleep(2)
                else:
                    break
            except Exception as e:
                logger.warning(f"Error in progress update: {e}")
                break

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

    try:
        await status_msg.edit_text(
            f"Completed! Processed: {progress_counter['processed']}, Failed: {progress_counter['failed']}"
        )
    except (TimedOut, NetworkError) as e:
        logger.warning(f"Failed to edit final status message: {e}")
