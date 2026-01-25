"""Pytest fixtures for llm_qa_service tests."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from domain.entities import WinnerExtractionResultV2, QARecord
from domain.entities.enums import ParticipantStatus, ProcurementStatus
from domain.entities.extraction_components import DocumentInfo, ExtractionFlags, ProcurementInfo
from domain.entities.winner import WinnerInfo
from domain.interfaces.context_loader import DocumentContext


@pytest.fixture
def sample_winner_info():
    """Sample WinnerInfo for testing."""
    return WinnerInfo(
        name="ООО Тест",
        inn="1234567890",
        kpp="123456789",
        ogrn="1234567890123",
        address="г. Москва, ул. Тестовая, д. 1",
        contract_price=100000.0,
        status=ParticipantStatus.WINNER,
    )


@pytest.fixture
def sample_extraction_result(sample_winner_info):
    """Sample WinnerExtractionResultV2 for testing."""
    return WinnerExtractionResultV2(
        winner_found=True,
        winners=[sample_winner_info],
        other_participants=[],
        procurement=ProcurementInfo(
            purchase_number="0123456789012345678",
            purchase_name="Тестовая закупка",
            status=ProcurementStatus.COMPLETED,
        ),
        flags=ExtractionFlags(),
        document=DocumentInfo(),
        reasoning="Тестовое обоснование",
    )


@pytest.fixture
def sample_qa_record(sample_extraction_result):
    """Sample QARecord for testing."""
    return QARecord(
        unit_id="UNIT_test123",
        source_file="test.pdf",
        result=sample_extraction_result,
        model_used="glm-4-flash",
    )


@pytest.fixture
def sample_document_context():
    """Sample DocumentContext for testing."""
    return DocumentContext(
        unit_id="UNIT_test123",
        content="# Протокол подведения итогов\n\n## Победитель\n\nООО Тест, ИНН 1234567890",
        source_file="test.pdf",
        content_type="markdown",
        metadata={"test": True},
    )


@pytest.fixture
def mock_llm_client():
    """Mock LLM client for testing."""
    from domain.interfaces.llm_client import LLMResponse

    client = AsyncMock()
    client.generate.return_value = LLMResponse(
        content='{"winner_found": true, "winners": [{"name": "ООО Тест", "inn": "1234567890"}], "reasoning": "Test"}',
        model="glm-4-flash",
        usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        finish_reason="stop",
    )
    client.model_name = "glm-4-flash"
    return client


@pytest.fixture
def mock_context_loader(sample_document_context):
    """Mock context loader for testing."""
    loader = AsyncMock()
    loader.load.return_value = sample_document_context
    loader.exists.return_value = True
    return loader


@pytest.fixture
def mock_repository(sample_qa_record):
    """Mock repository for testing."""
    repository = AsyncMock()
    repository.save.return_value = sample_qa_record.unit_id
    repository.get_by_unit_id.return_value = sample_qa_record
    repository.exists.return_value = False
    repository.get_stats.return_value = {
        "total": 10,
        "winner_found": 7,
        "winner_not_found": 2,
        "service_files": 1,
        "with_errors": 0,
    }
    return repository
