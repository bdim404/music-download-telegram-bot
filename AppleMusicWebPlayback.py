import re,os
import requests
from http.cookiejar import MozillaCookieJar
from retrying import retry
from requests.exceptions import ConnectionError
from PIL import Image
from io import BytesIO

# set the retrying decorator;
def retry_if_connection_error(exception):
    return isinstance(exception, requests.exceptions.ConnectionError)

class WebPlayback:
    def setup_session(self, cookies_location: str) -> requests.Session:
        cookies = MozillaCookieJar(cookies_location)
        cookies.load(ignore_discard=True, ignore_expires=True)
        session = requests.Session()
        session.cookies.update(cookies)
        session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:95.0) Gecko/20100101 Firefox/95.0",
                "Accept": "application/json",
                "Accept-Language": "en-US,en;q=0.5",
                "Accept-Encoding": "gzip, deflate, br",
                "content-type": "application/json",
                "Media-User-Token": session.cookies.get_dict()["media-user-token"],
                "x-apple-renewal": "true",
                "DNT": "1",
                "Connection": "keep-alive",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-site",
                "origin": "https://beta.music.apple.com",
            }
        )
        home_page = session.get("https://beta.music.apple.com").text
        index_js_uri = re.search(r"/(assets/index-legacy-[^/]+\.js)", home_page).group(
            1
        )
        index_js_page = session.get(
            f"https://beta.music.apple.com/{index_js_uri}"
        ).text
        token = re.search('(?=eyJh)(.*?)(?=")', index_js_page).group(1)
        session.headers.update({"authorization": f"Bearer {token}"})
        return session

    @retry(retry_on_exception=retry_if_connection_error, stop_max_attempt_number=5)
    async def get_song(self, session: requests.Session, song_id: str) -> list:
        response = session.get(f"https://api.music.apple.com/v1/catalog/us/songs/{song_id}")
        response_json = response.json()
        song_data = response_json["data"][0]
        song_id = song_data["id"]
        song_name = song_data["attributes"]["name"]
        artist_name = song_data["attributes"]["artistName"]
        track_number = str(song_data["attributes"]["trackNumber"]).zfill(2)
        artwork_url = song_data["attributes"]["artwork"]["url"].format(w=300, h=300)
        os.makedirs('./CoverArt', exist_ok=True)
        # 下载图片
        response = session.get(artwork_url)
        # 打开图片
        image = Image.open(BytesIO(response.content))
        # 保存图片
        image.save(f"./CoverArt/{song_name}.jpg")
        songs = [[song_id, track_number, song_name, artist_name]]
        return songs

    @retry(retry_on_exception=retry_if_connection_error, stop_max_attempt_number=5)
    async def get_album(self, session: requests.Session, album_id: str) -> dict:
        response = session.get(f"https://api.music.apple.com/v1/catalog/us/albums/{album_id}")
        response_json = response.json()
        album_data = response_json["data"][0]
        album_songs = album_data['relationships']['tracks']['data']
        os.makedirs('./CoverArt', exist_ok=True)

        songs = []
        for song in album_songs:
            attributes = song.get('attributes', {})
            play_params = attributes.get('playParams', {})
            kind = play_params.get('kind')
            if kind != 'song':  # 如果 kind 不是 'song'，则跳过这首歌曲
                continue
            song_id = song['id']
            song_name = song['attributes']['name']
            track_number = str(song['attributes']['trackNumber']).zfill(2)
            artist_name = album_data["attributes"]["artistName"]
            artwork_url = song['attributes']['artwork']['url'].format(w=300, h=300)
            # 下载图片
            response = session.get(artwork_url)
            # 打开图片
            image = Image.open(BytesIO(response.content))
            # 保存图片
            image.save(f"./CoverArt/{song_name}.jpg")
            songs.append((song_id, track_number, song_name, artist_name))  # 将歌曲的 id 和名称作为一个元组添加到列表中

        return songs

    @retry(retry_on_exception=retry_if_connection_error, stop_max_attempt_number=5)
    async def get_playlist(self, session: requests.Session, playlist_id: str) -> dict:
        response = session.get(f"https://api.music.apple.com/v1/catalog/us/playlists/{playlist_id}")
        response_json = response.json()
        playlist_data = response_json["data"][0]
        playlist_songs = playlist_data['relationships']['tracks']['data']
        os.makedirs('./CoverArt', exist_ok=True)

        songs = []
        for song in playlist_songs:
            attributes = song.get('attributes', {})
            play_params = attributes.get('playParams', {})
            kind = play_params.get('kind')
            if kind != 'song':  # 如果 kind 不是 'song'，则跳过这首歌曲
                continue
            song_id = song['id']
            song_name = song['attributes']['name']
            track_number = str(song['attributes']['trackNumber']).zfill(2)
            artist_name = attributes["artistName"]
            artwork_url = song['attributes']['artwork']['url'].format(w=300, h=300)
            # 下载图片
            response = session.get(artwork_url)
            # 打开图片
            image = Image.open(BytesIO(response.content))
            # 保存图片
            image.save(f"./CoverArt/{song_name}.jpg")
            songs.append((song_id, track_number, song_name, artist_name))
        return songs