"""MongoDB context loader implementation."""

import logging
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from domain.interfaces.context_loader import DocumentContext, IContextLoader

logger = logging.getLogger(__name__)

# Вторичная коллекция для загрузки метаданных закупки
PROTOCOLS_COLLECTION = "protocols"


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


class MongoContextLoader(IContextLoader):
    """
    Context loader from MongoDB.

    Reads documents from docling_results collection.
    Uses markdown_content as primary source with fallback chain.
    """

    def __init__(
        self,
        mongo_uri: str,
        database: str,
        collection: str = "docling_results",
    ):
        """
        Initialize MongoDB context loader.

        Args:
            mongo_uri: MongoDB connection URI.
            database: Database name.
            collection: Collection name (default: docling_results).
        """
        self.client = AsyncIOMotorClient(mongo_uri)
        self.db: AsyncIOMotorDatabase = self.client[database]
        self.collection = self.db[collection]
        # Вторичная коллекция для метаданных закупки
        self.protocols_collection = self.db[PROTOCOLS_COLLECTION]

    async def _load_procurement_metadata(self, unit_id: str) -> dict:
        """
        Загрузить метаданные закупки из коллекции protocols.

        Args:
            unit_id: Уникальный идентификатор документа.

        Returns:
            Словарь с метаданными закупки, включая trace и history.
        """
        metadata = {}
        try:
            protocol = await self.protocols_collection.find_one({"unit_id": unit_id})
            if protocol:
                # Извлекаем номер закупки из purchaseInfo
                purchase_info = protocol.get("purchaseInfo", {})
                if purchase_info:
                    metadata["purchase_notice_number"] = purchase_info.get("purchaseNoticeNumber")
                    metadata["purchase_name"] = purchase_info.get("name")
                    metadata["purchase_method_code"] = purchase_info.get("purchaseMethodCode")
                    metadata["purchase_method_name"] = purchase_info.get("purchaseCodeName")

                # Traceability: извлекаем registrationNumber как PRIMARY TRACE ID
                metadata["registration_number"] = protocol.get("registrationNumber")
                metadata["protocol_guid"] = protocol.get("guid")

                # Trace: копируем существующий trace из protocols для продолжения цепочки
                if "trace" in protocol:
                    metadata["existing_trace"] = protocol["trace"]

                # History: копируем существующую историю
                if "history" in protocol:
                    metadata["existing_history"] = protocol["history"]

                logger.debug(
                    f"Loaded procurement metadata for {unit_id}: "
                    f"registration_number={metadata.get('registration_number')}, "
                    f"purchase_notice_number={metadata.get('purchase_notice_number')}"
                )
        except Exception as e:
            logger.warning(f"Failed to load procurement metadata for {unit_id}: {e}")

        return metadata

    async def load(self, unit_id: str) -> Optional[DocumentContext]:
        """
        Load document context from MongoDB.

        Args:
            unit_id: Unique identifier (unit_id field in docling_results).

        Returns:
            DocumentContext if found, None otherwise.
        """
        # Search by unit_id field
        doc = await self.collection.find_one({"unit_id": unit_id})

        if not doc:
            logger.warning(f"Document not found for unit_id: {unit_id}")
            return None

        # Fallback chain for content
        content = doc.get("markdown_content", "")
        content_type = "markdown"

        if not content:
            content = doc.get("html_content", "")
            content_type = "html"

        if not content:
            content = doc.get("plain_text", "")
            content_type = "plain_text"

        # Fallback: generate content from docling_document.texts
        if not content:
            docling_doc = doc.get("docling_document", {})
            texts = docling_doc.get("texts", [])
            if texts:
                # Extract text from texts array (prefer 'orig' over 'text')
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

        # Fallback: check nested content field (for newly loaded datasets)
        if not content:
            nested_content = doc.get("content", {})
            if isinstance(nested_content, dict):
                # Direct texts array in content (DoclingDocument format)
                texts = nested_content.get("texts", [])
                if texts:
                    content_parts = []
                    for t in texts:
                        text_value = t.get("orig") or t.get("text", "")
                        if text_value:
                            content_parts.append(text_value.strip())

                    # Add tables content (critical for INN extraction!)
                    tables = nested_content.get("tables", [])
                    tables_text = _extract_text_from_tables(tables)
                    if tables_text:
                        content_parts.append("\n\n=== ТАБЛИЦЫ ИЗ ДОКУМЕНТА ===\n")
                        content_parts.append(tables_text)

                    content = "\n\n".join(content_parts)
                    content_type = "content.texts+tables"
                    logger.info(f"Generated content from content.texts+tables for {unit_id}: {len(content)} chars")

        if not content:
            logger.warning(f"No content found for unit_id: {unit_id}")
            return None

        # Extract source_file from nested contract structure
        source_file = None
        contract = doc.get("contract", {})
        if contract:
            source = contract.get("source", {})
            if source:
                source_file = source.get("original_filename")

        # Fallback to direct source_file field if contract structure not found
        if not source_file:
            source_file = doc.get("source_file")

        # Build metadata
        metadata = {
            "unit_id": unit_id,
            "content_length": len(content),
        }

        # ★ ЕДИНАЯ СИСТЕМА ТРЕЙСИНГА: Извлекаем PRIMARY TRACE ID из docling_results
        # Doclingproc сохраняет эти поля при экспорте в MongoDB (приоритет над protocols)
        trace_fields_from_docling = {
            "registration_number": doc.get("registrationNumber"),  # PRIMARY TRACE ID
            "purchase_notice_number": doc.get("purchaseNoticeNumber"),
            "record_id": doc.get("record_id"),  # ObjectId из protocols
            "protocol_id": doc.get("protocol_id"),  # Для обратной совместимости
            "protocol_date": doc.get("protocol_date"),
        }
        for key, value in trace_fields_from_docling.items():
            if value:
                metadata[key] = value

        # Add optional fields to metadata
        if doc.get("document_type"):
            metadata["document_type"] = doc["document_type"]
        if doc.get("processed_at"):
            metadata["processed_at"] = str(doc["processed_at"])

        # Загружаем метаданные закупки из protocols (номер закупки, название и т.д.)
        # ТОЛЬКО если нет данных из docling_results (fallback)
        if not metadata.get("registration_number") or not metadata.get("purchase_notice_number"):
            procurement_metadata = await self._load_procurement_metadata(unit_id)
            # Не перезаписываем существующие данные из docling_results
            for key, value in procurement_metadata.items():
                if key not in metadata or not metadata[key]:
                    metadata[key] = value
        else:
            # Если данные есть из docling_results, загружаем только trace/history
            procurement_metadata = await self._load_procurement_metadata(unit_id)
            for key in ["trace", "history", "purchase_name", "purchase_method_code", "purchase_method_name"]:
                if key in procurement_metadata and procurement_metadata[key]:
                    metadata[key] = procurement_metadata[key]

        # Traceability: преобразуем existing_trace/existing_history в trace/history
        if "existing_trace" in metadata:
            metadata["trace"] = metadata.pop("existing_trace")
        if "existing_history" in metadata:
            metadata["history"] = metadata.pop("existing_history")

        return DocumentContext(
            unit_id=unit_id,
            content=content,
            source_file=source_file,
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
        count = await self.collection.count_documents({"unit_id": unit_id}, limit=1)
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
        cursor = self.collection.find({}, {"unit_id": 1}).skip(skip).limit(limit)
        docs = await cursor.to_list(length=limit)
        return [doc["unit_id"] for doc in docs if "unit_id" in doc]

    async def count(self) -> int:
        """Get total document count."""
        return await self.collection.count_documents({})

    async def close(self) -> None:
        """Close MongoDB connection."""
        self.client.close()
