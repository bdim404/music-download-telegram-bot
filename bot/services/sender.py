import httpx
from telegram import Message
from telegram.ext import ContextTypes
from pathlib import Path
from typing import Optional
from mutagen.mp4 import MP4


class SenderService:
    async def send_audio(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        file_path: str,
        metadata: dict
    ) -> Message:
        duration = metadata.get('duration_ms', 0) // 1000

        thumbnail = None
        if metadata.get('cover_url'):
            thumbnail = await self._download_cover(metadata['cover_url'])

        if not thumbnail:
            thumbnail = self._extract_cover_from_file(file_path)

        with open(file_path, 'rb') as audio_file:
            message = await context.bot.send_audio(
                chat_id=chat_id,
                audio=audio_file,
                title=metadata['title'],
                performer=metadata['artist'],
                duration=duration,
                thumbnail=thumbnail,
                caption=f"{metadata['title']} - {metadata['artist']}"
            )

        return message

    async def send_cached_audio(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        file_id: str,
        metadata: dict
    ) -> Message:
        message = await context.bot.send_audio(
            chat_id=chat_id,
            audio=file_id,
            caption=f"{metadata['title']} - {metadata['artist']}"
        )

        return message

    async def _download_cover(self, cover_url: str) -> Optional[bytes]:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(cover_url)
                response.raise_for_status()
                return response.content
        except Exception:
            return None

    def _extract_cover_from_file(self, file_path: str) -> Optional[bytes]:
        try:
            audio = MP4(file_path)
            if audio.tags and 'covr' in audio.tags:
                cover_data = audio.tags['covr'][0]
                return bytes(cover_data)
        except Exception:
            return None
