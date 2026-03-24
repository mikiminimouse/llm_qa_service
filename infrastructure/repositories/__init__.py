"""Repository implementations.

Поддерживает два хранилища:
- MongoDB (оригинальный) - через MongoQARepository
- PostgreSQL (для миграции) - через PostgresQARepository
"""

from .mongo_qa_repository import MongoQARepository

# PostgreSQL репозиторий (для миграции на PostgreSQL)
try:
    from .postgres_qa_repository import (
        PostgresQARepository,
        create_postgres_qa_repository,
        is_postgresql_enabled,
        get_postgres_config,
        get_postgres_dsn,
    )
    _POSTGRESQL_AVAILABLE = True
except ImportError:
    _POSTGRESQL_AVAILABLE = False

__all__ = [
    "MongoQARepository",
    # PostgreSQL репозиторий
    "PostgresQARepository",
    "create_postgres_qa_repository",
    "is_postgresql_enabled",
    "get_postgres_config",
    "get_postgres_dsn",
]
