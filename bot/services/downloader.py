import sys
import logging
import socket
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "gamdl"))

logger = logging.getLogger(__name__)

from gamdl.api.apple_music_api import AppleMusicApi
from gamdl.api.itunes_api import ItunesApi
from gamdl.interface import AppleMusicInterface
from gamdl.interface.interface_song import AppleMusicSongInterface
from gamdl.interface.interface_music_video import AppleMusicMusicVideoInterface
from gamdl.interface.interface_uploaded_video import AppleMusicUploadedVideoInterface
from gamdl.interface.enums import SongCodec
from gamdl.downloader.downloader import AppleMusicDownloader
from gamdl.downloader.downloader_base import AppleMusicBaseDownloader
from gamdl.downloader.downloader_song import AppleMusicSongDownloader
from gamdl.downloader.downloader_music_video import AppleMusicMusicVideoDownloader
from gamdl.downloader.downloader_uploaded_video import AppleMusicUploadedVideoDownloader
from gamdl.downloader.types import DownloadItem, UrlInfo

from ..config import Config


class DownloaderService:
    def __init__(self, config: Config):
        self.config = config
        self.apple_music_api = None
        self.downloader = None
        self.fallback_downloader = None
        self.interface = None
        self.base_downloader = None

    def _check_wrapper_available(self, timeout: int = 2) -> bool:
        try:
            host, port_str = self.config.wrapper_url.rsplit(':', 1)
            port = int(port_str)
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((host, port))
            sock.close()
            return result == 0
        except Exception as e:
            logger.debug(f"Wrapper check failed: {e}")
            return False

    async def initialize(self):
        try:
            self.apple_music_api = await AppleMusicApi.create_from_netscape_cookies(
                cookies_path=self.config.cookies_path
            )

            if not self.apple_music_api.active_subscription:
                raise ValueError("Apple Music subscription is not active")

        except FileNotFoundError:
            raise FileNotFoundError(
                f"Cookies file not found at {self.config.cookies_path}. "
                "Please export cookies from Apple Music website."
            )
        except ValueError as e:
            if "media-user-token" in str(e):
                raise ValueError(
                    "Invalid cookies file. Please ensure you have exported cookies "
                    "from https://music.apple.com while logged in with an active subscription."
                )
            raise

        self.interface = AppleMusicInterface(
            self.apple_music_api,
            ItunesApi(
                self.apple_music_api.storefront,
                self.apple_music_api.language
            )
        )

        if self.config.use_wrapper:
            if not self._check_wrapper_available():
                raise RuntimeError(
                    f"Wrapper service is not available at {self.config.wrapper_url}.\n"
                    "Please start the wrapper service:\n"
                    "  docker run -d -p 10020:10020 -p 20020:20020 -p 30020:30020 \\\n"
                    "    -v ./rootfs/data:/app/rootfs/data -e args='-H 0.0.0.0' wrapper"
                )
            logger.info(f"Wrapper service is available at {self.config.wrapper_url}")

        self.base_downloader = AppleMusicBaseDownloader(
            output_path=self.config.temp_path,
            temp_path=self.config.temp_path,
            use_wrapper=self.config.use_wrapper,
            wrapper_decrypt_ip=self.config.wrapper_url,
            amdecrypt_path='amdecrypt',
            wvd_path=None,
            save_cover=False,
            save_playlist=False,
            silent=True,
            overwrite=True
        )

        codec_map = {
            "aac-legacy": SongCodec.AAC_LEGACY,
            "aac-he-legacy": SongCodec.AAC_HE_LEGACY,
            "aac": SongCodec.AAC,
            "aac-he": SongCodec.AAC_HE,
            "aac-binaural": SongCodec.AAC_BINAURAL,
            "aac-he-binaural": SongCodec.AAC_HE_BINAURAL,
            "aac-downmix": SongCodec.AAC_DOWNMIX,
            "aac-he-downmix": SongCodec.AAC_HE_DOWNMIX,
            "atmos": SongCodec.ATMOS,
            "ac3": SongCodec.AC3,
            "alac": SongCodec.ALAC
        }

        selected_codec = codec_map.get(self.config.song_codec.lower(), SongCodec.AAC_LEGACY)

        song_interface = AppleMusicSongInterface(self.interface)
        song_downloader = AppleMusicSongDownloader(
            base_downloader=self.base_downloader,
            interface=song_interface,
            codec=selected_codec,
            no_synced_lyrics=True
        )

        music_video_interface = AppleMusicMusicVideoInterface(self.interface)
        music_video_downloader = AppleMusicMusicVideoDownloader(
            base_downloader=self.base_downloader,
            interface=music_video_interface
        )

        uploaded_video_interface = AppleMusicUploadedVideoInterface(self.interface)
        uploaded_video_downloader = AppleMusicUploadedVideoDownloader(
            base_downloader=self.base_downloader,
            interface=uploaded_video_interface
        )

        self.downloader = AppleMusicDownloader(
            interface=self.interface,
            base_downloader=self.base_downloader,
            song_downloader=song_downloader,
            music_video_downloader=music_video_downloader,
            uploaded_video_downloader=uploaded_video_downloader,
            skip_processing=False
        )

        if not self.base_downloader.full_mp4decrypt_path:
            raise RuntimeError(
                "mp4decrypt not found. Please install Bento4:\n"
                "  macOS: brew install bento4\n"
                "  Ubuntu: sudo apt-get install bento4"
            )

    def parse_url(self, url: str) -> UrlInfo | None:
        return self.downloader.get_url_info(url)

    async def get_download_queue(self, url_info: UrlInfo) -> list[DownloadItem]:
        return await self.downloader.get_download_queue(url_info)

    async def download_track(self, download_item: DownloadItem, url_info: UrlInfo = None) -> tuple[str, str | None]:
        fallback_message = None
        high_quality_codecs = ['atmos', 'alac']

        track_title = download_item.media_tags.title
        track_artist = download_item.media_tags.artist
        track_id = download_item.media_metadata['id']

        logger.info(f"[{track_id}] Starting download: {track_artist} - {track_title} (codec: {self.config.song_codec.upper()})")

        try:
            await self.downloader.download(download_item)
            logger.info(f"[{track_id}] Download completed: {track_artist} - {track_title}")
        except Exception as e:
            error_msg = str(e).lower()
            is_format_unavailable = (
                'not available' in error_msg or
                'not found' in error_msg or
                'unsupported' in error_msg
            )

            if self.config.song_codec.lower() in high_quality_codecs and is_format_unavailable:
                logger.warning(f"[{track_id}] {self.config.song_codec.upper()} not available, falling back to AAC")
                fallback_message = f"⚠️ {self.config.song_codec.upper()} not available, using AAC instead"

                if not self.fallback_downloader:
                    song_interface = AppleMusicSongInterface(self.interface)
                    song_downloader = AppleMusicSongDownloader(
                        base_downloader=self.base_downloader,
                        interface=song_interface,
                        codec=SongCodec.AAC,
                        no_synced_lyrics=True
                    )

                    music_video_interface = AppleMusicMusicVideoInterface(self.interface)
                    music_video_downloader = AppleMusicMusicVideoDownloader(
                        base_downloader=self.base_downloader,
                        interface=music_video_interface
                    )

                    uploaded_video_interface = AppleMusicUploadedVideoInterface(self.interface)
                    uploaded_video_downloader = AppleMusicUploadedVideoDownloader(
                        base_downloader=self.base_downloader,
                        interface=uploaded_video_interface
                    )

                    self.fallback_downloader = AppleMusicDownloader(
                        interface=self.interface,
                        base_downloader=self.base_downloader,
                        song_downloader=song_downloader,
                        music_video_downloader=music_video_downloader,
                        uploaded_video_downloader=uploaded_video_downloader,
                        skip_processing=False
                    )

                if not url_info:
                    track_url = download_item.media_metadata.get('attributes', {}).get('url', '')
                    if track_url:
                        url_info = self.fallback_downloader.get_url_info(track_url)

                if not url_info:
                    logger.error(f"[{track_id}] Cannot fallback: URL not available")
                    raise

                logger.info(f"[{track_id}] Creating fallback download queue...")
                fallback_queue = await self.fallback_downloader.get_download_queue(url_info)
                if fallback_queue:
                    fallback_item = fallback_queue[0]
                    logger.info(f"[{track_id}] Fallback queue created, downloading with AAC codec...")
                    await self.fallback_downloader.download(fallback_item)
                    logger.info(f"[{track_id}] AAC fallback download completed: {track_artist} - {track_title}")
                    download_item = fallback_item
                else:
                    logger.error(f"[{track_id}] Failed to create fallback download queue")
                    raise Exception(f"Failed to create fallback download queue for track {track_id}")
            else:
                raise

        final_path = Path(download_item.final_path)
        if not final_path.is_absolute():
            final_path = final_path.resolve()

        if not final_path.exists():
            raise FileNotFoundError(f"Downloaded file not found at: {final_path}")

        file_size_mb = final_path.stat().st_size / 1024 / 1024
        logger.info(f"[{track_id}] File ready: {final_path.name} ({file_size_mb:.2f} MB)")

        return str(final_path), fallback_message

    def extract_metadata(self, download_item: DownloadItem) -> dict:
        cover_url = None
        if download_item.cover_url_template:
            cover_url = download_item.cover_url_template.format(w=1200, h=1200)
        elif download_item.media_metadata:
            artwork = download_item.media_metadata.get('attributes', {}).get('artwork', {})
            if artwork and artwork.get('url'):
                cover_url = artwork['url'].format(w=1200, h=1200)

        return {
            'apple_music_id': download_item.media_metadata['id'],
            'url': download_item.media_metadata.get('attributes', {}).get('url', ''),
            'title': download_item.media_tags.title,
            'artist': download_item.media_tags.artist,
            'album': download_item.media_tags.album,
            'duration_ms': download_item.media_metadata.get('attributes', {}).get('durationInMillis', 0),
            'cover_url': cover_url
        }
