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

# Set the Apple Music API hostname; 
AMP_API_HOSTNAME = "https://amp-api.music.apple.com"

# Set the Apple Music Storefront IDs;
STOREFRONT_IDS = {
    "AE": "143481-2,32",
    "AG": "143540-2,32",
    "AI": "143538-2,32",
    "AL": "143575-2,32",
    "AM": "143524-2,32",
    "AO": "143564-2,32",
    "AR": "143505-28,32",
    "AT": "143445-4,32",
    "AU": "143460-27,32",
    "AZ": "143568-2,32",
    "BB": "143541-2,32",
    "BE": "143446-2,32",
    "BF": "143578-2,32",
    "BG": "143526-2,32",
    "BH": "143559-2,32",
    "BJ": "143576-2,32",
    "BM": "143542-2,32",
    "BN": "143560-2,32",
    "BO": "143556-28,32",
    "BR": "143503-15,32",
    "BS": "143539-2,32",
    "BT": "143577-2,32",
    "BW": "143525-2,32",
    "BY": "143565-2,32",
    "BZ": "143555-2,32",
    "CA": "143455-6,32",
    "CG": "143582-2,32",
    "CH": "143459-57,32",
    "CL": "143483-28,32",
    "CN": "143465-19,32",
    "CO": "143501-28,32",
    "CR": "143495-28,32",
    "CV": "143580-2,32",
    "CY": "143557-2,32",
    "CZ": "143489-2,32",
    "DE": "143443-4,32",
    "DK": "143458-2,32",
    "DM": "143545-2,32",
    "DO": "143508-28,32",
    "DZ": "143563-2,32",
    "EC": "143509-28,32",
    "EE": "143518-2,32",
    "EG": "143516-2,32",
    "ES": "143454-8,32",
    "FI": "143447-2,32",
    "FJ": "143583-2,32",
    "FM": "143591-2,32",
    "FR": "143442-3,32",
    "GB": "143444-2,32",
    "GD": "143546-2,32",
    "GH": "143573-2,32",
    "GM": "143584-2,32",
    "GR": "143448-2,32",
    "GT": "143504-28,32",
    "GW": "143585-2,32",
    "GY": "143553-2,32",
    "HK": "143463-45,32",
    "HN": "143510-28,32",
    "HR": "143494-2,32",
    "HU": "143482-2,32",
    "ID": "143476-2,32",
    "IE": "143449-2,32",
    "IL": "143491-2,32",
    "IN": "143467-2,32",
    "IS": "143558-2,32",
    "IT": "143450-7,32",
    "JM": "143511-2,32",
    "JO": "143528-2,32",
    "JP": "143462-9,32",
    "KE": "143529-2,32",
    "KG": "143586-2,32",
    "KH": "143579-2,32",
    "KN": "143548-2,32",
    "KR": "143466-13,32",
    "KW": "143493-2,32",
    "KY": "143544-2,32",
    "KZ": "143517-2,32",
    "LA": "143587-2,32",
    "LB": "143497-2,32",
    "LC": "143549-2,32",
    "LK": "143486-2,32",
    "LR": "143588-2,32",
    "LT": "143520-2,32",
    "LU": "143451-2,32",
    "LV": "143519-2,32",
    "MD": "143523-2,32",
    "MG": "143531-2,32",
    "MK": "143530-2,32",
    "ML": "143532-2,32",
    "MN": "143592-2,32",
    "MO": "143515-45,32",
    "MR": "143590-2,32",
    "MS": "143547-2,32",
    "MT": "143521-2,32",
    "MU": "143533-2,32",
    "MW": "143589-2,32",
    "MX": "143468-28,32",
    "MY": "143473-2,32",
    "MZ": "143593-2,32",
    "NA": "143594-2,32",
    "NE": "143534-2,32",
    "NG": "143561-2,32",
    "NI": "143512-28,32",
    "NL": "143452-10,32",
    "NO": "143457-2,32",
    "NP": "143484-2,32",
    "NZ": "143461-27,32",
    "OM": "143562-2,32",
    "PA": "143485-28,32",
    "PE": "143507-28,32",
    "PG": "143597-2,32",
    "PH": "143474-2,32",
    "PK": "143477-2,32",
    "PL": "143478-2,32",
    "PT": "143453-24,32",
    "PW": "143595-2,32",
    "PY": "143513-28,32",
    "QA": "143498-2,32",
    "RO": "143487-2,32",
    "RU": "143469-16,32",
    "SA": "143479-2,32",
    "SB": "143601-2,32",
    "SC": "143599-2,32",
    "SE": "143456-17,32",
    "SG": "143464-19,32",
    "SI": "143499-2,32",
    "SK": "143496-2,32",
    "SL": "143600-2,32",
    "SN": "143535-2,32",
    "SR": "143554-2,32",
    "ST": "143598-2,32",
    "SV": "143506-28,32",
    "SZ": "143602-2,32",
    "TC": "143552-2,32",
    "TD": "143581-2,32",
    "TH": "143475-2,32",
    "TJ": "143603-2,32",
    "TM": "143604-2,32",
    "TN": "143536-2,32",
    "TR": "143480-2,32",
    "TT": "143551-2,32",
    "TW": "143470-18,32",
    "TZ": "143572-2,32",
    "UA": "143492-2,32",
    "UG": "143537-2,32",
    "US": "143441-1,32",
    "UY": "143514-2,32",
    "UZ": "143566-2,32",
    "VC": "143550-2,32",
    "VE": "143502-28,32",
    "VG": "143543-2,32",
    "VN": "143471-2,32",
    "YE": "143571-2,32",
    "ZA": "143472-2,32",
    "ZW": "143605-2,32",
}

class Downloader:
    # Set the default values of the class;
    def __init__(
        self,
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
        self.final_path = Path("./Apple Music")
        self.temp_path = Path("./temp")
        self.cookies_location = Path("./cookies.txt")
        self.wvd_location = Path("./device.wvd")
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
    @retry(retry_on_exception=RetryIfConnectionError, stop_max_attempt_number=5)
    async def GetAlbum(self, album_id: str) -> dict:
        response = self.session.get(f"https://api.music.apple.com/v1/catalog/us/albums/{album_id}")
        responseJson = response.json()
        albumData = responseJson["data"][0]
        albumSongs = albumData['relationships']['tracks']['data']

        songs = []
        for song in albumSongs:
            attributes = song.get('attributes', {})
            playParams = attributes.get('playParams', {})
            kind = playParams.get('kind')
            if kind != 'song':  # if kind is not 'song', skip this song.
                continue
            songId = song['id']
            songs.append((songId))  # put the id and name of the song as a tuple into the list.
        return songs

    # Set the get_album method;
    @retry(retry_on_exception=RetryIfConnectionError, stop_max_attempt_number=5)
    async def GetPlaylist(self, playlist_id: str) -> dict:
        response = self.session.get(f"https://api.music.apple.com/v1/catalog/us/playlists/{playlist_id}")
        responseJson = response.json()
        playlistData = responseJson["data"][0]
        playlistDongs = playlistData['relationships']['tracks']['data']

        songs = []
        for song in playlistDongs:
            attributes = song.get('attributes', {})
            playParams = attributes.get('playParams', {})
            kind = playParams.get('kind')
            if kind != 'song':  # if kind is not 'song', skip this song.
                continue
            songId = song['id']
            songs.append((songId)) # put the id and name of the song as a tuple into the list.
        return songs