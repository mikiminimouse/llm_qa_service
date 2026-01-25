"""Abstract interface for LLM clients."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class LLMResponse:
    """Response from LLM."""

    content: str
    model: str
    usage: dict
    finish_reason: str
    raw_response: Optional[dict] = None


class ILLMClient(ABC):
    """Abstract interface for LLM clients."""

    @abstractmethod
    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> LLMResponse:
        """Generate response from LLM.

        Args:
            system_prompt: System message for the LLM.
            user_prompt: User message/query.
            max_tokens: Maximum tokens in response.
            temperature: Sampling temperature.

        Returns:
            LLMResponse with generated content.

        Raises:
            LLMError: If generation fails.
        """
        pass

    @abstractmethod
    async def close(self) -> None:
        """Close client connections."""
        pass
