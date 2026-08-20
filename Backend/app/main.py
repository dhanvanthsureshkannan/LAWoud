"""LAWoud backend entrypoint. Run with: uvicorn app.main:app --reload"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import chat, health, legal_assistance
from app.config import settings
from app.services.ai.ai_service import AIService
from app.services.knowledge_service import KnowledgeService
from app.services.lawyer_directory_service import LawyerDirectoryService
from app.services.session_store import SessionStore
from app.services.web_search_service import WebSearchService

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger("lawoud.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting LAWoud backend...")
    app.state.ai_service = AIService(settings)
    app.state.knowledge_service = KnowledgeService(settings)
    app.state.web_search_service = WebSearchService(settings)
    app.state.lawyer_directory_service = LawyerDirectoryService(settings.lawyer_directory_path)
    app.state.session_store = SessionStore()

    logger.info("AI providers configured: %s", app.state.ai_service.configured_providers or "NONE")
    logger.info("Tavily configured: %s", settings.has_tavily)
    logger.info(
        "Knowledge base: %d sections loaded from %s",
        app.state.knowledge_service.section_count,
        app.state.knowledge_service.file_paths,
    )
    logger.info(
        "Lawyer directory: %d entries loaded from %s",
        app.state.lawyer_directory_service.entry_count,
        settings.lawyer_directory_path,
    )
    if not app.state.ai_service.configured_providers:
        logger.warning(
            "No AI provider is configured — set GEMINI_API_KEY and/or GROQ_API_KEY in .env. "
            "The server will still start, but /api/chat will fail on analysis/generation."
        )

    yield
    logger.info("Shutting down LAWoud backend.")


app = FastAPI(
    title="LAWoud API",
    description=(
        "Backend for LAWoud — an AI-powered legal assistance assistant for Indian law. "
        "Retrieval-gated: answers are generated only from a local curated Markdown knowledge "
        "base or whitelisted official web sources, never from unsupported model knowledge."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router)
app.include_router(legal_assistance.router)
app.include_router(health.router)


@app.get("/")
async def root() -> dict:
    return {
        "name": "LAWoud API",
        "docs": "/docs",
        "endpoints": [
            "POST /api/chat",
            "GET /api/chat/stream",
            "POST /api/chat/sync",
            "POST /api/legal-assistance",
            "GET /api/legal-assistance/states",
            "GET /api/health",
            "GET /api/knowledge/status",
        ],
    }
