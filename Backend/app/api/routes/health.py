"""GET /api/health, GET /api/knowledge/status."""

from fastapi import APIRouter, Depends

from app.api.deps import get_knowledge_service
from app.config import settings
from app.models.schemas import HealthResponse, KnowledgeStatusResponse
from app.services.knowledge_service import KnowledgeService

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        gemini_configured=settings.has_gemini,
        groq_configured=settings.has_groq,
        tavily_configured=settings.has_tavily,
    )


@router.get("/knowledge/status")
async def knowledge_status(
    knowledge_service: KnowledgeService = Depends(get_knowledge_service),
) -> KnowledgeStatusResponse:
    """Debug aid while swapping in the real knowledge .md file."""
    knowledge_service.reload_if_changed()
    return KnowledgeStatusResponse(
        file_path=str(settings.constitution_path),
        exists=knowledge_service.file_exists,
        section_count=knowledge_service.section_count,
        last_loaded=knowledge_service.last_loaded.isoformat() if knowledge_service.last_loaded else None,
        last_modified=knowledge_service.file_mtime.isoformat() if knowledge_service.file_mtime else None,
        file_paths=knowledge_service.file_paths,
        section_counts=knowledge_service.section_counts,
    )
