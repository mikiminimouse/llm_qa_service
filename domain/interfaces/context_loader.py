"""Abstract interface for document context loaders."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DocumentContext:
    """Context loaded from a document."""

    unit_id: str
    content: str
    source_file: Optional[str] = None
    content_type: str = "markdown"
    metadata: dict = field(default_factory=dict)


class IContextLoader(ABC):
    """Abstract interface for loading document context."""

    @abstractmethod
    async def load(self, unit_id: str) -> Optional[DocumentContext]:
        """Load document context by unit_id.

        Args:
            unit_id: Unique identifier of the document.

        Returns:
            DocumentContext if found, None otherwise.
        """
        pass

    @abstractmethod
    async def exists(self, unit_id: str) -> bool:
        """Check if document exists.

        Args:
            unit_id: Unique identifier of the document.

        Returns:
            True if document exists.
        """
        pass

    @abstractmethod
    async def close(self) -> None:
        """Close loader connections."""
        pass
