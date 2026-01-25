"""API request/response schemas."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from domain.entities import WinnerExtractionResultV2


class ProcessProtocolRequest(BaseModel):
    """Request to process a single protocol."""

    unit_id: str = Field(..., description="Unit ID from docling_results")
    force: bool = Field(default=False, description="Force reprocessing even if already exists")


class ProcessBatchRequest(BaseModel):
    """Request to process multiple protocols."""

    unit_ids: List[str] = Field(..., description="List of unit IDs to process")
    continue_on_error: bool = Field(default=True, description="Continue on individual errors")


class ProcessBatchParallelRequest(BaseModel):
    """Request to process multiple protocols in parallel."""

    unit_ids: List[str] = Field(..., description="List of unit IDs to process")
    max_concurrent: int = Field(default=3, ge=1, le=10, description="Max parallel requests")
    continue_on_error: bool = Field(default=True, description="Continue on individual errors")


class ProcessBatchParallelRetryRequest(BaseModel):
    """Request to process multiple protocols in parallel with automatic retry for failed."""

    unit_ids: List[str] = Field(..., description="List of unit IDs to process")
    max_concurrent: int = Field(default=3, ge=1, le=10, description="Max parallel requests")
    retry_failed: bool = Field(default=True, description="Automatically retry failed documents")
    retry_delay_seconds: int = Field(default=30, ge=5, le=120, description="Delay before retry in seconds")


class ProcessBatchParallelRetryResponse(BaseModel):
    """Response for parallel batch processing with retry."""

    total: int
    success: int
    skipped: int
    failed: int
    retried: int
    recovered: int
    max_concurrent: int
    total_time_seconds: float
    avg_time_per_doc_ms: float
    results: List["BatchResultItem"]


class ProcessProtocolResponse(BaseModel):
    """Response for single protocol processing."""

    unit_id: str
    success: bool
    winner_found: Optional[bool] = None
    winner_name: Optional[str] = None
    winner_inn: Optional[str] = None
    is_service_file: bool = False
    skipped: bool = False
    error: Optional[str] = None
    processing_time_ms: int = 0


class BatchResultItem(BaseModel):
    """Single item in batch processing response."""

    unit_id: str
    success: bool
    skipped: bool = False
    error: Optional[str] = None


class ProcessBatchResponse(BaseModel):
    """Response for batch processing."""

    total: int
    success: int
    skipped: int
    failed: int
    results: List[BatchResultItem]


class ProcessBatchParallelResponse(BaseModel):
    """Response for parallel batch processing."""

    total: int
    success: int
    skipped: int
    failed: int
    max_concurrent: int
    total_time_seconds: float
    avg_time_per_doc_ms: float
    results: List[BatchResultItem]


class QAResultResponse(BaseModel):
    """Response containing full QA result."""

    unit_id: str
    winner_found: bool
    result: WinnerExtractionResultV2
    source_file: Optional[str] = None
    model_used: Optional[str] = None
    processed_at: datetime
    processing_time_ms: Optional[int] = None


class StatsResponse(BaseModel):
    """Response containing processing statistics."""

    total: int = 0
    winner_found: int = 0
    winner_not_found: int = 0
    service_files: int = 0
    with_errors: int = 0


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = "ok"
    mongodb: bool = True
    llm: bool = True
    version: str = "1.0.0"


class ErrorResponse(BaseModel):
    """Error response."""

    detail: str
    error_code: Optional[str] = None
