"""FastAPI application entrypoint for LLM QA Service."""

import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.dependencies import init_services, shutdown_services
from api.routes import router
from config import get_settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup and shutdown."""
    # Startup
    settings = get_settings()
    logger.info(f"Starting LLM QA Service (debug={settings.DEBUG})")

    await init_services(settings)

    yield

    # Shutdown
    logger.info("Shutting down LLM QA Service")
    await shutdown_services()


# Create FastAPI application
app = FastAPI(
    title="LLM QA Service",
    description="Service for extracting winner information from procurement protocols using LLM",
    version="1.0.0",
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(router)


@app.get("/")
async def root():
    """Root endpoint with service info."""
    return {
        "service": "llm_qa_service",
        "version": "1.0.0",
        "description": "Winner extraction from procurement protocols",
        "docs": "/docs",
    }


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
