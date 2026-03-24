"""FastAPI dependencies for dependency injection."""

import logging
from functools import lru_cache
from typing import Union

from application.orchestrator import QAOrchestrator
from config import Settings, get_settings
from domain.interfaces.context_loader import IContextLoader
from domain.interfaces.qa_repository import IQARepository
from infrastructure.llm import create_llm_client
from infrastructure.loaders import MongoContextLoader
from infrastructure.prompt_manager import PromptManager
from infrastructure.repositories import MongoQARepository

# PostgreSQL импорты (для миграции)
try:
    from infrastructure.loaders import PostgresContextLoader
    from infrastructure.repositories import PostgresQARepository, is_postgresql_enabled
    _POSTGRESQL_AVAILABLE = True
except ImportError:
    _POSTGRESQL_AVAILABLE = False
    PostgresContextLoader = None  # type: ignore
    PostgresQARepository = None  # type: ignore
    is_postgresql_enabled = lambda: False

logger = logging.getLogger(__name__)

# Global instances (initialized during lifespan)
_orchestrator: QAOrchestrator | None = None
_context_loader: Union[MongoContextLoader, PostgresContextLoader, None] = None
_repository: Union[MongoQARepository, PostgresQARepository, None] = None


async def init_services(settings: Settings) -> None:
    """Initialize all services during app startup."""
    global _orchestrator, _context_loader, _repository

    logger.info("Initializing services...")

    # Determine data source: MongoDB or PostgreSQL
    use_postgresql = settings.USE_POSTGRESQL_SOURCE and _POSTGRESQL_AVAILABLE and is_postgresql_enabled()

    if use_postgresql:
        logger.info("Using PostgreSQL as data source (migration mode)")
        # Create PostgreSQL context loader and repository
        _context_loader = PostgresContextLoader(
            dsn=None,  # Will use environment variables
            pool_size=10,
        )
        _repository = PostgresQARepository(
            dsn=None,  # Will use environment variables
            pool_size=10,
        )
    else:
        logger.info("Using MongoDB as data source")
        # Create MongoDB context loader and repository
        _context_loader = MongoContextLoader(
            mongo_uri=settings.MONGO_URI,
            database=settings.MONGO_DATABASE,
            collection=settings.MONGO_PROTOCOLS_COLLECTION,
        )
        _repository = MongoQARepository(
            mongo_uri=settings.MONGO_URI,
            database=settings.MONGO_DATABASE,
            collection=settings.MONGO_QA_COLLECTION,
        )

    # Create LLM client
    llm_client = create_llm_client(
        provider="zhipu",
        api_key=settings.GLM_API_KEY,
        base_url=settings.GLM_BASE_URL,
        model=settings.GLM_MODEL,
        timeout=settings.GLM_TIMEOUT,
        max_retries=settings.GLM_MAX_RETRIES,
        retry_delay=settings.GLM_RETRY_DELAY,
    )

    # Create prompt manager
    prompt_manager = PromptManager(prompts_dir=settings.PROMPTS_DIR)

    # Create orchestrator (simplified, without post-processor)
    _orchestrator = QAOrchestrator(
        llm_client=llm_client,
        context_loader=_context_loader,
        repository=_repository,
        prompt_manager=prompt_manager,
        skip_processed=settings.SKIP_PROCESSED,
        max_tokens=settings.GLM_MAX_TOKENS,
        temperature=settings.GLM_TEMPERATURE,
        save_to_unit_dir=settings.SAVE_TO_UNIT_DIR,
        unit_base_paths=settings.UNIT_BASE_PATHS,
    )

    logger.info("Services initialized successfully")


async def shutdown_services() -> None:
    """Cleanup services during app shutdown."""
    global _orchestrator, _context_loader, _repository

    logger.info("Shutting down services...")

    if _orchestrator and _orchestrator.llm_client:
        await _orchestrator.llm_client.close()

    if _context_loader:
        await _context_loader.close()

    if _repository:
        await _repository.close()

    _orchestrator = None
    _context_loader = None
    _repository = None

    logger.info("Services shut down")


def get_orchestrator() -> QAOrchestrator:
    """Get the QA orchestrator instance."""
    if _orchestrator is None:
        raise RuntimeError("Orchestrator not initialized. Call init_services first.")
    return _orchestrator


def get_context_loader() -> IContextLoader:
    """Get the context loader instance."""
    if _context_loader is None:
        raise RuntimeError("Context loader not initialized. Call init_services first.")
    return _context_loader


def get_repository() -> IQARepository:
    """Get the repository instance."""
    if _repository is None:
        raise RuntimeError("Repository not initialized. Call init_services first.")
    return _repository
