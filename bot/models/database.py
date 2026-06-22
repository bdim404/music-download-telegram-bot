import aiosqlite
from pathlib import Path
from typing import Optional


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.db: Optional[aiosqlite.Connection] = None

    async def initialize(self):
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        self.db = await aiosqlite.connect(self.db_path)
        self.db.row_factory = aiosqlite.Row

        await self._create_tables()
        await self._migrate_tables()

    async def _create_tables(self):
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS songs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                apple_music_id TEXT NOT NULL,
                codec TEXT NOT NULL DEFAULT 'aac-legacy',
                url TEXT NOT NULL,
                title TEXT NOT NULL,
                artist TEXT NOT NULL,
                album TEXT,
                duration_ms INTEGER,
                cover_url TEXT,
                file_id TEXT NOT NULL,
                file_unique_id TEXT,
                file_size INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                access_count INTEGER DEFAULT 0,
                UNIQUE(apple_music_id, codec)
            )
        """)

        await self.db.execute("""
            CREATE INDEX IF NOT EXISTS idx_apple_music_id ON songs(apple_music_id)
        """)

        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                is_whitelisted BOOLEAN DEFAULT 0,
                download_count INTEGER DEFAULT 0,
                last_activity TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await self.db.execute("""
            CREATE INDEX IF NOT EXISTS idx_whitelisted ON users(is_whitelisted)
        """)

        await self.db.commit()

    async def _migrate_tables(self):
        await self._migrate_songs_codec_cache()
        await self._ensure_column("users", "download_codec", "TEXT")
        await self.db.execute("""
            CREATE INDEX IF NOT EXISTS idx_songs_codec ON songs(codec)
        """)
        await self.db.commit()

    async def _ensure_column(self, table: str, column: str, definition: str):
        async with self.db.execute(f"PRAGMA table_info({table})") as cursor:
            columns = [row["name"] for row in await cursor.fetchall()]

        if column not in columns:
            await self.db.execute(
                f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
            )

    async def _migrate_songs_codec_cache(self):
        async with self.db.execute("PRAGMA table_info(songs)") as cursor:
            columns = [row["name"] for row in await cursor.fetchall()]

        if not columns:
            return

        async with self.db.execute("PRAGMA index_list(songs)") as cursor:
            indexes = await cursor.fetchall()

        has_old_unique = False
        for index in indexes:
            if not index["unique"]:
                continue
            async with self.db.execute(f"PRAGMA index_info({index['name']})") as cursor:
                index_columns = [row["name"] for row in await cursor.fetchall()]
            if index_columns == ["apple_music_id"]:
                has_old_unique = True
                break

        if "codec" in columns and not has_old_unique:
            return

        await self.db.execute("ALTER TABLE songs RENAME TO songs_old")
        await self.db.execute("""
            CREATE TABLE songs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                apple_music_id TEXT NOT NULL,
                codec TEXT NOT NULL DEFAULT 'aac-legacy',
                url TEXT NOT NULL,
                title TEXT NOT NULL,
                artist TEXT NOT NULL,
                album TEXT,
                duration_ms INTEGER,
                cover_url TEXT,
                file_id TEXT NOT NULL,
                file_unique_id TEXT,
                file_size INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                access_count INTEGER DEFAULT 0,
                UNIQUE(apple_music_id, codec)
            )
        """)
        codec_expr = "COALESCE(codec, 'aac-legacy')" if "codec" in columns else "'aac-legacy'"
        await self.db.execute(f"""
            INSERT INTO songs (
                id, apple_music_id, codec, url, title, artist, album,
                duration_ms, cover_url, file_id, file_unique_id, file_size,
                created_at, last_accessed, access_count
            )
            SELECT
                id, apple_music_id, {codec_expr}, url, title, artist, album,
                duration_ms, cover_url, file_id, file_unique_id, file_size,
                created_at, last_accessed, access_count
            FROM songs_old
        """)
        await self.db.execute("DROP TABLE songs_old")
        await self.db.execute("""
            CREATE INDEX IF NOT EXISTS idx_apple_music_id ON songs(apple_music_id)
        """)
        await self.db.execute("""
            CREATE INDEX IF NOT EXISTS idx_songs_codec ON songs(codec)
        """)

    async def fetch_one(self, query: str, params: tuple = ()):
        async with self.db.execute(query, params) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def fetch_all(self, query: str, params: tuple = ()):
        async with self.db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def execute(self, query: str, params: tuple = ()):
        await self.db.execute(query, params)
        await self.db.commit()

    async def close(self):
        if self.db:
            await self.db.close()
