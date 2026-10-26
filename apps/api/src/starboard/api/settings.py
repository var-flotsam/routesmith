"""API settings, read from the environment with the `STARBOARD_` prefix.

These are deployment settings, not solver tunables; each default has its reason.
"""

from datetime import timedelta

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STARBOARD_")

    # The local Compose database; deployed environments set STARBOARD_DATABASE_URL.
    database_url: str = "postgresql+asyncpg://starboard:starboard@localhost:5432/starboard"
    # Where sign-in links point.
    app_base_url: str = "http://localhost:5173"
    # A magic link is used minutes after it is sent; a short life limits a leaked email.
    login_token_ttl: timedelta = timedelta(minutes=15)
    # A planner signs in about once a working week.
    session_ttl: timedelta = timedelta(days=7)
    # Off only for plain-HTTP local development.
    cookie_secure: bool = True
