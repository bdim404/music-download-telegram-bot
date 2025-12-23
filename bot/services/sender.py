import httpx
import logging
from telegram import Message
from telegram.ext import ContextTypes
from pathlib import Path
from typing import Optional
from mutagen.mp4 import MP4

logger = logging.getLogger(__name__)


class SenderService:
    async def send_audio(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        file_path: str,
        metadata: dict
    ) -> Message:
        duration = metadata.get('duration_ms', 0) // 1000
        thumbnail = await self._get_thumbnail(metadata.get('cover_url'), file_path)

        with open(file_path, 'rb') as audio_file:
            message = await context.bot.send_audio(
                chat_id=chat_id,
                audio=audio_file,
                title=metadata['title'],
                performer=metadata['artist'],
                duration=duration,
                thumbnail=thumbnail
            )

        return message

    async def send_cached_audio(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        file_id: str,
        metadata: dict
    ) -> Message:
        duration = metadata.get('duration_ms', 0) // 1000
        thumbnail = await self._get_thumbnail(metadata.get('cover_url'))

        message = await context.bot.send_audio(
            chat_id=chat_id,
            audio=file_id,
            title=metadata.get('title'),
            performer=metadata.get('artist'),
            duration=duration,
            thumbnail=thumbnail
        )

        return message

    async def _get_thumbnail(
        self,
        cover_url: Optional[str],
        file_path: Optional[str] = None
    ) -> Optional[bytes]:
        if cover_url:
            thumbnail = await self._download_cover(cover_url)
            if thumbnail:
                return thumbnail
            logger.debug("Falling back to file extraction after URL download failed")

        if file_path:
            return self._extract_cover_from_file(file_path)

        logger.debug("No thumbnail available")
        return None

    async def _download_cover(self, cover_url: str) -> Optional[bytes]:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(cover_url, timeout=10.0)
                response.raise_for_status()
                logger.info(f"Downloaded cover from URL (size: {len(response.content)} bytes)")
                return response.content
        except httpx.HTTPStatusError as e:
            logger.warning(f"HTTP error downloading cover: {e.response.status_code}")
            return None
        except httpx.TimeoutException:
            logger.warning("Timeout downloading cover image")
            return None
        except Exception as e:
            logger.error(f"Unexpected error downloading cover: {type(e).__name__}: {e}")
            return None

    def _extract_cover_from_file(self, file_path: str) -> Optional[bytes]:
        try:
            audio = MP4(file_path)
            if audio.tags and 'covr' in audio.tags:
                cover_data = audio.tags['covr'][0]
                logger.info(f"Extracted cover from file (size: {len(cover_data)} bytes)")
                return bytes(cover_data)
            else:
                logger.debug("No cover found in file metadata")
                return None
        except Exception as e:
            logger.warning(f"Failed to extract cover from file: {type(e).__name__}: {e}")
            return None
