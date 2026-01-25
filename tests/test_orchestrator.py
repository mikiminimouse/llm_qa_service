"""Tests for QA orchestrator."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from application.orchestrator import QAOrchestrator, ProcessingResult
from infrastructure.prompt_manager import PromptManager


class TestQAOrchestrator:
    """Tests for QAOrchestrator."""

    @pytest.fixture
    def prompt_manager(self, tmp_path):
        """Create prompt manager with test prompts."""
        # Create test prompt files
        system_dir = tmp_path / "prompts" / "system"
        user_dir = tmp_path / "prompts" / "user"
        system_dir.mkdir(parents=True)
        user_dir.mkdir(parents=True)

        (system_dir / "winner_extractor_v2.txt").write_text("Test system prompt")
        (user_dir / "extract_winner_v2.txt").write_text("<document>\n$document_content\n</document>")

        return PromptManager(prompts_dir=str(tmp_path / "prompts"))

    @pytest.fixture
    def orchestrator(self, mock_llm_client, mock_context_loader, mock_repository, prompt_manager):
        """Create orchestrator with mocked dependencies."""
        return QAOrchestrator(
            llm_client=mock_llm_client,
            context_loader=mock_context_loader,
            repository=mock_repository,
            prompt_manager=prompt_manager,
            skip_processed=True,
        )

    @pytest.mark.asyncio
    async def test_process_protocol_success(self, orchestrator, mock_llm_client):
        """Test successful protocol processing."""
        # Setup LLM response
        mock_llm_client.generate.return_value.content = """
{
    "winner_found": true,
    "winners": [{"name": "ООО Тест", "inn": "1234567890"}],
    "procurement_info": {"status": "completed"},
    "document_info": {"type": "итоговый_протокол"},
    "reasoning": "Победитель найден"
}
"""
        result = await orchestrator.process_protocol("UNIT_test123")

        assert result.success is True
        assert result.unit_id == "UNIT_test123"
        assert result.record is not None
        assert result.record.winner_found is True

    @pytest.mark.asyncio
    async def test_process_protocol_skip_processed(self, orchestrator, mock_repository):
        """Test skipping already processed protocol."""
        mock_repository.exists.return_value = True

        result = await orchestrator.process_protocol("UNIT_test123")

        assert result.success is True
        assert result.skipped is True

    @pytest.mark.asyncio
    async def test_process_protocol_not_found(self, orchestrator, mock_context_loader):
        """Test processing non-existent document."""
        mock_context_loader.load.return_value = None

        result = await orchestrator.process_protocol("UNIT_nonexistent")

        assert result.success is False
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_process_protocol_parse_error(self, orchestrator, mock_llm_client):
        """Test handling LLM response parse error."""
        mock_llm_client.generate.return_value.content = "Invalid response without JSON"

        result = await orchestrator.process_protocol("UNIT_test123")

        assert result.success is False
        assert "parse error" in result.error.lower()

    @pytest.mark.asyncio
    async def test_process_batch(self, orchestrator, mock_repository):
        """Test batch processing."""
        mock_repository.exists.return_value = False

        results = await orchestrator.process_batch(
            unit_ids=["UNIT_1", "UNIT_2", "UNIT_3"],
            continue_on_error=True,
        )

        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_get_stats(self, orchestrator, mock_repository):
        """Test getting statistics."""
        stats = await orchestrator.get_stats()

        assert stats["total"] == 10
        assert stats["winner_found"] == 7
        mock_repository.get_stats.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_result(self, orchestrator, mock_repository, sample_qa_record):
        """Test getting existing result."""
        mock_repository.get_by_unit_id.return_value = sample_qa_record

        result = await orchestrator.get_result("UNIT_test123")

        assert result is not None
        assert result.unit_id == "UNIT_test123"


class TestProcessingResult:
    """Tests for ProcessingResult dataclass."""

    def test_processing_result_success(self):
        """Test successful processing result."""
        result = ProcessingResult(
            unit_id="UNIT_test",
            success=True,
            processing_time_ms=100,
        )
        assert result.success is True
        assert result.skipped is False
        assert result.error is None

    def test_processing_result_skipped(self):
        """Test skipped processing result."""
        result = ProcessingResult(
            unit_id="UNIT_test",
            success=True,
            skipped=True,
        )
        assert result.success is True
        assert result.skipped is True

    def test_processing_result_error(self):
        """Test failed processing result."""
        result = ProcessingResult(
            unit_id="UNIT_test",
            success=False,
            error="Some error",
        )
        assert result.success is False
        assert result.error == "Some error"
