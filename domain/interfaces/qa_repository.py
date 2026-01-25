"""Abstract interface for QA results repository."""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from domain.entities import QARecord


class IQARepository(ABC):
    """Abstract interface for QA results storage."""

    @abstractmethod
    async def save(self, record: "QARecord") -> str:
        """Save QA record.

        Args:
            record: QARecord to save.

        Returns:
            ID of saved record.
        """
        pass

    @abstractmethod
    async def get_by_unit_id(self, unit_id: str) -> Optional["QARecord"]:
        """Get QA record by unit_id.

        Args:
            unit_id: Unique identifier.

        Returns:
            QARecord if found, None otherwise.
        """
        pass

    @abstractmethod
    async def exists(self, unit_id: str) -> bool:
        """Check if record exists.

        Args:
            unit_id: Unique identifier.

        Returns:
            True if record exists.
        """
        pass

    @abstractmethod
    async def get_stats(self) -> dict:
        """Get statistics about processed records.

        Returns:
            Dictionary with statistics.
        """
        pass

    @abstractmethod
    async def close(self) -> None:
        """Close repository connections."""
        pass
