"""Document context loaders."""

from .file_loader import FileContextLoader
from .mongo_loader import MongoContextLoader

# PostgreSQL loader (для миграции на PostgreSQL)
try:
    from .postgres_loader import PostgresContextLoader
    _POSTGRESQL_AVAILABLE = True
except ImportError:
    _POSTGRESQL_AVAILABLE = False

__all__ = [
    "MongoContextLoader",
    "FileContextLoader",
    # PostgreSQL loader
    "PostgresContextLoader",
]
