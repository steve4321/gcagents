from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings

ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT_DIR / "config"
DATA_DIR = ROOT_DIR / "data"

DB_PATH = DATA_DIR / "gcagents.db"


class AppConfig(BaseSettings):
    deepseek_api_key: str = ""
    minimax_api_key: str = ""
    zhipu_api_key: str = ""
    suno_api_key: str = ""
    itch_api_key: str = ""
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    x_bearer_token: str = ""
    butler_api_key: str = ""
    butler_username: str = ""

    db_url: str = f"sqlite+aiosqlite:///{ROOT_DIR / 'data' / 'gcagents.db'}"
    comfyui_url: str = "http://localhost:8188"

    games_output_dir: Path = DATA_DIR / "games"
    build_dir: Path = DATA_DIR / "builds"
    dashboard_port: int = 8080

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


class SourceConfig(BaseModel):
    type: str
    base_url: str = ""
    auth_type: str = "none"
    api_key_env: str = ""
    api_secret_env: str = ""
    rate_limit_per_second: int = 5
    throttle_per_second: int = 5
    cache_ttl_seconds: int = 300
    feeds: list[str] = []
    endpoints: dict[str, str] = {}
    subreddits: list[str] = []
    categories: list[str] = []
    charts: list[str] = []
    platforms: list[str] = []
    tags: list[str] = []
    search_terms: list[str] = []


class AllSourcesConfig(BaseModel):
    sources: dict[str, SourceConfig]


def load_config() -> AppConfig:
    return AppConfig()


def load_sources() -> AllSourcesConfig:
    path = CONFIG_DIR / "sources.yaml"
    try:
        with open(path) as f:
            raw = yaml.safe_load(f)
    except (FileNotFoundError, yaml.YAMLError) as e:
        raise RuntimeError(f"Failed to load sources config from {path}: {e}") from e
    return AllSourcesConfig(**raw)


def load_agents_config() -> dict:
    path = CONFIG_DIR / "agents.yaml"
    try:
        with open(path) as f:
            return yaml.safe_load(f)
    except (FileNotFoundError, yaml.YAMLError) as e:
        raise RuntimeError(f"Failed to load agents config from {path}: {e}") from e
