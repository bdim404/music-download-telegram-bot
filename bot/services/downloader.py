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
from gamdl.downloader.exceptions import FormatNotAvailable

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

        wrapper_required_codecs = ['atmos', 'alac']
        requested_codec = self.config.song_codec.lower()

        if not self.config.use_wrapper and requested_codec in wrapper_required_codecs:
            logger.warning(
                f"Codec '{requested_codec.upper()}' requires wrapper service, but use_wrapper is disabled. "
                f"Falling back to AAC codec."
            )
            selected_codec = SongCodec.AAC
        else:
            selected_codec = codec_map.get(requested_codec, SongCodec.AAC_LEGACY)

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

    def _create_fallback_downloader(self, codec: SongCodec) -> AppleMusicDownloader:
        song_interface = AppleMusicSongInterface(self.interface)
        song_downloader = AppleMusicSongDownloader(
            base_downloader=self.base_downloader,
            interface=song_interface,
            codec=codec,
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

        return AppleMusicDownloader(
            interface=self.interface,
            base_downloader=self.base_downloader,
            song_downloader=song_downloader,
            music_video_downloader=music_video_downloader,
            uploaded_video_downloader=uploaded_video_downloader,
            skip_processing=False
        )

    async def _try_aac_fallback_chain(
        self,
        download_item: DownloadItem,
        url_info: UrlInfo,
        primary_codec: str,
        track_id: str,
        track_artist: str,
        track_title: str
    ) -> tuple[DownloadItem, str]:
        AAC_FALLBACK_CHAIN = {
            'aac': ['aac-legacy', 'aac-he-legacy'],
            'aac-he': ['aac', 'aac-legacy'],
            'aac-binaural': ['aac', 'aac-legacy'],
            'aac-he-binaural': ['aac-he', 'aac', 'aac-legacy'],
            'aac-downmix': ['aac', 'aac-legacy'],
            'aac-he-downmix': ['aac-he', 'aac-legacy'],
            'aac-legacy': ['aac'],
            'aac-he-legacy': ['aac-legacy']
        }

        fallback_chain = AAC_FALLBACK_CHAIN.get(primary_codec, [])
        if not fallback_chain:
            raise Exception(
                f"Track '{track_artist} - {track_title}' is not available in {primary_codec.upper()} format."
            )

        attempted_codecs = [primary_codec]

        for fallback_codec_str in fallback_chain:
            attempted_codecs.append(fallback_codec_str)
            logger.warning(f"[{track_id}] {primary_codec.upper()} not available, trying {fallback_codec_str.upper()}")

            codec_map = {
                "aac-legacy": SongCodec.AAC_LEGACY,
                "aac-he-legacy": SongCodec.AAC_HE_LEGACY,
                "aac": SongCodec.AAC,
                "aac-he": SongCodec.AAC_HE,
            }
            fallback_codec = codec_map.get(fallback_codec_str, SongCodec.AAC_LEGACY)

            try:
                fallback_downloader = self._create_fallback_downloader(fallback_codec)

                if not url_info:
                    track_url = download_item.media_metadata.get('attributes', {}).get('url', '')
                    if track_url:
                        url_info = fallback_downloader.get_url_info(track_url)

                if not url_info:
                    logger.error(f"[{track_id}] Cannot try {fallback_codec_str}: URL not available")
                    continue

                fallback_queue = await fallback_downloader.get_download_queue(url_info)
                if not fallback_queue:
                    logger.error(f"[{track_id}] Failed to create queue for {fallback_codec_str}")
                    continue

                fallback_item = fallback_queue[0]

                if not fallback_item.stream_info:
                    logger.warning(f"[{track_id}] {fallback_codec_str.upper()} stream not available")
                    continue

                logger.info(f"[{track_id}] Downloading with {fallback_codec_str.upper()}...")
                await fallback_downloader.download(fallback_item)

                logger.info(f"[{track_id}] Successfully downloaded with {fallback_codec_str.upper()}")
                fallback_message = f"⚠️ {primary_codec.upper()} not available, using {fallback_codec_str.upper()} instead"
                return fallback_item, fallback_message

            except Exception as e:
                logger.warning(f"[{track_id}] {fallback_codec_str.upper()} failed: {e}")
                continue

        raise Exception(
            f"Track '{track_artist} - {track_title}' is not available in any AAC format. "
            f"Attempted: {', '.join(attempted_codecs)}. "
            "This track may not be available in your region or subscription tier."
        )

    def parse_url(self, url: str) -> UrlInfo | None:
        return self.downloader.get_url_info(url)

    async def get_download_queue(self, url_info: UrlInfo) -> list[DownloadItem]:
        return await self.downloader.get_download_queue(url_info)

    async def download_track(self, download_item: DownloadItem, url_info: UrlInfo = None) -> tuple[str, str | None]:
        fallback_message = None
        high_quality_codecs = ['atmos', 'alac']

        AAC_FALLBACK_CHAIN = {
            'aac': ['aac-legacy', 'aac-he-legacy'],
            'aac-he': ['aac', 'aac-legacy'],
            'aac-binaural': ['aac', 'aac-legacy'],
            'aac-he-binaural': ['aac-he', 'aac', 'aac-legacy'],
            'aac-downmix': ['aac', 'aac-legacy'],
            'aac-he-downmix': ['aac-he', 'aac-legacy'],
            'aac-legacy': ['aac'],
            'aac-he-legacy': ['aac-legacy']
        }

        track_title = download_item.media_tags.title
        track_artist = download_item.media_tags.artist
        track_id = download_item.media_metadata['id']

        logger.info(f"[{track_id}] Starting download: {track_artist} - {track_title} (codec: {self.config.song_codec.upper()})")

        try:
            await self.downloader.download(download_item)
            logger.info(f"[{track_id}] Download completed: {track_artist} - {track_title}")
        except Exception as e:
            error_msg = str(e).lower()

            if 'license exchange' in error_msg or 'status":-1002' in error_msg:
                logger.error(f"[{track_id}] DRM license authentication failed: {e}")
                raise Exception(
                    f"DRM authentication failed for '{track_artist} - {track_title}'. "
                    "Please re-authenticate the wrapper service:\n"
                    "1. Stop wrapper: docker ps | grep wrapper && docker stop <container_id>\n"
                    "2. Clear auth: bash clear_wrapper_auth.sh\n"
                    "3. Restart wrapper and re-authenticate"
                )

            is_format_unavailable = (
                isinstance(e, FormatNotAvailable) or
                'not available' in error_msg or
                'not found' in error_msg or
                'unsupported' in error_msg
            )

            if isinstance(e, FormatNotAvailable):
                has_enhanced_hls = (
                    download_item.media_metadata.get('attributes', {})
                    .get('extendedAssetUrls', {})
                    .get('enhancedHls') is not None
                )

                if not has_enhanced_hls:
                    logger.error(
                        f"[{track_id}] Track not available: No enhanced HLS streams in metadata. "
                        "This track may not be available in your region or with your subscription."
                    )
                    raise Exception(
                        f"Track '{track_artist} - {track_title}' is not available for download. "
                        "It may not be available in your region or subscription tier."
                    )

            requested_codec = self.config.song_codec.lower()

            if requested_codec in high_quality_codecs and is_format_unavailable:
                logger.warning(f"[{track_id}] {self.config.song_codec.upper()} not available, falling back to AAC")
                fallback_message = f"⚠️ {self.config.song_codec.upper()} not available, using AAC instead"

                if not self.fallback_downloader:
                    self.fallback_downloader = self._create_fallback_downloader(SongCodec.AAC)

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

                    if not fallback_item.stream_info:
                        logger.error(
                            f"[{track_id}] AAC fallback failed: Stream info not available. "
                            "Track may not be downloadable in your region."
                        )
                        raise Exception(
                            f"Track '{track_artist} - {track_title}' is not available in AAC format either. "
                            "The track may not be available for download in your region or subscription."
                        )

                    logger.info(f"[{track_id}] Fallback queue created, downloading with AAC codec...")
                    try:
                        await self.fallback_downloader.download(fallback_item)
                        logger.info(f"[{track_id}] AAC fallback download completed: {track_artist} - {track_title}")
                        download_item = fallback_item
                    except Exception as fallback_error:
                        fallback_error_msg = str(fallback_error).lower()

                        if 'license exchange' in fallback_error_msg or 'status":-1002' in fallback_error_msg:
                            logger.error(f"[{track_id}] AAC fallback: DRM license authentication failed: {fallback_error}")
                            raise Exception(
                                f"DRM authentication failed for '{track_artist} - {track_title}'. "
                                "Please re-authenticate the wrapper service:\n"
                                "1. Stop wrapper: docker ps | grep wrapper && docker stop <container_id>\n"
                                "2. Clear auth: bash clear_wrapper_auth.sh\n"
                                "3. Restart wrapper and re-authenticate"
                            )

                        if isinstance(fallback_error, FormatNotAvailable):
                            logger.error(
                                f"[{track_id}] AAC fallback download failed: Format not available. "
                                "Track is not available in any supported format (ALAC and AAC both unavailable)."
                            )
                            raise Exception(
                                f"Track '{track_artist} - {track_title}' is not available for download in any format. "
                                "This track may not be available in your region or subscription tier."
                            )

                        logger.error(f"[{track_id}] AAC fallback download failed with unexpected error: {fallback_error}")
                        raise
                else:
                    logger.error(f"[{track_id}] Failed to create fallback download queue")
                    raise Exception(f"Failed to create fallback download queue for track {track_id}")

            elif requested_codec in AAC_FALLBACK_CHAIN and is_format_unavailable:
                try:
                    download_item, fallback_message = await self._try_aac_fallback_chain(
                        download_item, url_info, requested_codec,
                        track_id, track_artist, track_title
                    )
                except Exception:
                    raise
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
