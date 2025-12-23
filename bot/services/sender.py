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

        try:
            with open(file_path, 'rb') as audio_file:
                message = await context.bot.send_audio(
                    chat_id=chat_id,
                    audio=audio_file,
                    title=metadata['title'],
                    performer=metadata['artist'],
                    duration=duration,
                    thumbnail=thumbnail
                )

            cover_status = "with cover" if thumbnail else "without cover"
            logger.info(f"Successfully sent audio '{metadata['title']}' by '{metadata['artist']}' {cover_status}")

            return message
        except Exception as e:
            logger.error(f"Failed to send audio '{metadata['title']}' with thumbnail: {type(e).__name__}: {e}")

            if thumbnail:
                logger.info(f"Retrying without thumbnail for '{metadata['title']}'")
                with open(file_path, 'rb') as audio_file:
                    message = await context.bot.send_audio(
                        chat_id=chat_id,
                        audio=audio_file,
                        title=metadata['title'],
                        performer=metadata['artist'],
                        duration=duration,
                        thumbnail=None
                    )
                logger.info(f"Successfully sent audio '{metadata['title']}' without cover")
                return message
            else:
                raise

    async def send_cached_audio(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        file_id: str,
        metadata: dict
    ) -> Message:
        duration = metadata.get('duration_ms', 0) // 1000
        thumbnail = await self._get_thumbnail(metadata.get('cover_url'), None, metadata)

        try:
            message = await context.bot.send_audio(
                chat_id=chat_id,
                audio=file_id,
                title=metadata.get('title'),
                performer=metadata.get('artist'),
                duration=duration,
                thumbnail=thumbnail
            )

            cover_status = "with cover" if thumbnail else "without cover"
            logger.info(f"Successfully sent cached audio '{metadata.get('title')}' by '{metadata.get('artist')}' {cover_status}")

            return message
        except Exception as e:
            logger.error(f"Failed to send cached audio '{metadata.get('title')}' with thumbnail: {type(e).__name__}: {e}")

            if thumbnail:
                logger.info(f"Retrying without thumbnail for '{metadata.get('title')}'")
                message = await context.bot.send_audio(
                    chat_id=chat_id,
                    audio=file_id,
                    title=metadata.get('title'),
                    performer=metadata.get('artist'),
                    duration=duration,
                    thumbnail=None
                )
                logger.info(f"Successfully sent cached audio '{metadata.get('title')}' without cover")
                return message
            else:
                raise

    async def _get_thumbnail(
        self,
        cover_url: Optional[str],
        file_path: Optional[str] = None,
        metadata: Optional[dict] = None
    ) -> Optional[bytes]:
        song_info = ""
        if metadata:
            song_info = f" for '{metadata.get('title', 'Unknown')}' by '{metadata.get('artist', 'Unknown')}'"

        if metadata and metadata.get('title') and metadata.get('artist'):
            logger.debug(f"Attempting iTunes Search{song_info}")
            thumbnail = await self._search_itunes_cover(
                title=metadata['title'],
                artist=metadata['artist'],
                album=metadata.get('album')
            )
            if thumbnail:
                logger.info(f"Successfully got cover from iTunes Search{song_info}")
                return thumbnail
            logger.warning(f"iTunes Search failed{song_info}")

        logger.warning(f"No thumbnail available{song_info}")
        return None

    async def _download_cover(self, cover_url: str) -> Optional[bytes]:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(cover_url, timeout=10.0)
                response.raise_for_status()
                size_kb = len(response.content) / 1024
                logger.debug(f"Downloaded cover from URL (size: {size_kb:.1f} KB)")
                return response.content
        except httpx.HTTPStatusError as e:
            logger.warning(f"HTTP error {e.response.status_code} downloading cover from {cover_url}")
            return None
        except httpx.TimeoutException:
            logger.warning(f"Timeout downloading cover from {cover_url}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error downloading cover from {cover_url}: {type(e).__name__}: {e}")
            return None

    def _extract_cover_from_file(self, file_path: str) -> Optional[bytes]:
        try:
            audio = MP4(file_path)
            if audio.tags and 'covr' in audio.tags:
                cover_data = audio.tags['covr'][0]
                size_kb = len(cover_data) / 1024
                logger.debug(f"Extracted cover from file (size: {size_kb:.1f} KB)")
                return bytes(cover_data)
            else:
                logger.debug(f"No cover found in file metadata: {file_path}")
                return None
        except Exception as e:
            logger.warning(f"Failed to extract cover from file {file_path}: {type(e).__name__}: {e}")
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

            logger.debug(f"Searching iTunes with query: '{query}'")

            async with httpx.AsyncClient() as client:
                response = await client.get(url, timeout=8.0)
                response.raise_for_status()
                data = response.json()

            results = data.get('results', [])
            result_count = len(results)

            if not results:
                logger.debug(f"iTunes returned 0 results for '{title}' by '{artist}'")
                return None

            logger.debug(f"iTunes returned {result_count} results for '{title}' by '{artist}'")

            best_match = self._find_best_match(results, title, artist)
            if not best_match:
                logger.debug(f"No suitable iTunes match found among {result_count} results")
                return None

            matched_title = best_match.get('trackName', 'Unknown')
            matched_artist = best_match.get('artistName', 'Unknown')
            logger.debug(f"Best iTunes match: '{matched_title}' by '{matched_artist}'")

            artwork_url = best_match.get('artworkUrl100')
            if not artwork_url:
                logger.debug("No artwork URL in iTunes result")
                return None

            logger.debug(f"Original iTunes artwork URL: {artwork_url}")

            for size in ['600x600', '320x320', '100x100']:
                cover_url = re.sub(r'\d+x\d+bb\.', f'{size}bb.', artwork_url)
                logger.debug(f"Trying {size} URL: {cover_url}")

                cover_data = await self._download_cover(cover_url)
                if not cover_data:
                    logger.debug(f"Failed to download {size} cover")
                    continue

                size_kb = len(cover_data) / 1024
                logger.debug(f"Downloaded {size} cover (size: {size_kb:.1f} KB)")

                if size_kb <= 200:
                    logger.info(f"Successfully got iTunes cover for '{title}' by '{artist}' ({size}, {size_kb:.1f} KB)")
                    return cover_data
                else:
                    logger.warning(f"Cover {size} too large ({size_kb:.1f} KB > 200 KB), trying smaller size")

            logger.warning(f"All iTunes cover sizes exceed 200 KB limit for '{title}' by '{artist}'")
            return None

        except httpx.HTTPStatusError as e:
            logger.warning(f"HTTP error searching iTunes for '{title}' by '{artist}': {e.response.status_code}")
            return None
        except httpx.TimeoutException:
            logger.warning(f"Timeout searching iTunes for '{title}' by '{artist}'")
            return None
        except Exception as e:
            logger.error(f"Unexpected error searching iTunes for '{title}' by '{artist}': {type(e).__name__}: {e}")
            return None
