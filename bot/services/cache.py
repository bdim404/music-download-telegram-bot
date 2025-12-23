from typing import Optional
from ..models.database import Database


class CacheService:
    def __init__(self, db: Database):
        self.db = db

    async def get_cached_song(self, apple_music_id: str) -> Optional[dict]:
        query = "SELECT * FROM songs WHERE apple_music_id = ?"
        result = await self.db.fetch_one(query, (apple_music_id,))

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
        file_id: str,
        file_unique_id: str,
        file_size: int
    ):
        query = """
        INSERT INTO songs (
            apple_music_id, url, title, artist, album,
            duration_ms, cover_url, file_id, file_unique_id, file_size
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(apple_music_id) DO UPDATE SET
            file_id = excluded.file_id,
            file_unique_id = excluded.file_unique_id,
            last_accessed = CURRENT_TIMESTAMP
        """

        await self.db.execute(query, (
            metadata['apple_music_id'],
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
