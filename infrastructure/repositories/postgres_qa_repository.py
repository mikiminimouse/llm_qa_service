"""PostgreSQL QA results repository implementation.

Асинхронный репозиторий для хранения результатов QA extraction
в PostgreSQL таблице qa_results базы данных delivery_processing.

Trace system:
- PRIMARY TRACE ID: reg_num (аналог registrationNumber)
- unit_id: локальный идентификатор
"""

import json
import logging
import os
from datetime import datetime
from typing import Optional

try:
    import asyncpg
    from asyncpg.pool import Pool
    ASYNCPG_AVAILABLE = True
except ImportError:
    ASYNCPG_AVAILABLE = False
    Pool = None

from domain.entities.qa_record import QARecord
from domain.interfaces.qa_repository import IQARepository

logger = logging.getLogger(__name__)


def get_postgres_config() -> dict:
    """
    Получает конфигурацию Remote PostgreSQL из переменных окружения.

    Переменные окружения:
    - REMOTE_PG_SERVER: сервер (default: sber1.multitender.ru)
    - REMOTE_PG_PORT: порт (default: 55432)
    - REMOTE_PG_USER: пользователь (default: vitaliy)
    - REMOTE_PG_PASSWORD: пароль (обязательный)
    - REMOTE_PG_DB: база данных (default: postgres)

    Returns:
        Словарь с параметрами подключения для asyncpg
    """
    return {
        "host": os.environ.get("REMOTE_PG_SERVER", "sber1.multitender.ru"),
        "port": int(os.environ.get("REMOTE_PG_PORT", "55432")),
        "user": os.environ.get("REMOTE_PG_USER", "vitaliy"),
        "password": os.environ.get("REMOTE_PG_PASSWORD", ""),
        "database": os.environ.get("REMOTE_PG_DB", "postgres"),
        "command_timeout": 60,
    }


def get_postgres_dsn() -> str:
    """
    Возвращает DSN для подключения к PostgreSQL.

    Returns:
        Строка DSN или пустая строка если пароль не задан
    """
    config = get_postgres_config()
    if not config["password"]:
        return ""

    from urllib.parse import quote_plus
    safe_password = quote_plus(config["password"])
    return (
        f"postgresql://{config['user']}:{safe_password}@"
        f"{config['host']}:{config['port']}/{config['database']}"
    )


class PostgresQARepository(IQARepository):
    """
    PostgreSQL repository for QA results.

    Stores extraction results in qa_results table.
    Uses upsert on unit_id for idempotent writes.
    API совместим с MongoQARepository для легкой замены.
    """

    def __init__(
        self,
        dsn: Optional[str] = None,
        pool_size: int = 10,
    ):
        """
        Инициализирует PostgreSQL QA репозиторий.

        Args:
            dsn: PostgreSQL DSN строка. Если не указана, используется get_postgres_dsn()
            pool_size: Размер пула соединений
        """
        if not ASYNCPG_AVAILABLE:
            raise ImportError(
                "asyncpg не установлен. Установите: pip install asyncpg"
            )

        self.dsn = dsn or get_postgres_dsn()
        if not self.dsn:
            raise ValueError(
                "PostgreSQL DSN не указан. Установите REMOTE_PG_PASSWORD "
                "переменную окружения или передайте dsn параметр."
            )

        self.pool_size = pool_size
        self._pool: Optional[Pool] = None
        self._indexes_created = False

    async def _get_pool(self) -> Pool:
        """Создает или возвращает пул соединений."""
        if self._pool is None:
            async def _init_connection(conn):
                await conn.execute("SET search_path TO contracts, public")

            self._pool = await asyncpg.create_pool(
                self.dsn,
                min_size=1,
                max_size=self.pool_size,
                command_timeout=60,
                init=_init_connection,
            )
            logger.info("PostgreSQL pool created for QA Enricher (schema: contracts)")
        return self._pool

    async def _ensure_indexes(self) -> None:
        """Создает индексы если они еще не созданы."""
        if self._indexes_created:
            return

        pool = await self._get_pool()
        async with pool.acquire() as conn:
            # Индексы обычно создаются через schema/init.sql
            # Проверяем только существование таблицы
            table_exists = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_schema = 'contracts' AND table_name = 'qa_results'
                )
            """)

            if not table_exists:
                logger.warning("Таблица qa_results не существует. Выполните schema/init.sql")

        self._indexes_created = True

    async def save(self, record: QARecord) -> str:
        """
        Save QA record (upsert by unit_id).

        Args:
            record: QARecord to save.

        Returns:
            unit_id of saved record.
        """
        await self._ensure_indexes()

        pool = await self._get_pool()
        async with pool.acquire() as conn:
            data = record.model_dump(mode="json", exclude_none=True)
            data["updated_at"] = datetime.utcnow()

            # Формируем trace и history как JSONB
            trace_json = json.dumps(data.get("trace", {})) if data.get("trace") else "{}"
            history_json = json.dumps(data.get("history", [])) if data.get("history") else "[]"

            # Формируем extracted_data из результата
            extracted_data = {}
            if hasattr(record.result, 'procurement'):
                extracted_data["procurement"] = record.result.procurement.model_dump(mode="json", exclude_none=True)
            if hasattr(record.result, 'winners'):
                extracted_data["winners"] = [
                    w.model_dump(mode="json", exclude_none=True)
                    for w in record.result.winners
                ]

            # UPSERT через ON CONFLICT
            query = """
                INSERT INTO qa_results (
                    delivery_doc_id, docling_result_id, unit_id, reg_num,
                    delivery_found, supplier_inn, supplier_name, delivery_amount,
                    extracted_data, trace, processed_at
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10::jsonb, NOW()
                )
                ON CONFLICT (unit_id) DO UPDATE SET
                    reg_num = EXCLUDED.reg_num,
                    delivery_found = EXCLUDED.delivery_found,
                    supplier_inn = EXCLUDED.supplier_inn,
                    supplier_name = EXCLUDED.supplier_name,
                    delivery_amount = EXCLUDED.delivery_amount,
                    extracted_data = COALESCE(qa_results.extracted_data, '{}'::jsonb) || EXCLUDED.extracted_data,
                    trace = COALESCE(qa_results.trace, '{}'::jsonb) || EXCLUDED.trace,
                    processed_at = NOW()
                RETURNING id
            """

            # Находим delivery_doc_id и docling_result_id по reg_num
            delivery_doc_id = await conn.fetchval(
                "SELECT id FROM delivery_documents WHERE reg_num = $1 LIMIT 1",
                data.get("registration_number") or data.get("reg_num")
            )

            docling_result_id = await conn.fetchval(
                "SELECT id FROM docling_results WHERE unit_id = $1 LIMIT 1",
                record.unit_id
            )

            await conn.execute(
                query,
                delivery_doc_id,
                docling_result_id,
                record.unit_id,
                data.get("registration_number") or data.get("reg_num"),
                record.winner_found,  # delivery_found
                record.winner_inn,    # supplier_inn
                record.winner_name,   # supplier_name
                None,  # delivery_amount (можно добавить из extracted_data)
                json.dumps(extracted_data, ensure_ascii=False),
                trace_json,
            )

        logger.debug(f"Saved QA record for unit_id: {record.unit_id}")
        return record.unit_id

    async def get_by_unit_id(self, unit_id: str) -> Optional[QARecord]:
        """
        Get QA record by unit_id.

        Args:
            unit_id: Unique identifier.

        Returns:
            QARecord if found, None otherwise.
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM qa_results WHERE unit_id = $1",
                unit_id
            )

            if row:
                return QARecord.model_validate(dict(row))
            return None

    async def exists(self, unit_id: str) -> bool:
        """
        Check if record exists.

        Args:
            unit_id: Unique identifier.

        Returns:
            True if record exists.
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM qa_results WHERE unit_id = $1",
                unit_id
            )
            return count > 0

    async def get_stats(self) -> dict:
        """
        Get statistics about processed records.

        Returns:
            Dictionary with statistics.
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE delivery_found = true) as winner_found,
                    COUNT(*) FILTER (WHERE delivery_found = false) as winner_not_found
                FROM qa_results
            """)

            if not row:
                return {
                    "total": 0,
                    "winner_found": 0,
                    "winner_not_found": 0,
                    "service_files": 0,
                    "with_errors": 0,
                }

            return {
                "total": row["total"],
                "winner_found": row["winner_found"],
                "winner_not_found": row["winner_not_found"],
                "service_files": 0,  # Можно добавить если нужно
                "with_errors": 0,     # Можно добавить если нужно
            }

    async def list_records(
        self,
        winner_found: Optional[bool] = None,
        limit: int = 100,
        skip: int = 0,
    ) -> list[QARecord]:
        """
        List QA records with optional filtering.

        Args:
            winner_found: Filter by delivery_found flag.
            limit: Maximum records to return.
            skip: Number of records to skip.

        Returns:
            List of QARecords.
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            query = "SELECT * FROM qa_results"
            params = []
            conditions = []

            if winner_found is not None:
                conditions.append(f"delivery_found = {winner_found}")

            if conditions:
                query += " WHERE " + " AND ".join(conditions)

            query += " ORDER BY processed_at DESC LIMIT $1 OFFSET $2"

            rows = await conn.fetch(query, limit, skip)

            return [QARecord.model_validate(dict(row)) for row in rows]

    async def delete(self, unit_id: str) -> bool:
        """
        Delete QA record.

        Args:
            unit_id: Unique identifier.

        Returns:
            True if deleted, False if not found.
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM qa_results WHERE unit_id = $1",
                unit_id
            )
            return "DELETE 1" in result

    async def close(self) -> None:
        """Close PostgreSQL connection."""
        if self._pool:
            await self._pool.close()
            self._pool = None
            logger.info("PostgreSQL pool closed")


# =============================================================================
# Factory Functions
# =============================================================================

async def create_postgres_qa_repository(
    dsn: Optional[str] = None,
    pool_size: int = 10,
) -> PostgresQARepository:
    """
    Создаёт и инициализирует PostgreSQL QA репозиторий.

    Args:
        dsn: PostgreSQL DSN строка
        pool_size: Размер пула соединений

    Returns:
        Инициализированный PostgresQARepository
    """
    repo = PostgresQARepository(dsn=dsn, pool_size=pool_size)
    await repo._ensure_indexes()
    return repo


def is_postgresql_enabled() -> bool:
    """
    Проверяет, включен ли PostgreSQL экспорт.

    Returns:
        True если установлен пароль Remote PostgreSQL или STORAGE_BACKEND=postgresql
    """
    if os.environ.get("STORAGE_BACKEND", "").lower() == "postgresql":
        return True
    return bool(os.environ.get("REMOTE_PG_PASSWORD", ""))
