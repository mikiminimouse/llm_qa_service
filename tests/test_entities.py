"""Tests for domain entities."""

import pytest
from pydantic import ValidationError

from domain.entities import (
    WinnerExtractionResultV2,
    QARecord,
    WinnerInfo,
    OtherParticipant,
    ProcurementInfo,
    ExtractionFlags,
    DocumentInfo,
)
from domain.entities.enums import (
    ParticipantStatus,
    ProcurementStatus,
    NotHeldReason,
    DocumentType,
)


class TestWinnerInfo:
    """Tests for WinnerInfo model."""

    def test_valid_winner_info(self):
        """Test creating valid WinnerInfo."""
        winner = WinnerInfo(
            name="ООО Тестовая компания",
            inn="1234567890",
            kpp="123456789",
        )
        assert winner.name == "ООО Тестовая компания"
        assert winner.inn == "1234567890"
        assert winner.kpp == "123456789"

    def test_inn_10_digits(self):
        """Test valid 10-digit INN."""
        winner = WinnerInfo(name="Test", inn="1234567890")
        assert winner.inn == "1234567890"

    def test_inn_12_digits(self):
        """Test valid 12-digit INN."""
        winner = WinnerInfo(name="Test", inn="123456789012")
        assert winner.inn == "123456789012"

    def test_invalid_inn_format(self):
        """Test invalid INN is set to None."""
        winner = WinnerInfo(name="Test", inn="12345")
        assert winner.inn is None

    def test_inn_with_spaces(self):
        """Test INN with spaces is cleaned."""
        winner = WinnerInfo(name="Test", inn="12 34 56 78 90")
        assert winner.inn == "1234567890"

    def test_kpp_validation(self):
        """Test KPP validation (9 digits)."""
        winner = WinnerInfo(name="Test", kpp="123456789")
        assert winner.kpp == "123456789"

        winner = WinnerInfo(name="Test", kpp="12345")
        assert winner.kpp is None

    def test_ogrn_13_digits(self):
        """Test valid 13-digit OGRN."""
        winner = WinnerInfo(name="Test", ogrn="1234567890123")
        assert winner.ogrn == "1234567890123"

    def test_ogrn_15_digits(self):
        """Test valid 15-digit OGRN (for IP)."""
        winner = WinnerInfo(name="Test", ogrn="123456789012345")
        assert winner.ogrn == "123456789012345"


class TestWinnerExtractionResultV2:
    """Tests for WinnerExtractionResultV2 model."""

    def test_consistency_validation_winner_found_no_winners(self):
        """Test that winner_found becomes False when no winners."""
        result = WinnerExtractionResultV2(
            winner_found=True,
            winners=[],
        )
        assert result.winner_found is False

    def test_consistency_validation_winners_exist(self):
        """Test that winner_found becomes True when winners exist."""
        result = WinnerExtractionResultV2(
            winner_found=False,
            winners=[WinnerInfo(name="Test")],
        )
        assert result.winner_found is True

    def test_service_file_clears_winners(self):
        """Test that service file flag clears winners."""
        result = WinnerExtractionResultV2(
            winner_found=True,
            winners=[WinnerInfo(name="Test")],
            flags=ExtractionFlags(is_service_file=True),
        )
        assert result.winner_found is False
        assert len(result.winners) == 0

    def test_get_primary_winner(self):
        """Test getting primary winner."""
        result = WinnerExtractionResultV2(
            winner_found=True,
            winners=[
                WinnerInfo(name="Winner 1"),
                WinnerInfo(name="Winner 2"),
            ],
        )
        winner = result.get_primary_winner()
        assert winner.name == "Winner 1"

    def test_get_primary_winner_none(self):
        """Test getting primary winner when none exists."""
        result = WinnerExtractionResultV2(
            winner_found=False,
            winners=[],
        )
        assert result.get_primary_winner() is None


class TestQARecord:
    """Tests for QARecord model."""

    def test_qa_record_creation(self, sample_extraction_result):
        """Test creating QARecord."""
        record = QARecord(
            unit_id="UNIT_test123",
            source_file="test.pdf",
            result=sample_extraction_result,
            model_used="glm-4-flash",
        )
        assert record.unit_id == "UNIT_test123"
        assert record.winner_found is True
        assert record.winner_name == "ООО Тест"

    def test_qa_record_to_mongo_dict(self, sample_qa_record):
        """Test converting QARecord to MongoDB dict."""
        data = sample_qa_record.to_mongo_dict()
        assert data["_id"] == sample_qa_record.unit_id
        assert "result" in data
        assert data["winner_found"] is True

    def test_qa_record_from_mongo_dict(self, sample_qa_record):
        """Test creating QARecord from MongoDB dict."""
        data = sample_qa_record.to_mongo_dict()
        restored = QARecord.from_mongo_dict(data)
        assert restored.unit_id == sample_qa_record.unit_id
        assert restored.winner_found == sample_qa_record.winner_found


class TestEnums:
    """Tests for domain enums."""

    def test_participant_status_values(self):
        """Test ParticipantStatus enum values."""
        assert ParticipantStatus.WINNER.value == "winner"
        assert ParticipantStatus.SINGLE_PARTICIPANT.value == "single_participant"

    def test_procurement_status_values(self):
        """Test ProcurementStatus enum values."""
        assert ProcurementStatus.COMPLETED.value == "completed"
        assert ProcurementStatus.NOT_HELD.value == "not_held"

    def test_not_held_reason_values(self):
        """Test NotHeldReason enum values."""
        assert NotHeldReason.SINGLE_PARTICIPANT.value == "single_participant"
        assert NotHeldReason.NO_APPLICATIONS.value == "no_applications"
