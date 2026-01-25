"""Domain interfaces (abstract base classes)."""

from .context_loader import DocumentContext, IContextLoader
from .llm_client import ILLMClient, LLMResponse
from .qa_repository import IQARepository

__all__ = [
    "ILLMClient",
    "LLMResponse",
    "IContextLoader",
    "DocumentContext",
    "IQARepository",
]
