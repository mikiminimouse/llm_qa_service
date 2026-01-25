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

    # GLM-4.7 via Z.ai proxy (OpenAI-compatible)
    GLM_API_KEY: str = ""
    GLM_BASE_URL: str = "https://api.z.ai/api/coding/paas/v4"
    GLM_MODEL: str = "GLM-4.7"
    GLM_TIMEOUT: float = 60.0
    GLM_MAX_RETRIES: int = 3
    GLM_RETRY_DELAY: float = 1.0
    GLM_MAX_TOKENS: int = 4096
    GLM_TEMPERATURE: float = 0.1

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8001
    DEBUG: bool = False

    # Processing
    BATCH_SIZE: int = 10
    SKIP_PROCESSED: bool = True

    # Prompts
    PROMPTS_DIR: str = "prompts"

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
