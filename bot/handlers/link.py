from telegram import Update, InputFile
from telegram.ext import ContextTypes
from telegram.error import TimedOut, NetworkError
from pathlib import Path
from typing import Optional
import logging
import asyncio
import re
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


def format_track_label(item) -> str:
    title = getattr(getattr(item, "media_tags", None), "title", None) or "Unknown Song"
    artist = getattr(getattr(item, "media_tags", None), "artist", None) or "Unknown Artist"
    return f"{title} - {artist}"


def extract_apple_music_urls(text: str) -> list[str]:
    url_pattern = r'https?://(?:music\.apple\.com|apple\.co)/[^\s]+'
    urls = re.findall(url_pattern, text, re.IGNORECASE)
    return [url for url in urls if has_apple_music_domain(url)]


async def link_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if not message or not message.text:
        logger.info("Ignoring update without text message")
        return

    user = update.effective_user
    if not user:
        logger.info("Ignoring update without user")
        return

    user_id = user.id
    chat_id = update.effective_chat.id
    message_text = message.text.strip()

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
        if not has_apple_music_domain(message_text):
            logger.info(f"Ignoring non-Apple Music message in group {chat_id}")
            return
        logger.info(f"Processing Apple Music link in group {chat_id}")
    else:
        if not await whitelist(update, context):
            return

    urls = extract_apple_music_urls(message_text)
    if not urls:
        logger.info(f"No valid Apple Music URLs found in message: {message_text[:50]}...")
        return

    if len(urls) == 1:
        await process_single_url(update, context, urls[0])
    else:
        await process_multiple_urls(update, context, urls)


async def process_single_url(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    message = update.effective_message
    downloader = context.bot_data['downloader']
    chat_id = update.effective_chat.id
    message_id = message.message_id
    reply_to = message_id if is_group_chat(chat_id) else None

    status_msg = await send_message_with_retry(message, "Validating link...")

    url_info = downloader.parse_url(url)
    if not url_info:
        error_text = "Invalid Apple Music URL. Please send a valid song, album, or playlist link."
        await safe_edit_status(status_msg, error_text)
        return

    is_album_request = (
        (url_info.type in ALBUM_MEDIA_TYPE) or
        (url_info.library_type in ALBUM_MEDIA_TYPE) or
        ('/album/' in url.lower())
    )

    await safe_edit_status(status_msg, "Fetching song information...")

    try:
        download_queue = await downloader.get_download_queue(url_info)

        if not download_queue:
            await send_message_with_retry(
                message,
                "Unable to fetch song information. Please check the URL and try again."
            )
            return

        if len(download_queue) > 1:
            await handle_collection(update, context, download_queue, status_msg, is_album_request, reply_to)
        else:
            await handle_single_track(update, context, download_queue[0], status_msg, reply_to)

    except Exception as e:
        logger.exception(f"Error processing link: {url}")
        try:
            await send_message_with_retry(
                update.message,
                f"An error occurred: {str(e)}"
            )
        except Exception:
            logger.error("Failed to send error message to user")


async def process_multiple_urls(update: Update, context: ContextTypes.DEFAULT_TYPE, urls: list[str]):
    message = update.effective_message
    downloader = context.bot_data['downloader']
    chat_id = update.effective_chat.id
    message_id = message.message_id
    reply_to = message_id if is_group_chat(chat_id) else None

    total_urls = len(urls)
    status_msg = await send_message_with_retry(
        message,
        f"Found {total_urls} links, processing..."
    )

    processed = 0
    failed = 0

    for idx, url in enumerate(urls, 1):
        try:
            await safe_edit_status(status_msg, f"Processing link {idx}/{total_urls}...")

            url_info = downloader.parse_url(url)
            if not url_info:
                logger.warning(f"Invalid URL {idx}/{total_urls}: {url}")
                failed += 1
                continue

            download_queue = await downloader.get_download_queue(url_info)
            if not download_queue:
                logger.warning(f"No songs found for URL {idx}/{total_urls}: {url}")
                failed += 1
                continue

            if len(download_queue) > 1:
                await handle_collection(update, context, download_queue, None, False, reply_to)
            else:
                await handle_single_track(update, context, download_queue[0], None, reply_to)

            processed += 1

        except Exception as e:
            logger.exception(f"Error processing URL {idx}/{total_urls}: {url}")
            failed += 1

    await safe_edit_status(
        status_msg,
        f"Complete! Processed: {processed} links, Failed: {failed} links"
    )
    asyncio.create_task(delete_status_after_delay(status_msg))


async def handle_single_track(update: Update, context: ContextTypes.DEFAULT_TYPE, item, status_msg=None, message_id: Optional[int] = None):
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
        status_msg = await send_message_with_retry(update.message, "Fetching song information...")

    cached = await cache.get_cached_song(apple_music_id)
    if cached:
        logger.info(f"Cache hit for {apple_music_id}")
        await safe_delete_status(status_msg)
        await sender.send_cached_audio(context, chat_id, cached['file_id'], cached, message_id)
        await cache.update_user_activity(
            user_id,
            update.effective_user.username,
            update.effective_user.first_name
        )
        return

    file_path = None
    try:
        await concurrency.acquire(user_id)

        await safe_edit_status(status_msg, f"Downloading: {format_track_label(item)}")

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

        await safe_edit_status(status_msg, "Uploading...")

        metadata = downloader.extract_metadata(item)
        message = await sender.send_audio(context, chat_id, file_path, metadata, message_id)

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
    progress_counter: dict,
    message_id: Optional[int] = None
):
    if item.error:
        progress_counter['failed'] += 1
        return

    try:
        apple_music_id = item.media_metadata['id']

        cached = await cache.get_cached_song(apple_music_id)
        if cached:
            await sender.send_cached_audio(context, chat_id, cached['file_id'], cached, message_id)
            progress_counter['processed'] += 1
            return

        file_path = None
        try:
            await concurrency.acquire(user_id)

            progress_counter['current'] = format_track_label(item)
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
            message = await sender.send_audio(context, chat_id, file_path, metadata, message_id)

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
    total: int,
    message_id: Optional[int] = None
):
    downloader = context.bot_data['downloader']
    cache = context.bot_data['cache']
    sender = context.bot_data['sender']
    concurrency = context.bot_data['concurrency']
    config = context.bot_data['config']

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    await safe_edit_status(status_msg, f"Found {total} songs, sending as album...")

    prepared_entries = []
    individual_entries = []
    failed = 0
    max_size = config.max_file_size_mb * 1024 * 1024
    archive_channel = getattr(config, 'archive_channel', '@applemusicachive')

    def cleanup_entries(entries):
        for entry in entries:
            try:
                file_handle = entry.get('file_handle')
                if file_handle and not file_handle.closed:
                    file_handle.close()

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
                    upload_source = entry.get('file_path') or entry['file_id']
                    message = await sender.send_audio(
                        context,
                        chat_id,
                        upload_source,
                        metadata,
                        message_id
                    )
                    if message and message.audio:
                        await cache.store_song(
                            metadata,
                            message.audio.file_id,
                            message.audio.file_unique_id,
                            entry.get('file_size', 0)
                        )
                else:
                    await sender.send_cached_audio(context, chat_id, entry['file_id'], metadata, message_id)
                processed += 1
            except Exception as e:
                logger.exception(f"Failed to send track individually: {e}")
        return processed

    for idx, item in enumerate(download_queue, 1):
        if item.error:
            failed += 1
            continue

        metadata = downloader.extract_metadata(item)
        apple_music_id = metadata['apple_music_id']
        await safe_edit_status(
            status_msg,
            f"Preparing album: {idx}/{total}\nProcessing: {metadata['title']} - {metadata['artist']}"
        )

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
                individual_entries.append({
                    'metadata': metadata,
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

    if not prepared_entries and not individual_entries:
        cleanup_entries(prepared_entries)
        cleanup_entries(individual_entries)
        await safe_edit_status(status_msg, f"Complete! Processed: 0, Failed: {failed}")
        return

    if len(prepared_entries) < 2:
        await safe_edit_status(status_msg, "Less than 2 songs available, sending individually...")
        processed = await send_entries_individually(prepared_entries + individual_entries)
        cleanup_entries(prepared_entries)
        cleanup_entries(individual_entries)

        failed_total = failed + (len(prepared_entries) + len(individual_entries) - processed)
        await cache.update_user_activity(
            user_id,
            update.effective_user.username,
            update.effective_user.first_name
        )
        await safe_edit_status(status_msg, f"Complete! Processed: {processed}, Failed: {failed_total}")
        asyncio.create_task(delete_status_after_delay(status_msg))
        return

    processed = 0
    send_failures = 0
    try:
        await safe_edit_status(status_msg, f"Prepared {len(prepared_entries)} songs, uploading...")
        media_group = []
        for entry in prepared_entries:
            media_source = entry['file_id']

            file_path = entry.get('file_path')

            media = await sender.build_input_media_audio(
                entry['metadata'],
                media_source,
                file_path=file_path,
                include_thumbnail=False
            )
            media_group.append(media)

        responses = await context.bot.send_media_group(
            chat_id=chat_id,
            media=media_group,
            reply_to_message_id=message_id
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

        if individual_entries:
            processed += await send_entries_individually(individual_entries)

    except Exception as e:
        logger.exception(f"Failed to send media group, falling back to individual sends: {e}")
        processed = await send_entries_individually(prepared_entries + individual_entries)
        send_failures = len(prepared_entries) + len(individual_entries) - processed
    finally:
        cleanup_entries(prepared_entries)
        cleanup_entries(individual_entries)

    failed_total = failed + send_failures

    await cache.update_user_activity(
        user_id,
        update.effective_user.username,
        update.effective_user.first_name
    )

    await safe_edit_status(
        status_msg,
        f"Complete! Processed: {processed}, Failed: {failed_total}"
    )
    asyncio.create_task(delete_status_after_delay(status_msg))


async def handle_collection(update: Update, context: ContextTypes.DEFAULT_TYPE, download_queue: list, status_msg=None, is_album: bool = False, message_id: Optional[int] = None):
    downloader = context.bot_data['downloader']
    cache = context.bot_data['cache']
    sender = context.bot_data['sender']
    concurrency = context.bot_data['concurrency']
    config = context.bot_data['config']

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    total = len(download_queue)
    if is_album and 1 < total <= 10:
        await handle_album_media_group(update, context, download_queue, status_msg, total, message_id)
        return
    if not status_msg:
        status_msg = await send_message_with_retry(
            update.message,
            "Fetching song information..."
        )

    progress_counter = {'processed': 0, 'failed': 0, 'current': None}

    async def update_progress():
        last_text = None
        while True:
            try:
                completed = progress_counter['processed'] + progress_counter['failed']
                if completed < total:
                    current = progress_counter.get('current')
                    current_text = f"\nCurrent: {current}" if current else ""
                    new_text = (
                        f"Downloading: {completed}/{total} "
                        f"(Successful: {progress_counter['processed']}, Failed: {progress_counter['failed']})"
                        f"{current_text}"
                    )
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

    await safe_edit_status(status_msg, f"Found {total} songs, downloading...")

    progress_task = asyncio.create_task(update_progress())

    tasks = [
        process_track_item(
            item, idx, total, user_id, chat_id,
            downloader, cache, sender, concurrency, config, context,
            progress_counter,
            message_id
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
        f"Complete! Processed: {progress_counter['processed']}, Failed: {progress_counter['failed']}"
    )
    asyncio.create_task(delete_status_after_delay(status_msg))
