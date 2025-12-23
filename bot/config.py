from dataclasses import dataclass, field
import yaml
from pathlib import Path


@dataclass
class Config:
    bot_token: str
    cookies_path: str = "./cookies.txt"
    whitelist_users: list[int] = field(default_factory=list)

    max_concurrent_per_user: int = 2
    max_concurrent_global: int = 5
    max_file_size_mb: int = 50

    database_path: str = "./data/cache.db"
    temp_path: str = "./data/temp"

    @classmethod
    def load(cls, path: str = "config.yaml"):
        config_path = Path(path)
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        with open(config_path) as f:
            data = yaml.safe_load(f)

        return cls(**data)
