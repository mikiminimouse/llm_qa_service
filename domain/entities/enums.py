"""Domain enums for winner extraction."""

from enum import Enum


class ParticipantStatus(str, Enum):
    """Status of a participant in the procurement."""

    WINNER = "winner"
    SINGLE_PARTICIPANT = "single_participant"
    ADMITTED = "admitted"
    REJECTED = "rejected"
    NOT_FOUND = "not_found"


class ProcurementStatus(str, Enum):
    """Status of the procurement procedure."""

    COMPLETED = "completed"
    NOT_HELD = "not_held"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class NotHeldReason(str, Enum):
    """Reason why procurement was not held."""

    SINGLE_PARTICIPANT = "single_participant"
    NO_APPLICATIONS = "no_applications"
    ALL_REJECTED = "all_rejected"
    OTHER = "other"


class DocumentType(str, Enum):
    """Type of procurement document."""

    FINAL_PROTOCOL = "итоговый_протокол"
    CONSIDERATION_PROTOCOL = "протокол_рассмотрения"
    RESULT_PROTOCOL = "протокол_подведения_итогов"
    AUCTION_PROTOCOL = "протокол_аукциона"
    PROCUREMENT_NOTICE = "извещение_о_закупке"
    APPLICATION = "заявка_участника"
    CONTRACT = "контракт"
    OTHER = "other"
    UNKNOWN = "unknown"
