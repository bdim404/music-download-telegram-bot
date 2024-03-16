import re,os
import requests
from http.cookiejar import MozillaCookieJar
from retrying import retry
from requests.exceptions import ConnectionError
from PIL import Image
from io import BytesIO

# set the retrying decorator;
def RetryIfConnectionError(exception):
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

    @retry(retry_on_exception=RetryIfConnectionError, stop_max_attempt_number=5)
    async def GetSong(self, session: requests.Session, songId: str) -> list:
        response = session.get(f"https://api.music.apple.com/v1/catalog/us/songs/{songId}")
        responseJson = response.json()
        songData = responseJson["data"][0]
        songId = songData["id"]
        songName = songData["attributes"]["name"]
        artistName = songData["attributes"]["artistName"]
        trackNumber = str(songData["attributes"]["trackNumber"]).zfill(2)
        artworkUrl = songData["attributes"]["artwork"]["url"].format(w=300, h=300)
        os.makedirs('./CoverArt', exist_ok=True)
        # 下载图片
        response = session.get(artworkUrl)
        # 打开图片
        image = Image.open(BytesIO(response.content))
        # 保存图片
        image.save(f"./CoverArt/{songName}.jpg")
        songs = [[songId, trackNumber, songName, artistName]]
        return songs

    @retry(retry_on_exception=RetryIfConnectionError, stop_max_attempt_number=5)
    async def GetAlbum(self, session: requests.Session, album_id: str) -> dict:
        response = session.get(f"https://api.music.apple.com/v1/catalog/us/albums/{album_id}")
        responseJson = response.json()
        albumData = responseJson["data"][0]
        albumSongs = albumData['relationships']['tracks']['data']
        os.makedirs('./CoverArt', exist_ok=True)

        songs = []
        for song in albumSongs:
            attributes = song.get('attributes', {})
            playParams = attributes.get('playParams', {})
            kind = playParams.get('kind')
            if kind != 'song':  # 如果 kind 不是 'song'，则跳过这首歌曲
                continue
            songId = song['id']
            songName = song['attributes']['name']
            trackNumber = str(song['attributes']['trackNumber']).zfill(2)
            artistName = albumData["attributes"]["artistName"]
            artworkUrl = song['attributes']['artwork']['url'].format(w=300, h=300)
            # 下载图片
            response = session.get(artworkUrl)
            # 打开图片
            image = Image.open(BytesIO(response.content))
            # 保存图片
            image.save(f"./CoverArt/{songName}.jpg")
            songs.append((songId, trackNumber, songName, artistName))  # 将歌曲的 id 和名称作为一个元组添加到列表中

        return songs

    @retry(retry_on_exception=RetryIfConnectionError, stop_max_attempt_number=5)
    async def GetPlaylist(self, session: requests.Session, playlist_id: str) -> dict:
        response = session.get(f"https://api.music.apple.com/v1/catalog/us/playlists/{playlist_id}")
        responseJson = response.json()
        playlistData = responseJson["data"][0]
        playlistDongs = playlistData['relationships']['tracks']['data']
        os.makedirs('./CoverArt', exist_ok=True)

        songs = []
        for song in playlistDongs:
            attributes = song.get('attributes', {})
            playParams = attributes.get('playParams', {})
            kind = playParams.get('kind')
            if kind != 'song':  # 如果 kind 不是 'song'，则跳过这首歌曲
                continue
            songId = song['id']
            songName = song['attributes']['name']
            trackNumber = str(song['attributes']['trackNumber']).zfill(2)
            artistName = attributes["artistName"]
            artworkUrl = song['attributes']['artwork']['url'].format(w=300, h=300)
            # 下载图片
            response = session.get(artworkUrl)
            # 打开图片
            image = Image.open(BytesIO(response.content))
            # 保存图片
            image.save(f"./CoverArt/{songName}.jpg")
            songs.append((songId, trackNumber, songName, artistName))
        return songs