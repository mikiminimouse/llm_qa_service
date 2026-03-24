"""Application settings using Pydantic Settings."""

from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # MongoDB - compatible with docling_integration
    MONGO_URI: str = "mongodb://admin:password@localhost:27018/?authSource=admin"
    MONGO_DATABASE: str = "docling_metadata"
    MONGO_PROTOCOLS_COLLECTION: str = "docling_results"
    MONGO_QA_COLLECTION: str = "qa_results"

    # PostgreSQL - для миграции с MongoDB
    LOCAL_PG_SERVER: str = "localhost"
    LOCAL_PG_PORT: int = 5433
    LOCAL_PG_USER: str = "delivery_user"
    LOCAL_PG_PASSWORD: str = ""
    LOCAL_PG_DB: str = "delivery_processing"

    # Source selection (для миграции)
    USE_POSTGRESQL_SOURCE: bool = False  # True для чтения из PostgreSQL вместо MongoDB

    # GLM-4.7 via Z.ai proxy (OpenAI-compatible)
    GLM_API_KEY: str = ""
    GLM_BASE_URL: str = "https://api.z.ai/api/coding/paas/v4"
    GLM_MODEL: str = "GLM-4.7"
    GLM_TIMEOUT: float = 45.0  # Уменьшено: 60 → 45 сек
    GLM_MAX_RETRIES: int = 2    # Уменьшено: 3 → 2
    GLM_RETRY_DELAY: float = 0.5  # Уменьшено: 1.0 → 0.5 сек
    GLM_MAX_TOKENS: int = 4096
    GLM_TEMPERATURE: float = 0.1

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8001
    DEBUG: bool = False

    # Processing
    BATCH_SIZE: int = 10
    SKIP_PROCESSED: bool = True

    # INN Enrichment
    ENABLE_INN_ENRICHMENT: bool = True

    # Prompts
    PROMPTS_DIR: str = "prompts"
    PROMPT_VERSION: str = "v4"  # v4 or v5 (v5 has improved INN extraction but needs more testing)

    # UNIT directories for saving qa_results.json
    UNIT_BASE_PATHS: list[str] = [
        "/root/winners_preprocessor/final_preprocessing/Data",
        "/root/winners_preprocessor/archive/Data",
    ]
    SAVE_TO_UNIT_DIR: bool = True


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
