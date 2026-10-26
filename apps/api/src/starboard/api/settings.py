"""API settings, read from the environment with the `STARBOARD_` prefix.

These are deployment settings, not solver tunables; each default has its reason.
"""

from datetime import timedelta
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STARBOARD_")

    # The local Compose database; deployed environments set STARBOARD_DATABASE_URL.
    database_url: str = "postgresql+asyncpg://starboard:starboard@localhost:5432/starboard"
    # The web app, where a signed-in browser lands.
    app_base_url: str = "http://localhost:5173"
    # The API as the browser reaches it (the web app proxies it under /api); sign-in links
    # point here.
    api_public_url: str = "http://localhost:5173/api"
    # A magic link is used minutes after it is sent; a short life limits a leaked email.
    login_token_ttl: timedelta = timedelta(minutes=15)
    # A planner signs in about once a working week.
    session_ttl: timedelta = timedelta(days=7)
    # Off only for plain-HTTP local development.
    cookie_secure: bool = True
    # The local Compose Redis, which the worker reads jobs from.
    redis_url: str = "redis://localhost:6379"
    # Uploaded files in development; deployed environments use S3-compatible storage.
    upload_dir: Path = Path("cache/uploads")
    # The street network cache, shared with the CLI.
    osm_cache_dir: Path = Path("cache/osm")
    # Geocoder answers, kept so an address is asked for once.
    geocode_cache_dir: Path = Path("cache/geocode")
    # An OSM extract (.osm.pbf) to build networks from instead of Overpass, if set.
    osm_extract: Path | None = None

    @field_validator("osm_extract", mode="before")
    @classmethod
    def _unset_when_blank(cls, value: object) -> object:
        """An empty STARBOARD_OSM_EXTRACT, as Compose passes when it is unset, means none."""
        return None if value == "" else value

    # A planner's stop list is a few thousand rows; this leaves room for a whole area.
    max_upload_bytes: int = 20 * 1024 * 1024
