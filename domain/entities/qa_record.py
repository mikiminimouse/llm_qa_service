"""QA Record model for MongoDB storage."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from .extraction_result import WinnerExtractionResultV2


class QARecord(BaseModel):
    """Record for storing QA results in MongoDB."""

    # Primary identifier (unit_id from docling_results)
    unit_id: str = Field(..., description="Unique identifier from docling_results")

    # Optional protocol_id for backwards compatibility
    protocol_id: Optional[str] = Field(
        None,
        description="Protocol ID if available",
    )

    # Source information
    source_file: Optional[str] = Field(
        None,
        description="Original source filename",
    )

    # Extraction result
    result: WinnerExtractionResultV2 = Field(
        ...,
        description="Extraction result",
    )

    # Quick access fields (denormalized for queries)
    winner_found: bool = Field(
        default=False,
        description="Winner found flag (denormalized)",
    )
    winner_name: Optional[str] = Field(
        None,
        description="Primary winner name (denormalized)",
    )
    winner_inn: Optional[str] = Field(
        None,
        description="Primary winner INN (denormalized)",
    )
    is_service_file: bool = Field(
        default=False,
        description="Service file flag (denormalized)",
    )

    # Processing metadata
    processed_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Processing timestamp",
    )
    model_used: Optional[str] = Field(
        None,
        description="LLM model used for extraction",
    )
    processing_time_ms: Optional[int] = Field(
        None,
        description="Processing time in milliseconds",
    )
    error: Optional[str] = Field(
        None,
        description="Error message if processing failed",
    )

    def model_post_init(self, __context) -> None:
        """Denormalize fields after initialization."""
        # Sync denormalized fields
        self.winner_found = self.result.winner_found
        self.is_service_file = self.result.flags.is_service_file

        primary_winner = self.result.get_primary_winner()
        if primary_winner:
            self.winner_name = primary_winner.name
            self.winner_inn = primary_winner.inn

    def to_mongo_dict(self) -> dict:
        """Convert to dictionary for MongoDB storage."""
        data = self.model_dump(mode="json")
        # Use unit_id as the primary key
        data["_id"] = self.unit_id
        return data

    @classmethod
    def from_mongo_dict(cls, data: dict) -> "QARecord":
        """Create instance from MongoDB document."""
        # Remove _id if present (it's the same as unit_id)
        data.pop("_id", None)
        return cls.model_validate(data)
