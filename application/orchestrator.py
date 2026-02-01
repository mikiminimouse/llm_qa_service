"""QA Orchestrator - main application logic."""

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

# Директория для сохранения "плохих" ответов LLM
BAD_RESPONSES_DIR = Path("/home/pak/llm_qa_service/bad_responses")
BAD_RESPONSES_DIR.mkdir(parents=True, exist_ok=True)

from domain.entities import QARecord, WinnerExtractionResultV2
from domain.entities.extraction_components import DocumentInfo, ExtractionFlags, ProcurementInfo
from domain.interfaces.context_loader import IContextLoader
from domain.interfaces.llm_client import ILLMClient
from domain.interfaces.qa_repository import IQARepository
from infrastructure.prompt_manager import PromptManager

from .response_parser import ResponseParseError, ResponseParser
from .validators.result_validator import ResultValidator

# Traceability
from domain.entities.extraction_components import HistoryEvent, TraceInfo

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
        processing_start = datetime.utcnow()

        # Переменные для хранения контекста при ошибках
        context = None
        llm_response = None

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

            # Traceability: извлекаем метаданные
            registration_number = context.metadata.get("registration_number")
            existing_trace = context.metadata.get("trace", {})
            existing_history = context.metadata.get("history", [])

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
            # Извлекаем исходный номер госзакупки из контекста (если есть)
            source_number = context.metadata.get("purchase_notice_number")
            extraction_result, raw_json = self.response_parser.parse(llm_response.content, source_number=source_number)
            extraction_result.raw_llm_response = llm_response.content

            # Traceability: добавляем registration_number в procurement
            if registration_number:
                extraction_result.procurement.registration_number = registration_number

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
            processing_end = datetime.utcnow()

            # Traceability: создаем TraceInfo
            trace_info = TraceInfo(
                component="llm_qaenrich",
                unit_id=unit_id,
                processed_at=processing_end.isoformat() + "Z",
                registration_number=registration_number,
                model_used=self.llm_client.model_name,
                processing_time_ms=processing_time_ms,
            )
            extraction_result.trace = trace_info

            # Traceability: создаем события истории
            history_events = [
                HistoryEvent(
                    component="llm_qaenrich",
                    action="loaded",
                    timestamp=processing_start.isoformat() + "Z",
                    registration_number=registration_number,
                    details={
                        "source_file": context.source_file,
                        "content_length": len(context.content),
                        "content_type": context.content_type,
                    },
                ),
                HistoryEvent(
                    component="llm_qaenrich",
                    action="processed",
                    timestamp=processing_end.isoformat() + "Z",
                    registration_number=registration_number,
                    details={
                        "winner_found": extraction_result.winner_found,
                        "model_used": self.llm_client.model_name,
                        "processing_time_ms": processing_time_ms,
                    },
                ),
            ]

            # Объединяем существующую историю с новой
            extraction_result.history = existing_history + history_events

            # Create QA record
            record = QARecord(
                unit_id=unit_id,
                # ★ ЕДИНАЯ СИСТЕМА ТРЕЙСИНГА: PRIMARY TRACE ID и связанные поля
                registration_number=registration_number,
                purchase_notice_number=context.metadata.get("purchase_notice_number"),
                record_id=context.metadata.get("record_id"),
                protocol_id=context.metadata.get("protocol_id"),  # Для обратной совместимости
                protocol_guid=context.metadata.get("protocol_guid"),
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
                f"time={processing_time_ms}ms, reg_number={registration_number}"
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

            # Сохраняем "плохой" ответ для анализа
            if llm_response and llm_response.content:
                self._save_bad_response(unit_id, llm_response.content, str(e), context)

            # Save error record with trace
            processing_time_ms = int((time.time() - start_time) * 1000)
            registration_number = context.metadata.get("registration_number") if context else None
            error_record = await self._create_error_record(
                unit_id, error_msg, llm_response,
                registration_number=registration_number,
                purchase_notice_number=context.metadata.get("purchase_notice_number") if context else None,
                record_id=context.metadata.get("record_id") if context else None,
                protocol_id=context.metadata.get("protocol_id") if context else None,
                processing_time_ms=processing_time_ms,
            )
            await self.repository.save(error_record)

            return ProcessingResult(
                unit_id=unit_id,
                success=False,
                error=error_msg,
                record=error_record,
                processing_time_ms=processing_time_ms,
            )

        except Exception as e:
            error_msg = f"Processing error: {e}"
            logger.error(f"Failed to process {unit_id}: {error_msg}")

            # Сохраняем "плохой" ответ для анализа
            if llm_response and llm_response.content:
                self._save_bad_response(unit_id, llm_response.content, str(e), context)

            return ProcessingResult(
                unit_id=unit_id,
                success=False,
                error=error_msg,
                processing_time_ms=int((time.time() - start_time) * 1000),
            )

    def _save_bad_response(
        self,
        unit_id: str,
        llm_content: str,
        error: str,
        context=None
    ) -> None:
        """Сохранить "плохой" ответ LLM для анализа."""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{unit_id}_{timestamp}.txt"
            filepath = BAD_RESPONSES_DIR / filename

            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(f"Unit ID: {unit_id}\n")
                f.write(f"Timestamp: {timestamp}\n")
                f.write(f"Error: {error}\n")
                f.write(f"Content Length: {len(context.content) if context else 'N/A'}\n")
                f.write("=" * 70 + "\n\n")
                f.write("LLM RESPONSE:\n")
                f.write(llm_content)
                f.write("\n\n" + "=" * 70 + "\n\n")
                if context and context.content:
                    preview = context.content[:2000]
                    f.write(f"DOCUMENT PREVIEW (first 2000 chars):\n{preview}...")

            logger.debug(f"Saved bad response to {filepath}")
        except Exception as save_error:
            logger.warning(f"Failed to save bad response for {unit_id}: {save_error}")

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

    async def _create_error_record(
        self,
        unit_id: str,
        error: str,
        llm_response=None,
        registration_number: Optional[str] = None,
        purchase_notice_number: Optional[str] = None,
        record_id: Optional[str] = None,
        protocol_id: Optional[str] = None,
        processing_time_ms: int = 0,
    ) -> QARecord:
        """Create QA record for failed processing."""
        processing_time = datetime.utcnow()

        reasoning = f"Processing failed: {error}"
        if llm_response and llm_response.content:
            reasoning += f"\n\nRaw LLM response (first 500 chars):\n{llm_response.content[:500]}..."

        # Traceability: создаем trace даже для ошибок
        trace_info = TraceInfo(
            component="llm_qaenrich",
            unit_id=unit_id,
            processed_at=processing_time.isoformat() + "Z",
            registration_number=registration_number,
            model_used=self.llm_client.model_name,
            processing_time_ms=processing_time_ms,
        )

        history_event = HistoryEvent(
            component="llm_qaenrich",
            action="error",
            timestamp=processing_time.isoformat() + "Z",
            registration_number=registration_number,
            details={"error": error},
        )

        result = WinnerExtractionResultV2(
            winner_found=False,
            winners=[],
            procurement=ProcurementInfo(registration_number=registration_number),
            flags=ExtractionFlags(insufficient_data=True),
            document=DocumentInfo(),
            reasoning=reasoning,
            trace=trace_info,
            history=[history_event],
        )

        return QARecord(
            unit_id=unit_id,
            # ★ ЕДИНАЯ СИСТЕМА ТРЕЙСИНГА: сохраняем поля трейсинга даже при ошибках
            registration_number=registration_number,
            purchase_notice_number=purchase_notice_number,
            record_id=record_id,
            protocol_id=protocol_id,
            result=result,
            error=error,
            model_used=self.llm_client.model_name,
        )

    async def get_result(self, unit_id: str) -> Optional[QARecord]:
        """Get existing result by unit_id."""
        return await self.repository.get_by_unit_id(unit_id)

    async def get_stats(self) -> dict:
        """Get processing statistics."""
        return await self.repository.get_stats()
