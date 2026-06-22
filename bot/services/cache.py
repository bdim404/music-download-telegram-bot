from typing import Optional
from ..models.database import Database


class CacheService:
    def __init__(self, db: Database):
        self.db = db

    async def get_cached_song(self, apple_music_id: str, codec: str) -> Optional[dict]:
        query = "SELECT * FROM songs WHERE apple_music_id = ? AND codec = ?"
        result = await self.db.fetch_one(query, (apple_music_id, codec))

        if result:
            await self.db.execute(
                "UPDATE songs SET access_count = access_count + 1, "
                "last_accessed = CURRENT_TIMESTAMP WHERE id = ?",
                (result['id'],)
            )

        return result

    async def store_song(
        self,
        metadata: dict,
        codec: str,
        file_id: str,
        file_unique_id: str,
        file_size: int
    ):
        query = """
        INSERT INTO songs (
            apple_music_id, codec, url, title, artist, album,
            duration_ms, cover_url, file_id, file_unique_id, file_size
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(apple_music_id, codec) DO UPDATE SET
            file_id = excluded.file_id,
            file_unique_id = excluded.file_unique_id,
            file_size = excluded.file_size,
            last_accessed = CURRENT_TIMESTAMP
        """

        await self.db.execute(query, (
            metadata['apple_music_id'],
            codec,
            metadata['url'],
            metadata['title'],
            metadata['artist'],
            metadata['album'],
            metadata['duration_ms'],
            metadata['cover_url'],
            file_id,
            file_unique_id,
            file_size
        ))

    async def get_user(self, user_id: int) -> Optional[dict]:
        query = "SELECT * FROM users WHERE user_id = ?"
        return await self.db.fetch_one(query, (user_id,))

    async def is_user_whitelisted(self, user_id: int) -> bool:
        user = await self.get_user(user_id)
        return bool(user and user.get('is_whitelisted'))

    async def list_whitelisted_users(self) -> list[dict]:
        query = """
        SELECT user_id, username, first_name, download_codec, send_lyrics, download_count, last_activity, created_at
        FROM users
        WHERE is_whitelisted = 1
        ORDER BY last_activity DESC, created_at DESC
        """
        return await self.db.fetch_all(query)

    async def set_user_whitelist(
        self,
        user_id: int,
        is_whitelisted: bool,
        username: str = None,
        first_name: str = None
    ):
        query = """
        INSERT INTO users (user_id, username, first_name, is_whitelisted)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username = COALESCE(excluded.username, username),
            first_name = COALESCE(excluded.first_name, first_name),
            is_whitelisted = excluded.is_whitelisted
        """
        await self.db.execute(query, (user_id, username, first_name, int(is_whitelisted)))

    async def get_user_codec(self, user_id: int, default_codec: str) -> str:
        user = await self.get_user(user_id)
        if user and user.get('download_codec'):
            return user['download_codec']
        return default_codec

    async def get_user_send_lyrics(self, user_id: int) -> bool:
        user = await self.get_user(user_id)
        return bool(user and user.get('send_lyrics'))

    async def set_user_send_lyrics(
        self,
        user_id: int,
        send_lyrics: bool,
        username: str = None,
        first_name: str = None
    ):
        query = """
        INSERT INTO users (user_id, username, first_name, send_lyrics)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username = COALESCE(excluded.username, username),
            first_name = COALESCE(excluded.first_name, first_name),
            send_lyrics = excluded.send_lyrics
        """
        await self.db.execute(query, (user_id, username, first_name, int(send_lyrics)))

    async def set_user_codec(
        self,
        user_id: int,
        codec: str,
        username: str = None,
        first_name: str = None
    ):
        query = """
        INSERT INTO users (user_id, username, first_name, download_codec)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username = COALESCE(excluded.username, username),
            first_name = COALESCE(excluded.first_name, first_name),
            download_codec = excluded.download_codec
        """
        await self.db.execute(query, (user_id, username, first_name, codec))

    async def update_user_activity(self, user_id: int, username: str = None, first_name: str = None):
        query = """
        INSERT INTO users (user_id, username, first_name, last_activity, download_count)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP, 1)
        ON CONFLICT(user_id) DO UPDATE SET
            username = excluded.username,
            first_name = excluded.first_name,
            last_activity = CURRENT_TIMESTAMP,
            download_count = download_count + 1
        """
        await self.db.execute(query, (user_id, username, first_name))
