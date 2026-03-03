from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://user:password@localhost:5432/todo_db"
    api_key: str = "sk_ants_12345"
    embedding_api_key: str = ""
    embedding_base_url: str = "https://api.openai.com/v1"
    log_level: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
