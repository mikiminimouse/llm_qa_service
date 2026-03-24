"""Main extraction result model.

NOTE: terminology updated for delivery processing system:
- "winner" → "supplier" (поставщик)
- "protocol" → "delivery document" (документ о поставке)
"""

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
from .supplier import OtherParticipant, SupplierInfo

# Legacy alias for backward compatibility
WinnerInfo = SupplierInfo


class WinnerExtractionResultV2(BaseModel):
    """
    Complete result of supplier extraction from a delivery document.

    LEGACY NAME: Kept for backward compatibility.
    New code should use DeliveryExtractionResult when created.

    Terminology:
    - "winner" → "supplier" (поставщик)
    - "protocol" → "delivery document" (документ о поставке)
    """

    # Main result
    winner_found: bool = Field(
        ...,
        description="Поставщик найден в документе (legacy поле, использует supplier_found)",
    )
    suppliers: List[SupplierInfo] = Field(
        default_factory=list,
        description="Список поставщиков (может быть >1 для многолотовых)",
    )

    # Legacy property for backward compatibility
    @property
    def winners(self) -> List[SupplierInfo]:
        """Legacy alias for suppliers."""
        return self.suppliers

    @winners.setter
    def winners(self, value: List[SupplierInfo]) -> None:
        """Legacy setter for winners."""
        self.suppliers = value

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
        """Validate consistency between winner_found and suppliers list."""
        if self.winner_found and not self.suppliers:
            # If winner_found is True but no suppliers, set to False
            self.winner_found = False

        if not self.winner_found and self.suppliers:
            # If suppliers exist but winner_found is False, set to True
            self.winner_found = True

        # Check for service file
        if self.flags.is_service_file:
            self.winner_found = False
            self.suppliers = []

        return self

    def get_primary_supplier(self) -> Optional[SupplierInfo]:
        """Get the primary (first) supplier if exists."""
        return self.suppliers[0] if self.suppliers else None

    # Legacy alias
    def get_primary_winner(self) -> Optional[SupplierInfo]:
        """Legacy alias for get_primary_supplier."""
        return self.get_primary_supplier()

    def get_total_participants_count(self) -> int:
        """Get total number of participants including suppliers."""
        return len(self.suppliers) + len(self.other_participants)
