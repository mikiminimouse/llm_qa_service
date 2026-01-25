"""LLM client factory."""

from domain.interfaces.llm_client import ILLMClient

from .glm47_client import GLM47Client


def create_llm_client(
    provider: str = "zhipu",
    api_key: str = "",
    base_url: str = "https://open.bigmodel.cn/api/paas/v4",
    model: str = "glm-4-flash",
    timeout: float = 60.0,
    max_retries: int = 3,
    retry_delay: float = 1.0,
) -> ILLMClient:
    """
    Create LLM client based on provider.

    Args:
        provider: LLM provider name (currently only 'zhipu' supported).
        api_key: API key for the provider.
        base_url: API base URL.
        model: Model name.
        timeout: Request timeout.
        max_retries: Maximum retries for failed requests.
        retry_delay: Base delay between retries.

    Returns:
        ILLMClient implementation.

    Raises:
        ValueError: If provider is not supported.
    """
    if provider == "zhipu" or provider == "glm":
        return GLM47Client(
            api_key=api_key,
            base_url=base_url,
            model=model,
            timeout=timeout,
            max_retries=max_retries,
            retry_delay=retry_delay,
        )
    else:
        raise ValueError(f"Unsupported LLM provider: {provider}")
