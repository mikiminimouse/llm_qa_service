"""QA Orchestrator - main application logic."""

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from domain.entities import QARecord, WinnerExtractionResultV2
from domain.entities.extraction_components import DocumentInfo, ExtractionFlags, ProcurementInfo
from domain.interfaces.context_loader import IContextLoader
from domain.interfaces.llm_client import ILLMClient
from domain.interfaces.qa_repository import IQARepository
from infrastructure.prompt_manager import PromptManager

from .response_parser import ResponseParseError, ResponseParser
from .validators.result_validator import ResultValidator

logger = logging.getLogger(__name__)


@dataclass
class ProcessingResult:
    """Result of processing a single document."""

    unit_id: str
    success: bool
    record: Optional[QARecord] = None
    error: Optional[str] = None
    skipped: bool = False
    processing_time_ms: int = 0


class QAOrchestrator:
    """
    Main orchestrator for QA processing.

    Coordinates loading context, calling LLM, parsing responses,
    validating results, and storing to repository.
    """

    def __init__(
        self,
        llm_client: ILLMClient,
        context_loader: IContextLoader,
        repository: IQARepository,
        prompt_manager: PromptManager,
        skip_processed: bool = True,
        max_tokens: int = 4096,
        temperature: float = 0.1,
        save_to_unit_dir: bool = False,
        unit_base_paths: Optional[List[str]] = None,
    ):
        """
        Initialize orchestrator.

        Args:
            llm_client: LLM client for generation.
            context_loader: Loader for document context.
            repository: Repository for storing results.
            prompt_manager: Manager for loading prompts.
            skip_processed: Skip already processed documents.
            max_tokens: Max tokens for LLM response.
            temperature: LLM temperature setting.
            save_to_unit_dir: Save qa_results.json to UNIT directory.
            unit_base_paths: Base paths to search for UNIT directories.
        """
        self.llm_client = llm_client
        self.context_loader = context_loader
        self.repository = repository
        self.prompt_manager = prompt_manager
        self.skip_processed = skip_processed
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.save_to_unit_dir = save_to_unit_dir
        self.unit_base_paths = unit_base_paths or []

        self.response_parser = ResponseParser()
        self.validator = ResultValidator()

    async def process_protocol(self, unit_id: str) -> ProcessingResult:
        """
        Process a single protocol.

        Args:
            unit_id: Unique identifier of the document.

        Returns:
            ProcessingResult with success status and record.
        """
        start_time = time.time()

        # Check if already processed
        if self.skip_processed:
            exists = await self.repository.exists(unit_id)
            if exists:
                logger.info(f"Skipping already processed: {unit_id}")
                return ProcessingResult(
                    unit_id=unit_id,
                    success=True,
                    skipped=True,
                )

        try:
            # Load document context
            context = await self.context_loader.load(unit_id)
            if not context:
                return ProcessingResult(
                    unit_id=unit_id,
                    success=False,
                    error=f"Document not found: {unit_id}",
                )

            # Load prompts
            system_prompt = self.prompt_manager.get_system_prompt()
            user_prompt = self.prompt_manager.format_user_prompt(
                document_content=context.content,
            )

            # Call LLM
            llm_response = await self.llm_client.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
            )

            # Parse response
            extraction_result, raw_json = self.response_parser.parse(llm_response.content)
            extraction_result.raw_llm_response = llm_response.content

            # Set document info
            extraction_result.document.source_file = context.source_file

            # Validate
            issues = self.validator.validate(extraction_result, context.content)
            for issue in issues:
                if issue.level == "error":
                    logger.warning(f"Validation error for {unit_id}: {issue.message}")
                elif issue.level == "warning":
                    logger.debug(f"Validation warning for {unit_id}: {issue.message}")

            # Calculate processing time
            processing_time_ms = int((time.time() - start_time) * 1000)

            # Create QA record
            record = QARecord(
                unit_id=unit_id,
                source_file=context.source_file,
                result=extraction_result,
                model_used=self.llm_client.model_name,
                processing_time_ms=processing_time_ms,
            )

            # Save to repository
            await self.repository.save(record)

            # Save to UNIT directory if enabled
            if self.save_to_unit_dir and self.unit_base_paths:
                saved_path = await self.repository.save_to_unit_directory(
                    unit_id, record, self.unit_base_paths
                )
                if saved_path:
                    logger.info(f"Saved qa_results.json to {saved_path}")

            logger.info(
                f"Processed {unit_id}: winner_found={extraction_result.winner_found}, "
                f"time={processing_time_ms}ms"
            )

            return ProcessingResult(
                unit_id=unit_id,
                success=True,
                record=record,
                processing_time_ms=processing_time_ms,
            )

        except ResponseParseError as e:
            error_msg = f"Parse error: {e}"
            logger.error(f"Failed to process {unit_id}: {error_msg}")

            # Save error record
            error_record = await self._create_error_record(unit_id, error_msg)
            await self.repository.save(error_record)

            return ProcessingResult(
                unit_id=unit_id,
                success=False,
                error=error_msg,
                record=error_record,
                processing_time_ms=int((time.time() - start_time) * 1000),
            )

        except Exception as e:
            error_msg = f"Processing error: {e}"
            logger.error(f"Failed to process {unit_id}: {error_msg}")

            return ProcessingResult(
                unit_id=unit_id,
                success=False,
                error=error_msg,
                processing_time_ms=int((time.time() - start_time) * 1000),
            )

    async def process_batch(
        self,
        unit_ids: List[str],
        continue_on_error: bool = True,
    ) -> List[ProcessingResult]:
        """
        Process multiple protocols.

        Args:
            unit_ids: List of unit_ids to process.
            continue_on_error: Continue processing if one fails.

        Returns:
            List of ProcessingResults.
        """
        results = []

        for i, unit_id in enumerate(unit_ids):
            logger.info(f"Processing {i + 1}/{len(unit_ids)}: {unit_id}")

            result = await self.process_protocol(unit_id)
            results.append(result)

            if not result.success and not continue_on_error:
                logger.error(f"Stopping batch due to error: {result.error}")
                break

        # Log summary
        success_count = sum(1 for r in results if r.success)
        skipped_count = sum(1 for r in results if r.skipped)
        error_count = sum(1 for r in results if not r.success)

        logger.info(
            f"Batch complete: {success_count} success, {skipped_count} skipped, "
            f"{error_count} errors out of {len(results)}"
        )

        return results

    async def process_batch_parallel(
        self,
        unit_ids: List[str],
        max_concurrent: int = 3,
        continue_on_error: bool = True,
    ) -> List[ProcessingResult]:
        """
        Параллельная обработка нескольких протоколов.

        Args:
            unit_ids: Список unit_id для обработки.
            max_concurrent: Максимальное количество параллельных запросов.
            continue_on_error: Продолжать при ошибках.

        Returns:
            List of ProcessingResults.
        """
        semaphore = asyncio.Semaphore(max_concurrent)
        total = len(unit_ids)

        async def process_with_semaphore(unit_id: str, index: int) -> ProcessingResult:
            async with semaphore:
                logger.info(f"[{index + 1}/{total}] Processing: {unit_id}")
                try:
                    return await self.process_protocol(unit_id)
                except Exception as e:
                    logger.error(f"[{index + 1}/{total}] Error processing {unit_id}: {e}")
                    if continue_on_error:
                        return ProcessingResult(
                            unit_id=unit_id,
                            success=False,
                            error=str(e),
                        )
                    raise

        # Запуск всех задач параллельно (с ограничением через semaphore)
        tasks = [
            process_with_semaphore(unit_id, i)
            for i, unit_id in enumerate(unit_ids)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=continue_on_error)

        # Обработка исключений
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                processed_results.append(ProcessingResult(
                    unit_id=unit_ids[i],
                    success=False,
                    error=str(result),
                ))
            else:
                processed_results.append(result)

        # Log summary
        success_count = sum(1 for r in processed_results if r.success)
        skipped_count = sum(1 for r in processed_results if r.skipped)
        error_count = sum(1 for r in processed_results if not r.success)

        logger.info(
            f"Parallel batch complete: {success_count} success, {skipped_count} skipped, "
            f"{error_count} errors out of {len(processed_results)} (max_concurrent={max_concurrent})"
        )

        return processed_results

    async def process_batch_parallel_with_retry(
        self,
        unit_ids: List[str],
        max_concurrent: int = 3,
        retry_failed: bool = True,
        retry_delay_seconds: int = 30,
    ) -> List[ProcessingResult]:
        """
        Параллельная обработка с автоматическим retry для failed документов.

        Args:
            unit_ids: Список unit_id для обработки.
            max_concurrent: Максимальное количество параллельных запросов.
            retry_failed: Выполнять повторную обработку для failed.
            retry_delay_seconds: Задержка перед retry в секундах.

        Returns:
            List of ProcessingResults.
        """
        # Первый проход
        results = await self.process_batch_parallel(unit_ids, max_concurrent)

        if not retry_failed:
            return results

        # Собрать failed (исключая skipped)
        failed_ids = [r.unit_id for r in results if not r.success and not r.skipped]

        if failed_ids:
            logger.info(
                f"Retrying {len(failed_ids)} failed documents after {retry_delay_seconds}s delay..."
            )
            await asyncio.sleep(retry_delay_seconds)

            # Очистить failed записи из БД для повторной обработки
            for unit_id in failed_ids:
                try:
                    await self.repository.delete(unit_id)
                except Exception as e:
                    logger.warning(f"Failed to delete {unit_id} for retry: {e}")

            # Повторная обработка с уменьшенным параллелизмом
            retry_concurrent = max(1, max_concurrent // 2)
            logger.info(f"Retry pass with max_concurrent={retry_concurrent}")

            retry_results = await self.process_batch_parallel(
                failed_ids,
                max_concurrent=retry_concurrent,
            )

            # Объединить результаты: заменить failed на retry результаты
            results_map = {r.unit_id: r for r in results}
            for retry_result in retry_results:
                results_map[retry_result.unit_id] = retry_result

            results = list(results_map.values())

            # Log retry summary
            retry_success = sum(1 for r in retry_results if r.success)
            logger.info(
                f"Retry complete: {retry_success}/{len(failed_ids)} recovered"
            )

        return results

    async def _create_error_record(self, unit_id: str, error: str) -> QARecord:
        """Create QA record for failed processing."""
        return QARecord(
            unit_id=unit_id,
            result=WinnerExtractionResultV2(
                winner_found=False,
                winners=[],
                procurement=ProcurementInfo(),
                flags=ExtractionFlags(insufficient_data=True),
                document=DocumentInfo(),
                reasoning=f"Processing failed: {error}",
            ),
            error=error,
            model_used=self.llm_client.model_name,
        )

    async def get_result(self, unit_id: str) -> Optional[QARecord]:
        """Get existing result by unit_id."""
        return await self.repository.get_by_unit_id(unit_id)

    async def get_stats(self) -> dict:
        """Get processing statistics."""
        return await self.repository.get_stats()
