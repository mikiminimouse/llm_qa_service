"""Tests for response parser."""

import pytest

from application.response_parser import ResponseParser, ResponseParseError


class TestResponseParser:
    """Tests for ResponseParser."""

    @pytest.fixture
    def parser(self):
        """Create parser instance."""
        return ResponseParser()

    def test_parse_json_block(self, parser):
        """Test parsing JSON from markdown code block."""
        response = """
Here is the extracted data:

```json
{
    "winner_found": true,
    "winners": [
        {
            "name": "ООО Тест",
            "inn": "1234567890"
        }
    ],
    "procurement_info": {
        "status": "completed"
    },
    "document_info": {
        "type": "итоговый_протокол"
    },
    "reasoning": "Победитель определён"
}
```
"""
        result, raw_json = parser.parse(response)
        assert result.winner_found is True
        assert len(result.winners) == 1
        assert result.winners[0].name == "ООО Тест"

    def test_parse_raw_json(self, parser):
        """Test parsing raw JSON without code block."""
        response = """
{
    "winner_found": false,
    "winners": [],
    "procurement_info": {
        "status": "not_held",
        "not_held_reason": "no_applications"
    },
    "document_info": {
        "type": "протокол_рассмотрения",
        "is_service_file": false
    },
    "reasoning": "Заявки не поступили"
}
"""
        result, raw_json = parser.parse(response)
        assert result.winner_found is False
        assert len(result.winners) == 0

    def test_parse_with_text_around_json(self, parser):
        """Test parsing JSON surrounded by text."""
        response = """
После анализа документа я извлёк следующую информацию:

{"winner_found": true, "winners": [{"name": "ИП Иванов", "inn": "123456789012"}], "procurement_info": {"status": "completed"}, "document_info": {"type": "итоговый_протокол"}, "reasoning": "Найден победитель"}

Надеюсь, это поможет!
"""
        result, raw_json = parser.parse(response)
        assert result.winner_found is True
        assert result.winners[0].name == "ИП Иванов"

    def test_parse_no_json(self, parser):
        """Test error when no JSON found."""
        response = "Это просто текст без JSON"
        with pytest.raises(ResponseParseError, match="No JSON found"):
            parser.parse(response)

    def test_parse_invalid_json(self, parser):
        """Test error on invalid JSON."""
        response = '{"winner_found": true, "invalid": }'
        with pytest.raises(ResponseParseError, match="Invalid JSON"):
            parser.parse(response)

    def test_parse_price_string(self, parser):
        """Test parsing price from string."""
        response = """
{
    "winner_found": true,
    "winners": [
        {
            "name": "ООО Тест",
            "contract_price": "245 890.00 руб."
        }
    ],
    "procurement_info": {"status": "completed"},
    "document_info": {"type": "итоговый_протокол"},
    "reasoning": "Тест"
}
"""
        result, _ = parser.parse(response)
        assert result.winners[0].contract_price == 245890.0

    def test_parse_single_participant(self, parser):
        """Test parsing single participant winner."""
        response = """
{
    "winner_found": true,
    "winners": [
        {
            "name": "Единственный участник ООО",
            "status": "single_participant"
        }
    ],
    "procurement_info": {
        "status": "not_held",
        "not_held_reason": "single_participant"
    },
    "flags": {
        "is_single_participant_winner": true,
        "procurement_not_held_but_winner_exists": true
    },
    "document_info": {"type": "протокол_рассмотрения"},
    "reasoning": "Единственный участник признан победителем"
}
"""
        result, _ = parser.parse(response)
        assert result.winner_found is True
        assert result.flags.single_participant is True

    def test_parse_service_file(self, parser):
        """Test parsing service file detection."""
        response = """
{
    "winner_found": false,
    "winners": [],
    "procurement_info": {"status": "unknown"},
    "document_info": {
        "type": "техзадание",
        "is_service_file": true
    },
    "reasoning": "Это техническое задание, не протокол"
}
"""
        result, _ = parser.parse(response)
        assert result.winner_found is False
        assert result.flags.is_service_file is True
