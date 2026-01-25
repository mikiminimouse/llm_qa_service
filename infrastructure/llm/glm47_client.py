"""GLM-4.7 LLM client implementation via Z.ai proxy."""

import asyncio
import logging
import time
from typing import Optional

import httpx

from domain.interfaces.llm_client import ILLMClient, LLMResponse

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """Base exception for LLM errors."""

    pass


class GLM47Client(ILLMClient):
    """
    Client for GLM-4.7 via Z.ai proxy.

    API is OpenAI-compatible, using standard chat completions format.
    Default endpoint: https://api.z.ai/api/coding/paas/v4/chat/completions
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.z.ai/api/coding/paas/v4",
        model: str = "GLM-4.7",
        timeout: float = 60.0,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ):
        """
        Initialize GLM-4.7 client.

        Args:
            api_key: Z.ai API key.
            base_url: API base URL (without trailing slash).
            model: Model name (glm-4.7 for Z.ai).
            timeout: Request timeout in seconds.
            max_retries: Maximum number of retries for failed requests.
            retry_delay: Base delay between retries (uses exponential backoff).
        """
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )

    @property
    def provider_name(self) -> str:
        """Get provider name."""
        return "zhipu"

    @property
    def model_name(self) -> str:
        """Get model name."""
        return self._model

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> LLMResponse:
        """
        Generate response from GLM-4.7.

        Args:
            system_prompt: System message for the LLM.
            user_prompt: User message/query.
            max_tokens: Maximum tokens in response (default: 4096).
            temperature: Sampling temperature (default: 0.1).

        Returns:
            LLMResponse with generated content.

        Raises:
            LLMError: If generation fails after all retries.
        """
        url = f"{self.base_url}/chat/completions"

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature if temperature is not None else 0.1,
            "max_tokens": max_tokens if max_tokens is not None else 4096,
        }

        start_time = time.time()
        last_error: Optional[Exception] = None

        for attempt in range(self.max_retries):
            try:
                response = await self._client.post(url, json=payload)

                # Handle rate limiting with retry
                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", self.retry_delay * (2**attempt)))
                    logger.warning(f"Rate limited, waiting {retry_after}s (attempt {attempt + 1})")
                    await asyncio.sleep(retry_after)
                    continue

                # Handle server errors with retry
                if response.status_code >= 500:
                    logger.warning(f"Server error {response.status_code} (attempt {attempt + 1})")
                    await asyncio.sleep(self.retry_delay * (2**attempt))
                    continue

                response.raise_for_status()

                data = response.json()

                # Handle Z.ai proxy errors (HTTP 200 with error in JSON)
                if data.get("success") is False or data.get("code"):
                    error_msg = data.get("msg") or data.get("error", {}).get("message", "Unknown error")
                    error_code = data.get("code") or data.get("error", {}).get("code", "unknown")
                    logger.error(f"API error (code={error_code}): {error_msg}")
                    raise LLMError(f"API error (code={error_code}): {error_msg}")

                latency_ms = (time.time() - start_time) * 1000

                return LLMResponse(
                    content=data["choices"][0]["message"]["content"],
                    model=data.get("model", self._model),
                    usage={
                        "prompt_tokens": data.get("usage", {}).get("prompt_tokens", 0),
                        "completion_tokens": data.get("usage", {}).get("completion_tokens", 0),
                        "total_tokens": data.get("usage", {}).get("total_tokens", 0),
                    },
                    finish_reason=data["choices"][0].get("finish_reason", "unknown"),
                    raw_response=data,
                )

            except httpx.HTTPStatusError as e:
                last_error = e
                logger.warning(f"HTTP error {e.response.status_code} (attempt {attempt + 1}): {e}")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay * (2**attempt))

            except httpx.TimeoutException as e:
                last_error = e
                logger.warning(f"Timeout (attempt {attempt + 1})")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay * (2**attempt))

            except Exception as e:
                last_error = e
                logger.error(f"Unexpected error (attempt {attempt + 1}): {e}")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay * (2**attempt))

        raise LLMError(f"Failed after {self.max_retries} attempts: {last_error}")

    async def health_check(self) -> bool:
        """Check API availability."""
        try:
            await self.generate(
                system_prompt="",
                user_prompt="ping",
                max_tokens=5,
            )
            return True
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False

    async def close(self) -> None:
        """Close HTTP client."""
        await self._client.aclose()
