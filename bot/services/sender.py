import httpx
from telegram import Message
from telegram.ext import ContextTypes
from pathlib import Path
from typing import Optional


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

        with open(file_path, 'rb') as audio_file:
            message = await context.bot.send_audio(
                chat_id=chat_id,
                audio=audio_file,
                title=metadata['title'],
                performer=metadata['artist'],
                duration=duration,
                thumbnail=thumbnail,
                caption=f"{metadata['title']} - {metadata['artist']}\n{metadata.get('album', '')}"
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
            caption=f"✓ {metadata['title']} - {metadata['artist']} (Cached)"
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
