from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Konfiguracja wyłącznie ze zmiennych środowiskowych (patrz .env.example)."""

    model_config = SettingsConfigDict(env_prefix="OFFCUT_", env_file=None)

    database_url: str = "postgresql+psycopg://offcut:offcut@localhost:5432/offcut"
    secret_key: str  # wymagany – brak wartości domyślnej celowo
    session_hours: int = 12
    cookie_secure: bool = False  # True za HTTPS
    cors_origins: list[str] = ["http://localhost:5173"]

    optimizer_max_nodes: int = 300_000
    optimizer_time_limit_s: float = 3.0
    max_pieces_per_project: int = 200
    max_stock_candidates: int = 400


@lru_cache
def get_settings() -> Settings:
    return Settings()
