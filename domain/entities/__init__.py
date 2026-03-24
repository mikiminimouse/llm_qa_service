"""Domain entities."""

from .enums import (
    DocumentType,
    NotHeldReason,
    ParticipantStatus,
    ProcurementStatus,
)
from .extraction_components import DocumentInfo, ExtractionFlags, ProcurementInfo
from .extraction_result import WinnerExtractionResultV2
from .qa_record import QARecord

# NEW: Используем supplier.py для системы обработки delivery документов
from .supplier import OtherParticipant, SupplierInfo

# Legacy: Сохраняем импорт из winner.py для обратной совместимости
# В новом коде используйте SupplierInfo вместо WinnerInfo
try:
    from .winner import WinnerInfo as LegacyWinnerInfo
    WinnerInfo = SupplierInfo  # Перенаправление на новый класс
except ImportError:
    WinnerInfo = SupplierInfo

__all__ = [
    "ParticipantStatus",
    "ProcurementStatus",
    "NotHeldReason",
    "DocumentType",
    # Новые имена (Delivery Processing)
    "SupplierInfo",
    # Legacy имена (для обратной совместимости)
    "WinnerInfo",
    "OtherParticipant",
    "ProcurementInfo",
    "ExtractionFlags",
    "DocumentInfo",
    "WinnerExtractionResultV2",
    "QARecord",
]
