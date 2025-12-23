import httpx
import logging
from telegram import Message
from telegram.ext import ContextTypes
from pathlib import Path
from typing import Optional
from mutagen.mp4 import MP4
from difflib import SequenceMatcher
from urllib.parse import quote_plus
import re

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
        thumbnail = await self._get_thumbnail(metadata.get('cover_url'), file_path, metadata)

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
        thumbnail = await self._get_thumbnail(metadata.get('cover_url'), None, metadata)

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
        file_path: Optional[str] = None,
        metadata: Optional[dict] = None
    ) -> Optional[bytes]:
        if cover_url:
            thumbnail = await self._download_cover(cover_url)
            if thumbnail:
                return thumbnail
            logger.debug("Falling back to file extraction after URL download failed")

        if file_path:
            thumbnail = self._extract_cover_from_file(file_path)
            if thumbnail:
                return thumbnail
            logger.debug("Falling back to iTunes Search after file extraction failed")

        if metadata and metadata.get('title') and metadata.get('artist'):
            thumbnail = await self._search_itunes_cover(
                title=metadata['title'],
                artist=metadata['artist'],
                album=metadata.get('album')
            )
            if thumbnail:
                return thumbnail

        logger.debug("No thumbnail available after all fallback attempts")
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

    def _normalize_string(self, text: str) -> str:
        text = text.lower()
        text = re.sub(r'\(official.*?\)|\(audio\)|\[explicit\]', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\bfeat\b\.?|\bft\b\.?|\bfeaturing\b', '', text, flags=re.IGNORECASE)
        text = re.sub(r'[^\w\s]', ' ', text)
        text = re.sub(r'\s+', ' ', text)
        return text.strip()

    def _calculate_similarity(self, str1: str, str2: str) -> float:
        normalized1 = self._normalize_string(str1)
        normalized2 = self._normalize_string(str2)
        return SequenceMatcher(None, normalized1, normalized2).ratio() * 100

    def _find_best_match(self, results: list, title: str, artist: str) -> Optional[dict]:
        if not results:
            return None

        best_match = None
        best_score = 0

        for result in results:
            result_title = result.get('trackName', '')
            result_artist = result.get('artistName', '')

            if not result_title or not result_artist:
                continue

            title_normalized = self._normalize_string(title)
            artist_normalized = self._normalize_string(artist)
            result_title_normalized = self._normalize_string(result_title)
            result_artist_normalized = self._normalize_string(result_artist)

            if title_normalized == result_title_normalized and artist_normalized == result_artist_normalized:
                score = 100
            elif artist_normalized == result_artist_normalized:
                title_similarity = self._calculate_similarity(title, result_title)
                if title_similarity > 80:
                    score = 80 + (title_similarity - 80) / 2
                else:
                    score = title_similarity * 0.8
            else:
                title_similarity = self._calculate_similarity(title, result_title)
                if title_similarity > 85:
                    score = title_similarity * 0.7
                else:
                    score = title_similarity * 0.5

            if score > best_score:
                best_score = score
                best_match = result

        if best_score >= 65:
            logger.debug(f"Best match score: {best_score:.1f}")
            return best_match

        logger.debug(f"No good match found (best score: {best_score:.1f}), using first result")
        return results[0] if results else None

    async def _search_itunes_cover(
        self,
        title: str,
        artist: str,
        album: Optional[str] = None
    ) -> Optional[bytes]:
        try:
            query = f"{artist} {title}"
            encoded_query = quote_plus(query)
            url = f"https://itunes.apple.com/search?term={encoded_query}&media=music&entity=song&limit=5"

            async with httpx.AsyncClient() as client:
                response = await client.get(url, timeout=8.0)
                response.raise_for_status()
                data = response.json()

            results = data.get('results', [])
            if not results:
                logger.debug(f"No iTunes results for '{title}' by '{artist}'")
                return None

            best_match = self._find_best_match(results, title, artist)
            if not best_match:
                logger.debug("No suitable iTunes match found")
                return None

            artwork_url = best_match.get('artworkUrl100')
            if not artwork_url:
                logger.debug("No artwork URL in iTunes result")
                return None

            high_res_url = artwork_url.replace('100x100bb.jpg', '1200x1200bb.jpg')
            logger.info(f"Found iTunes cover for '{title}' by '{artist}'")

            return await self._download_cover(high_res_url)

        except httpx.HTTPStatusError as e:
            logger.warning(f"HTTP error searching iTunes: {e.response.status_code}")
            return None
        except httpx.TimeoutException:
            logger.warning("Timeout searching iTunes")
            return None
        except Exception as e:
            logger.error(f"Unexpected error searching iTunes: {type(e).__name__}: {e}")
            return None
