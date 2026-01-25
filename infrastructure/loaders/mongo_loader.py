"""MongoDB context loader implementation."""

import logging
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from domain.interfaces.context_loader import DocumentContext, IContextLoader

logger = logging.getLogger(__name__)


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
                content = "\n\n".join(content_parts)
                content_type = "docling_texts"
                logger.info(f"Generated content from docling_document.texts for {unit_id}: {len(content)} chars")

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

        # Add optional fields to metadata
        if doc.get("protocol_id"):
            metadata["protocol_id"] = doc["protocol_id"]
        if doc.get("document_type"):
            metadata["document_type"] = doc["document_type"]
        if doc.get("processed_at"):
            metadata["processed_at"] = str(doc["processed_at"])

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
