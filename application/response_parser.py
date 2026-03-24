"""Parser for LLM responses to extract structured data.

NOTE: Terminology updated for delivery processing system:
- "winner" → "supplier" (поставщик)
- "protocol" → "delivery document" (документ о поставке)
- "purchaseProtocol" → "week_docs"
"""

import json
import logging
import re
from typing import Optional, Tuple

from pydantic import ValidationError

from domain.entities import WinnerExtractionResultV2
from domain.entities.enums import DocumentType, NotHeldReason, ParticipantStatus, ProcurementStatus
from domain.entities.extraction_components import CustomerInfo, DocumentInfo, ExtractionFlags, ProcurementInfo
from domain.entities.supplier import OtherParticipant, SupplierInfo

# Legacy alias for backward compatibility
WinnerInfo = SupplierInfo

logger = logging.getLogger(__name__)


class ResponseParseError(Exception):
    """Error during response parsing."""

    pass


class ResponseParser:
    """
    Parser for LLM responses.

    Extracts JSON from various response formats and validates
    against Pydantic models.
    """

    # Patterns for JSON extraction
    JSON_BLOCK_PATTERN = re.compile(r"```(?:json)?\s*\n?(.*?)\n?```", re.DOTALL)
    # Improved pattern to find balanced JSON objects
    JSON_OBJECT_PATTERN = re.compile(r"\{(?:[^{}]|(?:\{[^{}]*\}))*\}", re.DOTALL)

    def parse(self, response: str, source_number: str = None) -> Tuple[WinnerExtractionResultV2, str]:
        """
        Parse LLM response to WinnerExtractionResultV2.

        Args:
            response: Raw LLM response text.
            source_number: Исходный номер госзакупки (11 цифр) из contracts.week_docs.

        Returns:
            Tuple of (WinnerExtractionResultV2, raw_json_str).

        Raises:
            ResponseParseError: If parsing fails.
        """
        # Extract JSON from response
        json_str = self._extract_json(response)
        if not json_str:
            raise ResponseParseError("No JSON found in response")

        # Parse JSON
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            raise ResponseParseError(f"Invalid JSON: {e}")

        # Transform to our model structure
        try:
            result = self._transform_to_result(data, source_number=source_number)
            return result, json_str
        except ValidationError as e:
            raise ResponseParseError(f"Validation error: {e}")

    def _extract_json(self, text: str) -> Optional[str]:
        """
        Extract JSON from response text with robust fallback logic.

        Tries multiple strategies:
        1. Look for ```json blocks
        2. Look for raw JSON object (balanced braces)
        3. Try to fix common JSON issues and retry
        """
        # Try markdown code block first
        match = self.JSON_BLOCK_PATTERN.search(text)
        if match:
            json_str = match.group(1).strip()
            if self._is_valid_json(json_str):
                return json_str

        # Try raw JSON object with balanced braces
        match = self.JSON_OBJECT_PATTERN.search(text)
        if match:
            json_str = match.group(0).strip()
            if self._is_valid_json(json_str):
                return json_str

        # Try to find the largest valid JSON substring
        logger.debug("Standard extraction failed, trying fallback methods")
        return self._extract_json_fallback(text)

    def _is_valid_json(self, text: str) -> bool:
        """Check if text is valid JSON."""
        try:
            json.loads(text)
            return True
        except (json.JSONDecodeError, ValueError):
            return False

    def _extract_json_fallback(self, text: str) -> Optional[str]:
        """
        Fallback JSON extraction with common fixes.

        Tries to fix common JSON issues:
        - Trailing commas
        - Missing quotes around keys
        - Single quotes instead of double quotes
        """
        # Try to find JSON-like patterns
        candidates = []

        # Look for content between first { and last }
        first_brace = text.find("{")
        last_brace = text.rfind("}")
        if first_brace != -1 and last_brace > first_brace:
            candidates.append(text[first_brace:last_brace + 1])

        # Look for content between ``` and ```
        for match in re.finditer(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL):
            candidates.append(match.group(1).strip())

        # Try to fix each candidate
        for candidate in candidates:
            # Try as-is first
            if self._is_valid_json(candidate):
                return candidate

            # Try common fixes
            fixed = self._fix_json(candidate)
            if fixed and self._is_valid_json(fixed):
                logger.debug("Fixed broken JSON with common patches")
                return fixed

        return None

    def _fix_json(self, text: str) -> Optional[str]:
        """
        Attempt to fix common JSON issues.

        Fixes:
        - Trailing commas in arrays/objects
        - Single quotes to double quotes
        - Unquoted keys
        """
        if not text:
            return None

        fixed = text

        # Remove trailing commas before } or ]
        fixed = re.sub(r",(\s*[}\]])", r"\1", fixed)

        # Fix single quotes to double quotes (simple case)
        # This is a basic fix - more complex cases may require json5
        fixed = fixed.replace("'", '"')

        # Try to fix unquoted keys (basic pattern)
        # This is conservative - only fixes obvious cases
        fixed = re.sub(r"(\{)\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:", r'\1"\2":', fixed)
        fixed = re.sub(r",\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:", r', "\1":', fixed)

        return fixed.strip() if fixed != text else None

    def _transform_to_result(self, data: dict, source_number: str = None) -> WinnerExtractionResultV2:
        """
        Transform LLM JSON output to WinnerExtractionResultV2.

        Args:
            data: Parsed JSON dictionary.
            source_number: Исходный номер госзакупки (11 цифр) из contracts.week_docs.

        Returns:
            WinnerExtractionResultV2 model.
        """
        # Extract suppliers (previously "winners")
        suppliers = []
        for w in data.get("winners", []):
            supplier = SupplierInfo(
                name=w.get("name", "Unknown"),
                inn=w.get("inn"),
                kpp=w.get("kpp"),
                ogrn=w.get("ogrn"),
                address=w.get("address"),
                contract_price=self._parse_price(w.get("contract_price")),
                delivery_amount=self._parse_price(w.get("delivery_amount") or w.get("contract_price")),
                status=self._parse_participant_status(w.get("status", "winner")),
                confidence=w.get("confidence", 1.0),
            )
            suppliers.append(supplier)

        # Extract other participants
        other_participants = []
        for p in data.get("other_participants", []):
            participant = OtherParticipant(
                name=p.get("name", "Unknown"),
                inn=p.get("inn"),
                status=self._parse_participant_status(p.get("status", "admitted")),
                rejection_reason=p.get("rejection_reason"),
                proposed_price=self._parse_price(p.get("price")),
            )
            other_participants.append(participant)

        # Extract procurement info
        procurement_data = data.get("procurement_info", {})
        raw_number = procurement_data.get("number")
        procurement = ProcurementInfo(
            purchase_number=raw_number,  # Сырой номер от LLM (для обратной совместимости)
            purchase_notice_number=self._normalize_purchase_number(raw_number, source_number),  # Используем только исходный номер
            purchase_name=procurement_data.get("name"),
            initial_price=self._parse_price(procurement_data.get("initial_price")),
            final_price=self._parse_price(procurement_data.get("final_price")),
            status=self._parse_procurement_status(procurement_data.get("status", "unknown")),
            not_held_reason=self._parse_not_held_reason(procurement_data.get("not_held_reason")),
        )

        # Extract flags
        flags_data = data.get("flags", {})
        document_info = data.get("document_info", {})
        flags = ExtractionFlags(
            is_service_file=document_info.get("is_service_file", False),
            is_multi_lot=flags_data.get("multiple_lots", False),
            no_winner_declared=not data.get("winner_found", False) and not winners,
            procurement_cancelled=procurement.status == ProcurementStatus.CANCELLED,
            single_participant=flags_data.get("is_single_participant_winner", False),
            all_rejected=procurement.not_held_reason == NotHeldReason.ALL_REJECTED,
            insufficient_data=document_info.get("no_useful_content", False),
        )

        # Extract document info
        document = DocumentInfo(
            document_type=self._parse_document_type(document_info.get("type", "unknown")),
            content_quality="good" if not document_info.get("has_encoding_issues", False) else "poor",
        )

        # Extract customer info (for validation - to ensure we don't confuse with winner)
        customer_data = data.get("customer_info", {})
        customer = CustomerInfo(
            name=customer_data.get("name"),
            inn=customer_data.get("inn"),
        )

        return WinnerExtractionResultV2(
            winner_found=data.get("winner_found", False),
            suppliers=suppliers,  # New field name (uses winners property for compatibility)
            other_participants=other_participants,
            procurement=procurement,
            customer=customer,
            flags=flags,
            document=document,
            reasoning=data.get("reasoning"),
            raw_llm_response=None,  # Will be set by caller
        )

    def _parse_price(self, value) -> Optional[float]:
        """Parse price string to float."""
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            # Remove currency and spaces
            cleaned = re.sub(r"[^\d.,]", "", value)
            cleaned = cleaned.replace(",", ".").replace(" ", "")
            if cleaned:
                try:
                    return float(cleaned)
                except ValueError:
                    return None
        return None

    def _normalize_purchase_number(self, raw_number: str, source_number: str = None) -> Optional[str]:
        """
        Нормализовать номер закупки к формату purchaseNoticeNumber (223-ФЗ).

        ПРИОРИТЕТ:
        1. source_number (из contracts.week_docs) — только если 11 цифр
        2. None — если нет валидного исходного номера

        НЕ извлекать номер из текста документа (raw_number)!

        Args:
            raw_number: Сырой номер закупки из LLM ответа (ИГНОРИРУЕТСЯ)
            source_number: Исходный номер госзакупки из contracts.week_docs

        Returns:
            Нормализованный номер (строка из 11 цифр) или None
        """
        # Используем только исходный номер из contracts.week_docs
        if source_number:
            source_str = str(source_number).strip()
            # Проверяем: ровно 11 цифр (формат 223-ФЗ)
            if re.match(r"^\d{11}$", source_str):
                return source_str
            # Если исходный номер не 11 цифр — не используем
            logger.debug(f"Source number is not 11 digits: {source_str}")

        # НЕ извлекаем номер из текста документа
        # raw_number игнорируется, чтобы избежать ошибок (внутренние номера, номера документов)
        return None

    def _parse_participant_status(self, status: str) -> ParticipantStatus:
        """Parse participant status string to enum."""
        if not status:
            return ParticipantStatus.NOT_FOUND
        status_map = {
            "winner": ParticipantStatus.WINNER,
            "single_participant": ParticipantStatus.SINGLE_PARTICIPANT,
            "admitted": ParticipantStatus.ADMITTED,
            "rejected": ParticipantStatus.REJECTED,
            "not_found": ParticipantStatus.NOT_FOUND,
        }
        return status_map.get(status.lower(), ParticipantStatus.NOT_FOUND)

    def _parse_procurement_status(self, status: str) -> ProcurementStatus:
        """Parse procurement status string to enum."""
        if not status:
            return ProcurementStatus.UNKNOWN
        status_map = {
            "completed": ProcurementStatus.COMPLETED,
            "not_held": ProcurementStatus.NOT_HELD,
            "cancelled": ProcurementStatus.CANCELLED,
            "unknown": ProcurementStatus.UNKNOWN,
        }
        return status_map.get(status.lower(), ProcurementStatus.UNKNOWN)

    def _parse_not_held_reason(self, reason: Optional[str]) -> Optional[NotHeldReason]:
        """Parse not held reason string to enum."""
        if not reason:
            return None
        reason_map = {
            "single_participant": NotHeldReason.SINGLE_PARTICIPANT,
            "no_applications": NotHeldReason.NO_APPLICATIONS,
            "all_rejected": NotHeldReason.ALL_REJECTED,
        }
        return reason_map.get(reason.lower())

    def _parse_document_type(self, doc_type: str) -> DocumentType:
        """
        Parse document type string to enum.

        NOTE: Legacy protocol types are mapped to delivery document types.
        """
        if not doc_type:
            return DocumentType.UNKNOWN
        type_map = {
            # Legacy types (protocol based)
            "итоговый_протокол": DocumentType.FINAL_PROTOCOL,
            "протокол_рассмотрения": DocumentType.CONSIDERATION_PROTOCOL,
            "протокол_подведения_итогов": DocumentType.RESULT_PROTOCOL,
            "протокол_аукциона": DocumentType.AUCTION_PROTOCOL,
            "протокол_запроса_цен": DocumentType.FINAL_PROTOCOL,  # Map to final
            # New types (delivery document based)
            "документ_о_поставке": DocumentType.OTHER,
            "акт_выполнения": DocumentType.OTHER,
            # Other types
            "техзадание": DocumentType.OTHER,
            "расчет_баллов": DocumentType.OTHER,
            "иное": DocumentType.OTHER,
        }
        return type_map.get(doc_type.lower(), DocumentType.UNKNOWN)
