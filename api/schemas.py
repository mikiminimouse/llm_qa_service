"""API request/response schemas.

NOTE: Terminology updated for delivery processing system:
- "protocol" → "delivery document" (документ о поставке)
- "winner" → "supplier" (поставщик)
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from domain.entities import WinnerExtractionResultV2


class ProcessProtocolRequest(BaseModel):
    """
    Request to process a single delivery document.

    Legacy name: ProcessProtocolRequest (kept for backward compatibility).
    New code should use ProcessDeliveryDocumentRequest.
    """

    unit_id: str = Field(..., description="Unit ID from docling_results")
    force: bool = Field(default=False, description="Force reprocessing even if already exists")


class ProcessBatchRequest(BaseModel):
    """Request to process multiple delivery documents."""

    unit_ids: List[str] = Field(..., description="List of unit IDs to process")
    continue_on_error: bool = Field(default=True, description="Continue on individual errors")


class ProcessBatchParallelRequest(BaseModel):
    """Request to process multiple delivery documents in parallel."""

    unit_ids: List[str] = Field(..., description="List of unit IDs to process")
    max_concurrent: int = Field(default=3, ge=1, le=10, description="Max parallel requests")
    continue_on_error: bool = Field(default=True, description="Continue on individual errors")


class ProcessBatchParallelRetryRequest(BaseModel):
    """Request to process multiple delivery documents in parallel with automatic retry for failed."""

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
    """
    Response for single delivery document processing.

    Legacy name: ProcessProtocolResponse (kept for backward compatibility).
    Fields use both old (winner_*) and new (supplier_*) naming for compatibility.
    """

    unit_id: str
    success: bool
    # New field names
    supplier_found: Optional[bool] = Field(None, description="Supplier found in document")
    supplier_name: Optional[str] = Field(None, description="Supplier name")
    supplier_inn: Optional[str] = Field(None, description="Supplier INN")
    # Legacy aliases (for backward compatibility)
    winner_found: Optional[bool] = Field(None, description="Legacy: use supplier_found")
    winner_name: Optional[str] = Field(None, description="Legacy: use supplier_name")
    winner_inn: Optional[str] = Field(None, description="Legacy: use supplier_inn")
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
    supplier_found: bool = Field(..., description="Supplier found in document")
    result: WinnerExtractionResultV2
    source_file: Optional[str] = None
    model_used: Optional[str] = None
    processed_at: datetime
    processing_time_ms: Optional[int] = None

    # Legacy alias
    @property
    def winner_found(self) -> bool:
        """Legacy alias for supplier_found."""
        return self.supplier_found


class StatsResponse(BaseModel):
    """
    Response containing processing statistics.

    Field names updated for delivery processing:
    - winner_found → supplier_found
    """

    total: int = 0
    supplier_found: int = Field(0, description="Documents with supplier found")
    supplier_not_found: int = Field(0, description="Documents without supplier")
    service_files: int = 0
    with_errors: int = 0

    # Legacy aliases
    @property
    def winner_found(self) -> int:
        """Legacy alias for supplier_found."""
        return self.supplier_found

    @property
    def winner_not_found(self) -> int:
        """Legacy alias for supplier_not_found."""
        return self.supplier_not_found


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = "ok"
    postgresql: bool = Field(True, description="PostgreSQL connection status")
    mongodb: bool = Field(True, description="MongoDB connection status (legacy)")
    llm: bool = True
    version: str = "2.0.0"  # Delivery Processing v2.0


class ErrorResponse(BaseModel):
    """Error response."""

    detail: str
    error_code: Optional[str] = None
