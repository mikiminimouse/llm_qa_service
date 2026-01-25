"""MongoDB QA results repository implementation."""

import json
import logging
import os
from datetime import datetime
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import ASCENDING, IndexModel

from domain.entities.qa_record import QARecord
from domain.interfaces.qa_repository import IQARepository

logger = logging.getLogger(__name__)


class MongoQARepository(IQARepository):
    """
    MongoDB repository for QA results.

    Stores extraction results in qa_results collection.
    Uses upsert on unit_id for idempotent writes.
    """

    def __init__(
        self,
        mongo_uri: str,
        database: str,
        collection: str = "qa_results",
    ):
        """
        Initialize MongoDB QA repository.

        Args:
            mongo_uri: MongoDB connection URI.
            database: Database name.
            collection: Collection name (default: qa_results).
        """
        self.client = AsyncIOMotorClient(mongo_uri)
        self.db: AsyncIOMotorDatabase = self.client[database]
        self.collection = self.db[collection]
        self._indexes_created = False

    async def _ensure_indexes(self) -> None:
        """Create indexes if not already created."""
        if self._indexes_created:
            return

        indexes = [
            IndexModel([("unit_id", ASCENDING)], unique=True),
            IndexModel([("winner_found", ASCENDING)]),
            IndexModel([("is_service_file", ASCENDING)]),
            IndexModel([("processed_at", ASCENDING)]),
            IndexModel([("winner_inn", ASCENDING)]),
        ]

        try:
            await self.collection.create_indexes(indexes)
            self._indexes_created = True
            logger.info("QA repository indexes created")
        except Exception as e:
            logger.warning(f"Failed to create indexes: {e}")

    async def save(self, record: QARecord) -> str:
        """
        Save QA record (upsert by unit_id).

        Args:
            record: QARecord to save.

        Returns:
            unit_id of saved record.
        """
        await self._ensure_indexes()

        data = record.to_mongo_dict()
        data["updated_at"] = datetime.utcnow()

        await self.collection.update_one(
            {"unit_id": record.unit_id},
            {"$set": data},
            upsert=True,
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
        doc = await self.collection.find_one({"unit_id": unit_id})
        if not doc:
            return None

        return QARecord.from_mongo_dict(doc)

    async def exists(self, unit_id: str) -> bool:
        """
        Check if record exists.

        Args:
            unit_id: Unique identifier.

        Returns:
            True if record exists.
        """
        count = await self.collection.count_documents({"unit_id": unit_id}, limit=1)
        return count > 0

    async def get_stats(self) -> dict:
        """
        Get statistics about processed records.

        Returns:
            Dictionary with statistics.
        """
        pipeline = [
            {
                "$group": {
                    "_id": None,
                    "total": {"$sum": 1},
                    "winner_found": {
                        "$sum": {"$cond": ["$winner_found", 1, 0]}
                    },
                    "service_files": {
                        "$sum": {"$cond": ["$is_service_file", 1, 0]}
                    },
                    "with_errors": {
                        "$sum": {"$cond": [{"$ne": ["$error", None]}, 1, 0]}
                    },
                }
            }
        ]

        cursor = self.collection.aggregate(pipeline)
        results = await cursor.to_list(length=1)

        if not results:
            return {
                "total": 0,
                "winner_found": 0,
                "winner_not_found": 0,
                "service_files": 0,
                "with_errors": 0,
            }

        stats = results[0]
        return {
            "total": stats.get("total", 0),
            "winner_found": stats.get("winner_found", 0),
            "winner_not_found": stats.get("total", 0)
            - stats.get("winner_found", 0)
            - stats.get("service_files", 0),
            "service_files": stats.get("service_files", 0),
            "with_errors": stats.get("with_errors", 0),
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
            winner_found: Filter by winner_found flag.
            limit: Maximum records to return.
            skip: Number of records to skip.

        Returns:
            List of QARecords.
        """
        query = {}
        if winner_found is not None:
            query["winner_found"] = winner_found

        cursor = self.collection.find(query).skip(skip).limit(limit)
        docs = await cursor.to_list(length=limit)

        return [QARecord.from_mongo_dict(doc) for doc in docs]

    async def delete(self, unit_id: str) -> bool:
        """
        Delete QA record.

        Args:
            unit_id: Unique identifier.

        Returns:
            True if deleted, False if not found.
        """
        result = await self.collection.delete_one({"unit_id": unit_id})
        return result.deleted_count > 0

    async def close(self) -> None:
        """Close MongoDB connection."""
        self.client.close()

    async def save_to_unit_directory(
        self,
        unit_id: str,
        record: QARecord,
        base_paths: list[str],
    ) -> Optional[str]:
        """
        Save qa_results.json to the UNIT directory on disk.

        Args:
            unit_id: Unique identifier (e.g., UNIT_xxx).
            record: QARecord to save.
            base_paths: List of base directories to search for UNIT folder.

        Returns:
            Path to saved file or None if directory not found.
        """
        unit_dir = self._find_unit_directory(unit_id, base_paths)
        if not unit_dir:
            logger.debug(f"UNIT directory not found for {unit_id}")
            return None

        output_path = os.path.join(unit_dir, "qa_results.json")
        try:
            data = record.model_dump(mode="json")
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2, default=str)
            logger.info(f"Saved qa_results.json to {output_path}")
            return output_path
        except Exception as e:
            logger.error(f"Failed to save qa_results.json to {output_path}: {e}")
            return None

    def _find_unit_directory(
        self,
        unit_id: str,
        base_paths: list[str],
    ) -> Optional[str]:
        """
        Find UNIT directory on disk.

        Searches recursively in base_paths for a directory matching unit_id.

        Args:
            unit_id: Unique identifier (e.g., UNIT_xxx).
            base_paths: List of base directories to search.

        Returns:
            Path to UNIT directory or None if not found.
        """
        for base in base_paths:
            if not os.path.exists(base):
                continue

            # Walk through directory tree looking for unit_id folder
            for root, dirs, _ in os.walk(base):
                if unit_id in dirs:
                    found_path = os.path.join(root, unit_id)
                    logger.debug(f"Found UNIT directory: {found_path}")
                    return found_path

                # Optimization: skip deep recursion in irrelevant directories
                # Keep only directories that might contain UNITs
                dirs[:] = [
                    d for d in dirs
                    if d.startswith("UNIT_")
                    or d in ("Processing", "Merge", "Extracted", "Normalize", "OutputDocling")
                    or d.startswith("Processing_")
                    or d.startswith("Processed_")
                    or d.isdigit()  # date folders like "20250115"
                    or "-" in d  # date folders like "2025-01-15"
                ]

        return None
