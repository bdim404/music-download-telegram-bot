from config import COOKIES_LOCATION, WVD_LOCATION, STOREFRONT_IDS, AMP_API_HOSTNAME
from pywidevine.license_protocol_pb2 import WidevinePsshData
from http.cookiejar import MozillaCookieJar
from pywidevine import PSSH, Cdm, Device
from xml.etree import ElementTree
from urllib.parse import quote
from yt_dlp import YoutubeDL
from retrying import retry
from pathlib import Path
from io import BytesIO
from time import sleep
from PIL import Image
import subprocess
import functools
import datetime
import ciso8601
import requests
import base64
import shutil
import m3u8
import re
import os

# Set the retrying decorator;
def RetryIfConnectionError(exception):
    return isinstance(exception, requests.exceptions.ConnectionError)

class Downloader:
    # Set the default values of the class;
    def __init__(
        self,
        error: str = None,
        final_path: Path = None,
        temp_path: Path = None,
        cookies_location: Path = None,
        wvd_location: Path = None,
        ffmpeg_location: str = None,
        template_folder_album: str = None,
        template_folder_compilation: str = None,
        template_file_single_disc: str = None,
        template_file_multi_disc: str = None,
        template_date: str = None,
        exclude_tags: str = None,
        truncate: int = None,
        songs_heaac: bool = None,
        **kwargs,
    ):
        self.error = None
        self.final_path = Path("./Apple Music")
        self.temp_path = Path("./temp")
        self.cookies_location = Path(COOKIES_LOCATION)
        self.wvd_location = Path(WVD_LOCATION)
        self.ffmpeg_location = "ffmpeg"
        self.template_folder_album = "{album_artist}/{album}"
        self.template_folder_compilation = "Compilations/{album}"
        self.template_file_single_disc = "{track:02d} {title}"
        self.template_file_multi_disc = "{disc}-{track:02d} {title}"
        self.template_date = "%Y-%m-%dT%H:%M:%SZ"
        self.exclude_tags = None
        self.truncate = 50
        self.songs_flavor = "32:ctrp64" if songs_heaac else "28:ctrp256"

    # Set the setup_session method;
    def setup_session(self) -> None:
        cookies = MozillaCookieJar(self.cookies_location)
        cookies.load(ignore_discard=True, ignore_expires=True)
        self.session = requests.Session()
        self.session.cookies.update(cookies)
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:95.0) Gecko/20100101 Firefox/95.0",
                "Accept": "application/json",
                "Accept-Language": "en-US,en;q=0.5",
                "Accept-Encoding": "gzip, deflate, br",
                "content-type": "application/json",
                "Media-User-Token": self.session.cookies.get_dict()["media-user-token"],
                "x-apple-renewal": "true",
                "DNT": "1",
                "Connection": "keep-alive",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-site",
                "origin": "https://beta.music.apple.com",
            }
        )
        home_page = self.session.get("https://beta.music.apple.com").text
        index_js_uri = re.search(r"/(assets/index-legacy-[^/]+\.js)", home_page).group(
            1
        )
        index_js_page = self.session.get(
            f"https://beta.music.apple.com/{index_js_uri}"
        ).text
        token = re.search('(?=eyJh)(.*?)(?=")', index_js_page).group(1)
        self.session.headers.update({"authorization": f"Bearer {token}"})
        self.country = self.session.cookies.get_dict()["itua"]
        self.storefront = STOREFRONT_IDS[self.country.upper()]

    # Set the setup_cdm method;
    def setup_cdm(self) -> None:
        self.cdm = Cdm.from_device(Device.load(self.wvd_location))
        self.cdm_session = self.cdm.open()

    # Set the get_webplayback method;
    def get_webplayback(self, track_id: str) -> dict:
        webplayback_response = self.session.post(
            "https://play.itunes.apple.com/WebObjects/MZPlay.woa/wa/webPlayback",
            json={
                "salableAdamId": track_id,
                "language": "en-US",
            },
        )
        if webplayback_response.status_code != 200:
            raise Exception(f"Failed to get webplayback: {webplayback_response.text}")
        return webplayback_response.json()["songList"][0]

    # Set the get_stream_url_song method;
    def get_stream_url_song(self, webplayback: dict) -> str:
        return next(
            i for i in webplayback["assets"] if i["flavor"] == self.songs_flavor
        )["URL"]

    # Set the get_encrypted_location_audio method;
    def get_encrypted_location_audio(self, track_id: str) -> Path:
        return self.temp_path / f"{track_id}_encrypted_audio.m4a"

    # Set the get_decrypted_location_audio method;
    def get_decrypted_location_audio(self, track_id: str) -> Path:
        return self.temp_path / f"{track_id}_decrypted_audio.m4a"

    # Set the get_fixed_location method;
    def get_fixed_location(self, track_id: str, file_extension: str) -> Path:
        return self.temp_path / f"{track_id}_fixed{file_extension}"

    # Set the get_license_b64 method;
    def get_license_b64(self, challenge: str, track_uri: str, track_id: str) -> str:
        license_b64_response = self.session.post(
            "https://play.itunes.apple.com/WebObjects/MZPlay.woa/wa/acquireWebPlaybackLicense",
            json={
                "challenge": challenge,
                "key-system": "com.widevine.alpha",
                "uri": track_uri,
                "adamId": track_id,
                "isLibrary": False,
                "user-initiated": True,
            },
        )
        if license_b64_response.status_code != 200:
            raise Exception(f"Failed to get license_b64: {license_b64_response.text}")
        return license_b64_response.json()["license"]

    # Set the get_decryption_key_song method;
    def get_decryption_key_song(self, stream_url: str, track_id: str) -> str:
        track_uri = m3u8.load(stream_url).keys[0].uri
        widevine_pssh_data = WidevinePsshData()
        widevine_pssh_data.algorithm = 1
        widevine_pssh_data.key_ids.append(base64.b64decode(track_uri.split(",")[1]))
        pssh = PSSH(base64.b64encode(widevine_pssh_data.SerializeToString()).decode())
        challenge = base64.b64encode(
            self.cdm.get_license_challenge(self.cdm_session, pssh)
        ).decode()
        license_b64 = self.get_license_b64(challenge, track_uri, track_id)
        self.cdm.parse_license(self.cdm_session, license_b64)
        return next(
            i for i in self.cdm.get_keys(self.cdm_session) if i.type == "CONTENT"
        ).key.hex()

    # Set the get_tags_song method;
    def get_tags_song(self, webplayback: dict) -> dict:
        flavor = next(
            i for i in webplayback["assets"] if i["flavor"] == self.songs_flavor
        )
        metadata = flavor["metadata"]
        tags = {
            "album": metadata["playlistName"],
            "album_artist": metadata["playlistArtistName"],
            "album_id": int(metadata["playlistId"]),
            "album_sort": metadata["sort-album"],
            "artist": metadata["artistName"],
            "artist_id": int(metadata["artistId"]),
            "artist_sort": metadata["sort-artist"],
            "comments": metadata.get("comments"),
            "compilation": metadata["compilation"],
            "composer": metadata.get("composerName"),
            "composer_id": (
                int(metadata.get("composerId")) if metadata.get("composerId") else None
            ),
            "composer_sort": metadata.get("sort-composer"),
            "copyright": metadata.get("copyright"),
            "date": (
                self.sanitize_date(metadata["releaseDate"], self.template_date)
                if metadata.get("releaseDate")
                else None
            ),
            "disc": metadata["discNumber"],
            "disc_total": metadata["discCount"],
            "gapless": metadata["gapless"],
            "genre": metadata["genre"],
            "genre_id": metadata["genreId"],
            "media_type": 1,
            "rating": metadata["explicit"],
            "storefront": metadata["s"],
            "title": metadata["itemName"],
            "title_id": int(metadata["itemId"]),
            "title_sort": metadata["sort-name"],
            "track": metadata["trackNumber"],
            "track_total": metadata["trackCount"],
            "xid": metadata.get("xid"),
        }
        return tags

    # Set the get_sanitized_string method;
    def get_sanitized_string(self, dirty_string: str, is_folder: bool) -> str:
        dirty_string = re.sub(r'[\\/:*?"<>|;]', "_", dirty_string)
        if is_folder:
            dirty_string = dirty_string[: self.truncate]
            if dirty_string.endswith("."):
                dirty_string = dirty_string[:-1] + "_"
        else:
            if self.truncate is not None:
                dirty_string = dirty_string[: self.truncate - 4]
        return dirty_string.strip()

    # Set the get_final_location method;
    def get_final_location(self, tags: dict) -> Path:
        if tags.get("album"):
            final_location_folder = (
                self.template_folder_compilation.split("/")
                if tags.get("compilation")
                else self.template_folder_album.split("/")
            )
            final_location_file = (
                self.template_file_multi_disc.split("/")
                if tags["disc_total"] > 1
                else self.template_file_single_disc.split("/")
            )
        file_extension = ".m4a" 
        final_location_folder = [
            self.get_sanitized_string(i.format(**tags), True)
            for i in final_location_folder
        ]
        final_location_file = [
            self.get_sanitized_string(i.format(**tags), True)
            for i in final_location_file[:-1]
        ] + [
            self.get_sanitized_string(final_location_file[-1].format(**tags), False)
            + file_extension
        ]
        return self.final_path.joinpath(*final_location_folder).joinpath(
            *final_location_file
        )

    # Set the sanitize_date method;
    @staticmethod
    def sanitize_date(date: str, template_date: str):
        datetime_obj = ciso8601.parse_datetime(date)
        return datetime_obj.strftime(template_date)

    # Set the fixup_song_ffmpeg method;
    def fixup_song_ffmpeg(
        self, encrypted_location: Path, decryption_key: str, fixed_location: Path
    ) -> None:
        subprocess.run(
            [
                self.ffmpeg_location,
                "-loglevel",
                "error",
                "-y",
                "-decryption_key",
                decryption_key,
                "-i",
                encrypted_location,
                "-movflags",
                "+faststart",
                "-c",
                "copy",
                fixed_location,
            ],
            check=True,
        )

    # Set the move_to_final_location method;
    def move_to_final_location(
        self, fixed_location: Path, final_location: Path
    ) -> None:
        final_location.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(fixed_location, final_location)
        return final_location

    # Set the cleanup_temp_path method;
    def cleanup_temp_path(self) -> None:
        shutil.rmtree(self.temp_path)

    # Set the download_ytdlp method;
    def download_ytdlp(self, encrypted_location: Path, stream_url: str) -> None:
        with YoutubeDL(
            {
                "quiet": True,
                "no_warnings": True,
                "outtmpl": str(encrypted_location),
                "allow_unplayable_formats": True,
                "fixup": "never",
                "allowed_extractors": ["generic"],
            }
        ) as ydl:
            ydl.download(stream_url)

    # Set the get_cover_url method;
    def get_cover_url(self, webplayback: dict) -> str:
        return (
            webplayback["artwork-urls"]["default"]["url"].rsplit("/", 1)[0]
            + f"/300x300bb.jpg"
        )

    # Set the get_cover method;
    def get_cover(self, cover_url):
        response = requests.get(cover_url)
        return response.content

    # Set the save_cover method;
    def save_cover(self, tags, cover_url):
        os.makedirs('./CoverArt', exist_ok=True)
        cover_bytes = self.get_cover(cover_url)
        image = Image.open(BytesIO(cover_bytes))
        title = tags['title']
        print(title)
        safe_title = re.sub(r'[\\/*?:"<>|]', "", title)
        image.save(f"./CoverArt/{safe_title}.jpg")
        return f"./CoverArt/{safe_title}.jpg"

    # Set the get_song method;
    @retry(retry_on_exception=RetryIfConnectionError, stop_max_attempt_number=10)
    async def get_album(self, album_id: str) -> dict:
        try:
            response = self.session.get(f"https://api.music.apple.com/v1/catalog/us/albums/{album_id}")
            response.raise_for_status()  # 如果状态码表示请求失败，这行代码会抛出一个异常
        except Exception as e:
            self.error = e  # 在异常处理中抛出异常
            return None
        response_json = response.json()
        print(response_json)
        album_data = response_json["data"][0]
        album_songs = album_data['relationships']['tracks']['data']

        songs = []
        for song in album_songs:
            attributes = song.get('attributes', {})
            play_params = attributes.get('playParams', {})
            kind = play_params.get('kind')
            if kind != 'song':  # if kind is not 'song', skip this song.
                continue
            song_id = song['id']
            songs.append((song_id))  # put the id and name of the song as a tuple into the list.
        print(songs)
        return songs

    # Set the get_album method;
    @retry(retry_on_exception=RetryIfConnectionError, stop_max_attempt_number=10)
    async def get_playlist(self, playlist_id: str) -> dict:
        # try to get the playlist data from the apple music api.
        try:
            response = self.session.get(
                f"https://api.music.apple.com/v1/catalog/us/playlists/{playlist_id}",
                params={
                    "limit[tracks]": 300, # set the limit of the tracks to 300.
                },
            )
            response.raise_for_status()  # if the status code indicates that the request failed, this line of code will throw an exception.
        except Exception as e:
            self.error = e  
            return None
        response_json = response.json()
        playlist_data = response_json["data"][0]
        playlist_songs = playlist_data['relationships']['tracks']['data']

        songs = []
        for song in playlist_songs:
            attributes = song.get('attributes', {})
            play_params = attributes.get('playParams', {})
            kind = play_params.get('kind')
            if kind != 'song':  # if kind is not 'song', skip this song.
                continue
            song_id = song['id']
            songs.append((song_id)) # put the id and name of the song as a tuple into the list.

        # Check if there are more songs
        while 'next' in response_json:
            next_url = response_json['next']
            response = self.session.get(next_url)
            response_json = response.json()
            playlist_songs = response_json['data']

            for song in playlist_songs:
                attributes = song.get('attributes', {})
                play_params = attributes.get('playParams', {})
                kind = play_params.get('kind')
                if kind != 'song':  # if kind is not 'song', skip this song.
                    continue
                song_id = song['id']
                songs.append((song_id)) # put the id and name of the song as a tuple into the list.

        return songs