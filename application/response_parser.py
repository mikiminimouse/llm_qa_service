"""Parser for LLM responses to extract structured data."""

import json
import logging
import re
from typing import Optional, Tuple

from pydantic import ValidationError

from domain.entities import WinnerExtractionResultV2
from domain.entities.enums import DocumentType, NotHeldReason, ParticipantStatus, ProcurementStatus
from domain.entities.extraction_components import CustomerInfo, DocumentInfo, ExtractionFlags, ProcurementInfo
from domain.entities.winner import OtherParticipant, WinnerInfo

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
    JSON_OBJECT_PATTERN = re.compile(r"\{.*\}", re.DOTALL)

    def parse(self, response: str) -> Tuple[WinnerExtractionResultV2, str]:
        """
        Parse LLM response to WinnerExtractionResultV2.

        Args:
            response: Raw LLM response text.

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
            result = self._transform_to_result(data)
            return result, json_str
        except ValidationError as e:
            raise ResponseParseError(f"Validation error: {e}")

    def _extract_json(self, text: str) -> Optional[str]:
        """
        Extract JSON from response text.

        Tries multiple strategies:
        1. Look for ```json blocks
        2. Look for raw JSON object
        """
        # Try markdown code block first
        match = self.JSON_BLOCK_PATTERN.search(text)
        if match:
            return match.group(1).strip()

        # Try raw JSON object
        match = self.JSON_OBJECT_PATTERN.search(text)
        if match:
            return match.group(0).strip()

        return None

    def _transform_to_result(self, data: dict) -> WinnerExtractionResultV2:
        """
        Transform LLM JSON output to WinnerExtractionResultV2.

        Args:
            data: Parsed JSON dictionary.

        Returns:
            WinnerExtractionResultV2 model.
        """
        # Extract winners
        winners = []
        for w in data.get("winners", []):
            winner = WinnerInfo(
                name=w.get("name", "Unknown"),
                inn=w.get("inn"),
                kpp=w.get("kpp"),
                ogrn=w.get("ogrn"),
                address=w.get("address"),
                contract_price=self._parse_price(w.get("contract_price")),
                status=self._parse_participant_status(w.get("status", "winner")),
                confidence=w.get("confidence", 1.0),
            )
            winners.append(winner)

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
        procurement = ProcurementInfo(
            purchase_number=procurement_data.get("number"),
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
            winners=winners,
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

    def _parse_participant_status(self, status: str) -> ParticipantStatus:
        """Parse participant status string to enum."""
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
        """Parse document type string to enum."""
        type_map = {
            "итоговый_протокол": DocumentType.FINAL_PROTOCOL,
            "протокол_рассмотрения": DocumentType.CONSIDERATION_PROTOCOL,
            "протокол_подведения_итогов": DocumentType.RESULT_PROTOCOL,
            "протокол_аукциона": DocumentType.AUCTION_PROTOCOL,
            "протокол_запроса_цен": DocumentType.FINAL_PROTOCOL,  # Map to final
            "техзадание": DocumentType.OTHER,
            "расчет_баллов": DocumentType.OTHER,
            "иное": DocumentType.OTHER,
        }
        return type_map.get(doc_type.lower(), DocumentType.UNKNOWN)
