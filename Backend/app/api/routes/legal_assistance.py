"""POST /api/legal-assistance, GET /api/legal-assistance/states."""

from fastapi import APIRouter, Depends

from app.api.deps import get_ai_service, get_lawyer_directory_service, get_web_search_service
from app.models.schemas import LegalAssistanceRequest, LegalAssistanceResponse, StatesResponse
from app.services import location_service
from app.services.ai.ai_service import AIService
from app.services.lawyer_directory_service import LawyerDirectoryService
from app.services.legal_assistance_service import get_legal_assistance
from app.services.web_search_service import WebSearchService

router = APIRouter(prefix="/api/legal-assistance", tags=["legal-assistance"])


@router.post("")
async def legal_assistance(
    request: LegalAssistanceRequest,
    ai_service: AIService = Depends(get_ai_service),
    web_search_service: WebSearchService = Depends(get_web_search_service),
    lawyer_directory_service: LawyerDirectoryService = Depends(get_lawyer_directory_service),
) -> LegalAssistanceResponse:
    """Advocate + legal-aid lookup, callable standalone (e.g. a "Find Legal
    Assistance" button) with an explicit district/state. The chat flow reaches
    the same `get_legal_assistance` logic inline, from `orchestrator.py`'s
    AWAITING_LOCATION phase, once it has parsed a district/state out of the
    user's chat message — the two paths share this one implementation so they
    can never drift apart."""
    return await get_legal_assistance(
        request,
        ai_service=ai_service,
        web_search_service=web_search_service,
        lawyer_directory_service=lawyer_directory_service,
    )


@router.get("/states")
async def states() -> StatesResponse:
    """States/UTs list for a frontend dropdown."""
    return StatesResponse(
        states=location_service.all_states(),
        union_territories=location_service.all_union_territories(),
    )
