"""API routes for QA service."""

import logging
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from config import Settings, get_settings

from .dependencies import get_context_loader, get_orchestrator, get_repository
from .schemas import (
    BatchResultItem,
    ErrorResponse,
    HealthResponse,
    ProcessBatchParallelRequest,
    ProcessBatchParallelResponse,
    ProcessBatchParallelRetryRequest,
    ProcessBatchParallelRetryResponse,
    ProcessBatchRequest,
    ProcessBatchResponse,
    ProcessProtocolRequest,
    ProcessProtocolResponse,
    QAResultResponse,
    StatsResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/qa", tags=["qa"])


@router.post(
    "/process",
    response_model=ProcessProtocolResponse,
    responses={404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
async def process_protocol(
    request: ProcessProtocolRequest,
    orchestrator=Depends(get_orchestrator),
):
    """
    Process a single protocol to extract winner information.

    - **unit_id**: Unit ID from docling_results collection
    - **force**: Force reprocessing even if result already exists
    """
    # If force, temporarily disable skip_processed
    original_skip = orchestrator.skip_processed
    if request.force:
        orchestrator.skip_processed = False

    try:
        result = await orchestrator.process_protocol(request.unit_id)

        response = ProcessProtocolResponse(
            unit_id=result.unit_id,
            success=result.success,
            skipped=result.skipped,
            error=result.error,
            processing_time_ms=result.processing_time_ms,
        )

        if result.record:
            response.winner_found = result.record.winner_found
            response.winner_name = result.record.winner_name
            response.winner_inn = result.record.winner_inn
            response.is_service_file = result.record.is_service_file

        return response

    finally:
        orchestrator.skip_processed = original_skip


@router.post(
    "/process/batch",
    response_model=ProcessBatchResponse,
    responses={500: {"model": ErrorResponse}},
)
async def process_batch(
    request: ProcessBatchRequest,
    orchestrator=Depends(get_orchestrator),
):
    """
    Process multiple protocols in batch.

    - **unit_ids**: List of unit IDs to process
    - **continue_on_error**: Continue processing if individual items fail
    """
    results = await orchestrator.process_batch(
        unit_ids=request.unit_ids,
        continue_on_error=request.continue_on_error,
    )

    items = [
        BatchResultItem(
            unit_id=r.unit_id,
            success=r.success,
            skipped=r.skipped,
            error=r.error,
        )
        for r in results
    ]

    return ProcessBatchResponse(
        total=len(results),
        success=sum(1 for r in results if r.success),
        skipped=sum(1 for r in results if r.skipped),
        failed=sum(1 for r in results if not r.success),
        results=items,
    )


@router.post(
    "/process/batch-parallel",
    response_model=ProcessBatchParallelResponse,
    responses={500: {"model": ErrorResponse}},
)
async def process_batch_parallel(
    request: ProcessBatchParallelRequest,
    orchestrator=Depends(get_orchestrator),
):
    """
    Process multiple protocols in parallel.

    - **unit_ids**: List of unit IDs to process
    - **max_concurrent**: Maximum number of parallel requests (1-10)
    - **continue_on_error**: Continue processing if individual items fail
    """
    start_time = time.time()

    results = await orchestrator.process_batch_parallel(
        unit_ids=request.unit_ids,
        max_concurrent=request.max_concurrent,
        continue_on_error=request.continue_on_error,
    )

    total_time = time.time() - start_time

    items = [
        BatchResultItem(
            unit_id=r.unit_id,
            success=r.success,
            skipped=r.skipped,
            error=r.error,
        )
        for r in results
    ]

    return ProcessBatchParallelResponse(
        total=len(results),
        success=sum(1 for r in results if r.success),
        skipped=sum(1 for r in results if r.skipped),
        failed=sum(1 for r in results if not r.success),
        max_concurrent=request.max_concurrent,
        total_time_seconds=round(total_time, 2),
        avg_time_per_doc_ms=round(total_time * 1000 / len(results), 0) if results else 0,
        results=items,
    )


@router.post(
    "/process/batch-parallel-retry",
    response_model=ProcessBatchParallelRetryResponse,
    responses={500: {"model": ErrorResponse}},
)
async def process_batch_parallel_retry(
    request: ProcessBatchParallelRetryRequest,
    orchestrator=Depends(get_orchestrator),
):
    """
    Process multiple protocols in parallel with automatic retry for failed documents.

    - **unit_ids**: List of unit IDs to process
    - **max_concurrent**: Maximum number of parallel requests (1-10)
    - **retry_failed**: Automatically retry failed documents after delay
    - **retry_delay_seconds**: Delay before retrying failed documents (5-120 seconds)
    """
    start_time = time.time()

    # Подсчитаем failed до retry для статистики
    initial_results = await orchestrator.process_batch_parallel(
        unit_ids=request.unit_ids,
        max_concurrent=request.max_concurrent,
    )

    initial_failed = [r for r in initial_results if not r.success and not r.skipped]
    initial_failed_count = len(initial_failed)

    # Если retry включён и есть failed - делаем retry
    if request.retry_failed and initial_failed:
        import asyncio

        failed_ids = [r.unit_id for r in initial_failed]
        logger.info(f"Waiting {request.retry_delay_seconds}s before retry...")
        await asyncio.sleep(request.retry_delay_seconds)

        # Очистить failed для повторной обработки
        repository = get_repository()
        for unit_id in failed_ids:
            try:
                await repository.delete(unit_id)
            except Exception:
                pass

        # Retry с уменьшенным параллелизмом
        retry_concurrent = max(1, request.max_concurrent // 2)
        retry_results = await orchestrator.process_batch_parallel(
            unit_ids=failed_ids,
            max_concurrent=retry_concurrent,
        )

        # Объединить результаты
        results_map = {r.unit_id: r for r in initial_results}
        for retry_result in retry_results:
            results_map[retry_result.unit_id] = retry_result

        results = list(results_map.values())
        recovered = sum(1 for r in retry_results if r.success)
    else:
        results = initial_results
        recovered = 0

    total_time = time.time() - start_time

    items = [
        BatchResultItem(
            unit_id=r.unit_id,
            success=r.success,
            skipped=r.skipped,
            error=r.error,
        )
        for r in results
    ]

    return ProcessBatchParallelRetryResponse(
        total=len(results),
        success=sum(1 for r in results if r.success),
        skipped=sum(1 for r in results if r.skipped),
        failed=sum(1 for r in results if not r.success),
        retried=initial_failed_count,
        recovered=recovered,
        max_concurrent=request.max_concurrent,
        total_time_seconds=round(total_time, 2),
        avg_time_per_doc_ms=round(total_time * 1000 / len(results), 0) if results else 0,
        results=items,
    )


@router.get(
    "/result/{unit_id}",
    response_model=QAResultResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_result(
    unit_id: str,
    orchestrator=Depends(get_orchestrator),
):
    """
    Get existing QA result by unit_id.

    Returns 404 if not found.
    """
    record = await orchestrator.get_result(unit_id)

    if not record:
        raise HTTPException(status_code=404, detail=f"Result not found for unit_id: {unit_id}")

    return QAResultResponse(
        unit_id=record.unit_id,
        winner_found=record.winner_found,
        result=record.result,
        source_file=record.source_file,
        model_used=record.model_used,
        processed_at=record.processed_at,
        processing_time_ms=record.processing_time_ms,
    )


@router.get(
    "/stats",
    response_model=StatsResponse,
)
async def get_stats(
    orchestrator=Depends(get_orchestrator),
):
    """Get processing statistics."""
    stats = await orchestrator.get_stats()
    return StatsResponse(**stats)


@router.get(
    "/health",
    response_model=HealthResponse,
)
async def health_check(
    settings: Settings = Depends(get_settings),
):
    """
    Health check endpoint.

    Checks MongoDB and LLM connectivity.
    """
    mongodb_ok = True
    llm_ok = True

    # Check MongoDB
    try:
        loader = get_context_loader()
        await loader.count()
    except Exception as e:
        logger.error(f"MongoDB health check failed: {e}")
        mongodb_ok = False

    # LLM check is optional (skip for health endpoint to avoid costs)

    status = "ok" if mongodb_ok else "degraded"

    return HealthResponse(
        status=status,
        mongodb=mongodb_ok,
        llm=llm_ok,
        version="1.0.0",
    )


@router.get(
    "/documents",
    response_model=list[str],
)
async def list_documents(
    limit: int = Query(default=100, le=1000),
    skip: int = Query(default=0, ge=0),
):
    """
    List available document unit_ids from source collection.

    Useful for discovering what can be processed.
    """
    loader = get_context_loader()
    return await loader.list_unit_ids(limit=limit, skip=skip)


@router.delete(
    "/result/{unit_id}",
    response_model=dict,
    responses={404: {"model": ErrorResponse}},
)
async def delete_result(
    unit_id: str,
    repository=Depends(get_repository),
):
    """
    Delete QA result by unit_id.

    Returns 404 if not found.
    """
    deleted = await repository.delete(unit_id)

    if not deleted:
        raise HTTPException(status_code=404, detail=f"Result not found for unit_id: {unit_id}")

    return {"deleted": True, "unit_id": unit_id}
