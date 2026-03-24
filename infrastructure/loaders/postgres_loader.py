"""PostgreSQL context loader implementation.

Загружает документы из таблицы docling_results PostgreSQL.
Альтернатива MongoContextLoader для миграции на PostgreSQL.

Trace system:
- PRIMARY TRACE ID: reg_num (из docling_results)
- unit_id: локальный идентификатор
"""

import json
import logging
import os
from typing import Optional

try:
    import asyncpg
    from asyncpg.pool import Pool
    ASYNCPG_AVAILABLE = True
except ImportError:
    ASYNCPG_AVAILABLE = False
    # Создаём псевдоним для type hints когда модуль недоступен
    from typing import Any as Pool  # type: ignore

from domain.interfaces.context_loader import IContextLoader, DocumentContext

logger = logging.getLogger(__name__)


def _extract_text_from_tables(tables: list) -> str:
    """
    Extract text content from DoclingDocument tables.

    Args:
        tables: List of table objects from DoclingDocument.

    Returns:
        Formatted text representation of tables.
    """
    if not tables:
        return ""

    table_texts = []
    for table_idx, table in enumerate(tables):
        cells = table.get("data", {}).get("table_cells", [])
        if not cells:
            continue

        # Get table dimensions
        num_rows = table.get("data", {}).get("num_rows", 0)
        num_cols = table.get("data", {}).get("num_cols", 0)

        if num_rows == 0 or num_cols == 0:
            continue

        # Build table as text grid
        rows = []
        for row_idx in range(num_rows):
            row_cells = []
            for col_idx in range(num_cols):
                # Find cell at this position
                cell_text = ""
                for cell in cells:
                    if (cell.get("start_row_offset_idx") == row_idx and
                        cell.get("end_row_offset_idx") == row_idx + 1 and
                        cell.get("start_col_offset_idx") == col_idx):
                        cell_text = cell.get("text", "").strip()
                        break
                row_cells.append(cell_text)
            if any(cell for cell in row_cells):  # Only add non-empty rows
                rows.append(" | ".join(row_cells))

        if rows:
            table_texts.append(f"--- Таблица {table_idx + 1} ---")
            table_texts.extend(rows)
            table_texts.append("")  # Empty line after table

    return "\n".join(table_texts)


class PostgresContextLoader(IContextLoader):
    """
    Context loader from PostgreSQL.

    Reads documents from docling_results table.
    Uses markdown_content as primary source with fallback chain.
    """

    def __init__(
        self,
        dsn: Optional[str] = None,
        pool_size: int = 10,
    ):
        """
        Инициализирует PostgreSQL context loader.

        Args:
            dsn: PostgreSQL DSN строка. Если не указана, используется get_postgres_dsn()
            pool_size: Размер пула соединений
        """
        if not ASYNCPG_AVAILABLE:
            raise ImportError(
                "asyncpg не установлен. Установите: pip install asyncpg"
            )

        self.dsn = dsn or self._get_dsn()
        if not self.dsn:
            raise ValueError(
                "PostgreSQL DSN не указан. Установите LOCAL_PG_PASSWORD "
                "переменную окружения"
            )

        self.pool_size = pool_size
        self._pool: Optional[Pool] = None

    def _get_dsn(self) -> str:
        """Возвращает DSN из переменных окружения."""
        config = {
            "host": os.environ.get("LOCAL_PG_SERVER", "localhost"),
            "port": int(os.environ.get("LOCAL_PG_PORT", "5433")),
            "user": os.environ.get("LOCAL_PG_USER", "delivery_user"),
            "database": os.environ.get("LOCAL_PG_DB", "delivery_processing"),
        }

        from urllib.parse import quote_plus
        password = os.environ.get("LOCAL_PG_PASSWORD", "")
        if not password:
            return ""

        safe_password = quote_plus(password)
        return (
            f"postgresql://{config['user']}:{safe_password}@"
            f"{config['host']}:{config['port']}/{config['database']}"
        )

    async def _get_pool(self) -> Pool:
        """Создает или возвращает пул соединений."""
        if self._pool is None:
            self._pool = await asyncpg.create_pool(
                self.dsn,
                min_size=1,
                max_size=self.pool_size,
                command_timeout=60,
            )
            logger.info("PostgreSQL pool created for Context Loader")
        return self._pool

    async def load(self, unit_id: str) -> Optional[DocumentContext]:
        """
        Load document context from PostgreSQL.

        Args:
            unit_id: Unique identifier (unit_id field in docling_results).

        Returns:
            DocumentContext if found, None otherwise.
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            # Search by unit_id field
            row = await conn.fetchrow(
                "SELECT * FROM docling_results WHERE unit_id = $1",
                unit_id
            )

            if not row:
                logger.warning(f"Document not found for unit_id: {unit_id}")
                return None

            # Fallback chain for content
            content = row.get("markdown_content", "")
            content_type = "markdown"

            if not content:
                content = row.get("html_content", "")
                content_type = "html"

            if not content:
                content = row.get("plain_text", "")
                content_type = "plain_text"

            # Fallback: generate content from docling_document JSONB
            if not content:
                docling_doc = row.get("docling_document", {})
                if isinstance(docling_doc, str):
                    try:
                        docling_doc = json.loads(docling_doc)
                    except:
                        docling_doc = {}
                texts = docling_doc.get("texts", [])
                if texts:
                    content_parts = []
                    for t in texts:
                        text_value = t.get("orig") or t.get("text", "")
                        if text_value:
                            content_parts.append(text_value.strip())

                    # Add tables content (critical for INN extraction!)
                    tables = docling_doc.get("tables", [])
                    tables_text = _extract_text_from_tables(tables)
                    if tables_text:
                        content_parts.append("\n\n=== ТАБЛИЦЫ ИЗ ДОКУМЕНТА ===\n")
                        content_parts.append(tables_text)

                    content = "\n\n".join(content_parts)
                    content_type = "docling_texts+tables"
                    logger.info(f"Generated content from docling_document.texts+tables for {unit_id}: {len(content)} chars")

            if not content:
                logger.warning(f"No content found for unit_id: {unit_id}")
                return None

            # Build metadata
            metadata = {
                "unit_id": unit_id,
                "content_length": len(content),
                "registration_number": row.get("reg_num"),  # PRIMARY TRACE ID
                "record_id": None,  # Можно добавить позже
                "processed_at": str(row.get("processed_at")) if row.get("processed_at") else None,
            }

            # Проверяем trace для получения дополнительной информации
            trace = row.get("trace")
            if trace:
                if isinstance(trace, str):
                    try:
                        trace = json.loads(trace)
                    except:
                        trace = {}
                metadata["trace"] = trace

            return DocumentContext(
                unit_id=unit_id,
                content=content,
                source_file=None,  # Можно добавить если нужно
                content_type=content_type,
                metadata=metadata,
            )

    async def exists(self, unit_id: str) -> bool:
        """
        Check if document exists.

        Args:
            unit_id: Unique identifier.

        Returns:
            True if document exists.
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM docling_results WHERE unit_id = $1",
                unit_id
            )
            return count > 0

    async def list_unit_ids(self, limit: int = 100, skip: int = 0) -> list[str]:
        """
        List available unit_ids.

        Args:
            limit: Maximum number of unit_ids to return.
            skip: Number of documents to skip.

        Returns:
            List of unit_ids.
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT unit_id FROM docling_results ORDER BY processed_at DESC LIMIT $1 OFFSET $2",
                limit, skip
            )
            return [row["unit_id"] for row in rows]

    async def count(self) -> int:
        """Get total document count."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            return await conn.fetchval("SELECT COUNT(*) FROM docling_results")

    async def close(self) -> None:
        """Close PostgreSQL connection."""
        if self._pool:
            await self._pool.close()
            self._pool = None
            logger.info("PostgreSQL pool closed")
