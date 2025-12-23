import sys
import logging
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

        interface = AppleMusicInterface(
            self.apple_music_api,
            ItunesApi(
                self.apple_music_api.storefront,
                self.apple_music_api.language
            )
        )

        base_downloader = AppleMusicBaseDownloader(
            output_path=self.config.temp_path,
            temp_path=self.config.temp_path,
            use_wrapper=False,
            wvd_path=None,
            save_cover=False,
            save_playlist=False,
            silent=True,
            overwrite=True
        )

        song_interface = AppleMusicSongInterface(interface)
        song_downloader = AppleMusicSongDownloader(
            base_downloader=base_downloader,
            interface=song_interface,
            codec=SongCodec.AAC_LEGACY,
            no_synced_lyrics=True
        )

        music_video_interface = AppleMusicMusicVideoInterface(interface)
        music_video_downloader = AppleMusicMusicVideoDownloader(
            base_downloader=base_downloader,
            interface=music_video_interface
        )

        uploaded_video_interface = AppleMusicUploadedVideoInterface(interface)
        uploaded_video_downloader = AppleMusicUploadedVideoDownloader(
            base_downloader=base_downloader,
            interface=uploaded_video_interface
        )

        self.downloader = AppleMusicDownloader(
            interface=interface,
            base_downloader=base_downloader,
            song_downloader=song_downloader,
            music_video_downloader=music_video_downloader,
            uploaded_video_downloader=uploaded_video_downloader,
            skip_processing=False
        )

        if not base_downloader.full_mp4decrypt_path:
            raise RuntimeError(
                "mp4decrypt not found. Please install Bento4:\n"
                "  macOS: brew install bento4\n"
                "  Ubuntu: sudo apt-get install bento4"
            )

    def parse_url(self, url: str) -> UrlInfo | None:
        return self.downloader.get_url_info(url)

    async def get_download_queue(self, url_info: UrlInfo) -> list[DownloadItem]:
        return await self.downloader.get_download_queue(url_info)

    async def download_track(self, download_item: DownloadItem) -> str:
        await self.downloader.download(download_item)

        final_path = Path(download_item.final_path)
        if not final_path.is_absolute():
            final_path = final_path.resolve()

        if not final_path.exists():
            raise FileNotFoundError(f"Downloaded file not found at: {final_path}")

        return str(final_path)

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
