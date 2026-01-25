"""Validator for extraction results."""

import logging
import re
from dataclasses import dataclass
from typing import List, Optional

from domain.entities import WinnerExtractionResultV2

logger = logging.getLogger(__name__)


@dataclass
class ValidationIssue:
    """Validation issue found in result."""

    level: str  # "error", "warning", "info"
    code: str
    message: str
    field: Optional[str] = None


class ResultValidator:
    """
    Validator for winner extraction results.

    Performs consistency checks and detects common errors
    like confusing customer with winner.
    """

    # Markers in winner name that indicate it might be customer (not winner)
    CUSTOMER_MARKERS = [
        r"сведения об организаторе",
        r"сведения о заказчике",
        r"организатор закупки",
        r"контактная информация заказчика",
    ]

    # Budget institution prefixes - usually customers, not winners
    BUDGET_INSTITUTION_PREFIXES = [
        r"^МАДОУ\b",
        r"^МАОУ\b",
        r"^МБОУ\b",
        r"^МКОУ\b",
        r"^МБУ\b",
        r"^МКУ\b",
        r"^ГАУ\b",
        r"^ГБУ\b",
        r"^ГБОУ\b",
        r"^ОГБОУ\b",
        r"^ОГБПОУ\b",
        r"^КГБУ\b",
        r"^Администрация\b",
        r"^Управление\b",
        r"^Департамент\b",
        r"^Министерство\b",
    ]

    # Markers that indicate ETP operator (not winner)
    OPERATOR_MARKERS = [
        r"ТОРГИ-ОНЛАЙН",
        r"Сбербанк-АСТ",
        r"РТС-тендер",
        r"оператор электронной площадки",
        r"техническая поддержка",
        r"ЕЭТП",
        r"Росэлторг",
    ]

    def __init__(self, rules: Optional[dict] = None):
        """
        Initialize validator.

        Args:
            rules: Optional validation rules from YAML.
        """
        self.rules = rules or {}

    def validate(
        self,
        result: WinnerExtractionResultV2,
        document_content: Optional[str] = None,
    ) -> List[ValidationIssue]:
        """
        Validate extraction result.

        Args:
            result: Extraction result to validate.
            document_content: Optional document content for cross-checking.

        Returns:
            List of validation issues.
        """
        issues: List[ValidationIssue] = []

        # Check winner_found consistency
        issues.extend(self._check_winner_consistency(result))

        # Check for customer confusion
        issues.extend(self._check_customer_confusion(result, document_content))

        # Check data quality
        issues.extend(self._check_data_quality(result))

        return issues

    def _check_winner_consistency(self, result: WinnerExtractionResultV2) -> List[ValidationIssue]:
        """Check consistency between winner_found and winners list."""
        issues = []

        if result.winner_found and not result.winners:
            issues.append(
                ValidationIssue(
                    level="warning",
                    code="WINNER_FOUND_NO_DATA",
                    message="winner_found is True but no winners in list",
                )
            )

        if not result.winner_found and result.winners:
            issues.append(
                ValidationIssue(
                    level="warning",
                    code="WINNER_DATA_FOUND_FALSE",
                    message="Winners in list but winner_found is False",
                )
            )

        return issues

    def _check_customer_confusion(
        self,
        result: WinnerExtractionResultV2,
        document_content: Optional[str],
    ) -> List[ValidationIssue]:
        """Check if winner might be confused with customer."""
        issues = []

        if not result.winners:
            return issues

        for winner in result.winners:
            # Check winner name against customer markers
            for marker in self.CUSTOMER_MARKERS:
                if re.search(marker, winner.name, re.IGNORECASE):
                    issues.append(
                        ValidationIssue(
                            level="warning",
                            code="POSSIBLE_CUSTOMER_CONFUSION",
                            message=f"Winner '{winner.name}' matches customer marker: {marker}",
                            field="winners[].name",
                        )
                    )
                    result.flags.customer_confused_with_winner = True
                    break

            # Check if winner is a budget institution (usually customers)
            for prefix in self.BUDGET_INSTITUTION_PREFIXES:
                if re.search(prefix, winner.name, re.IGNORECASE):
                    issues.append(
                        ValidationIssue(
                            level="warning",
                            code="BUDGET_INSTITUTION_AS_WINNER",
                            message=f"Winner '{winner.name}' appears to be a budget institution (usually customer)",
                            field="winners[].name",
                        )
                    )
                    result.flags.customer_confused_with_winner = True
                    break

            # Check against operator markers
            for marker in self.OPERATOR_MARKERS:
                if re.search(marker, winner.name, re.IGNORECASE):
                    issues.append(
                        ValidationIssue(
                            level="error",
                            code="OPERATOR_AS_WINNER",
                            message=f"Winner '{winner.name}' matches operator marker: {marker}",
                            field="winners[].name",
                        )
                    )
                    break

            # If document content provided, check if winner INN appears in customer section
            if document_content and winner.inn:
                self._check_inn_in_customer_section(winner.inn, document_content, issues)

        # Check if winner INN matches customer INN (critical error)
        if result.customer and result.customer.inn:
            for winner in result.winners:
                if winner.inn and winner.inn == result.customer.inn:
                    issues.append(
                        ValidationIssue(
                            level="error",
                            code="WINNER_INN_EQUALS_CUSTOMER_INN",
                            message=f"Winner INN {winner.inn} equals customer INN - likely confusion!",
                            field="winners[].inn",
                        )
                    )
                    result.flags.customer_confused_with_winner = True

        return issues

    def _check_inn_in_customer_section(
        self,
        inn: str,
        document_content: str,
        issues: List[ValidationIssue],
    ) -> None:
        """Check if INN appears in customer section of document."""
        # Look for customer section
        customer_section_match = re.search(
            r"(сведения о[б]? заказчик[еа]|сведения о[б]? организатор[еа]).{0,2000}",
            document_content,
            re.IGNORECASE | re.DOTALL,
        )

        if customer_section_match:
            section = customer_section_match.group(0)
            if inn in section:
                issues.append(
                    ValidationIssue(
                        level="warning",
                        code="INN_IN_CUSTOMER_SECTION",
                        message=f"Winner INN {inn} appears in customer section",
                        field="winners[].inn",
                    )
                )

    def _check_data_quality(self, result: WinnerExtractionResultV2) -> List[ValidationIssue]:
        """Check data quality of extraction result."""
        issues = []

        for i, winner in enumerate(result.winners):
            # Check INN format
            if winner.inn:
                if not re.match(r"^\d{10}$|^\d{12}$", winner.inn):
                    issues.append(
                        ValidationIssue(
                            level="warning",
                            code="INVALID_INN_FORMAT",
                            message=f"INN '{winner.inn}' has invalid format (should be 10 or 12 digits)",
                            field=f"winners[{i}].inn",
                        )
                    )

            # Check name is not too short
            if len(winner.name) < 5:
                issues.append(
                    ValidationIssue(
                        level="warning",
                        code="SHORT_NAME",
                        message=f"Winner name '{winner.name}' is suspiciously short",
                        field=f"winners[{i}].name",
                    )
                )

        # Check reasoning
        if not result.reasoning:
            issues.append(
                ValidationIssue(
                    level="info",
                    code="NO_REASONING",
                    message="No reasoning provided by LLM",
                )
            )

        return issues

    def has_errors(self, issues: List[ValidationIssue]) -> bool:
        """Check if any issues are errors."""
        return any(issue.level == "error" for issue in issues)

    def has_warnings(self, issues: List[ValidationIssue]) -> bool:
        """Check if any issues are warnings."""
        return any(issue.level == "warning" for issue in issues)
