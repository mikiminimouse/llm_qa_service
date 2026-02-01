"""Main extraction result model."""

from typing import List, Optional

from pydantic import BaseModel, Field, model_validator

from .extraction_components import (
    CustomerInfo,
    DocumentInfo,
    ExtractionFlags,
    HistoryEvent,
    ProcurementInfo,
    TraceInfo,
)
from .winner import OtherParticipant, WinnerInfo


class WinnerExtractionResultV2(BaseModel):
    """Complete result of winner extraction from a protocol."""

    # Main result
    winner_found: bool = Field(
        ...,
        description="Победитель найден в документе",
    )
    winners: List[WinnerInfo] = Field(
        default_factory=list,
        description="Список победителей (может быть >1 для многолотовых)",
    )

    # Additional participants
    other_participants: List[OtherParticipant] = Field(
        default_factory=list,
        description="Другие участники закупки",
    )

    # Procurement information
    procurement: ProcurementInfo = Field(
        default_factory=ProcurementInfo,
        description="Информация о закупке",
    )

    # Customer information (for validation - to ensure we don't confuse with winner)
    customer: CustomerInfo = Field(
        default_factory=CustomerInfo,
        description="Информация о заказчике (для проверки)",
    )

    # Extraction flags
    flags: ExtractionFlags = Field(
        default_factory=ExtractionFlags,
        description="Флаги особых случаев",
    )

    # Document info
    document: DocumentInfo = Field(
        default_factory=DocumentInfo,
        description="Информация о документе",
    )

    # Traceability fields
    trace: Optional[TraceInfo] = Field(
        None,
        description="Информация о трейсинге обработки",
    )
    history: List[HistoryEvent] = Field(
        default_factory=list,
        description="История обработки документа",
    )

    # LLM metadata
    reasoning: Optional[str] = Field(
        None,
        description="Пояснение LLM о результате извлечения",
    )
    raw_llm_response: Optional[str] = Field(
        None,
        description="Сырой ответ LLM (для отладки)",
    )

    @model_validator(mode="after")
    def validate_consistency(self) -> "WinnerExtractionResultV2":
        """Validate consistency between winner_found and winners list."""
        if self.winner_found and not self.winners:
            # If winner_found is True but no winners, set to False
            self.winner_found = False

        if not self.winner_found and self.winners:
            # If winners exist but winner_found is False, set to True
            self.winner_found = True

        # Check for service file
        if self.flags.is_service_file:
            self.winner_found = False
            self.winners = []

        return self

    def get_primary_winner(self) -> Optional[WinnerInfo]:
        """Get the primary (first) winner if exists."""
        return self.winners[0] if self.winners else None

    def get_total_participants_count(self) -> int:
        """Get total number of participants including winners."""
        return len(self.winners) + len(self.other_participants)
