"""POST /api/legal-assistance, GET /api/legal-assistance/states."""

from fastapi import APIRouter, Depends

from app.api.deps import get_ai_service, get_web_search_service
from app.models.schemas import LegalAssistanceRequest, LegalAssistanceResponse, StatesResponse
from app.services import location_service
from app.services.ai.ai_service import AIService
from app.services.legal_assistance_service import get_legal_assistance
from app.services.web_search_service import WebSearchService

router = APIRouter(prefix="/api/legal-assistance", tags=["legal-assistance"])


@router.post("")
async def legal_assistance(
    request: LegalAssistanceRequest,
    ai_service: AIService = Depends(get_ai_service),
    web_search_service: WebSearchService = Depends(get_web_search_service),
) -> LegalAssistanceResponse:
    """Advocate + legal-aid lookup. Should only be called after the user clicks
    "Find Legal Assistance" in response to /api/chat flagging professional help
    may be appropriate — the district/state prompt belongs on the frontend here,
    never inside the /chat flow."""
    return await get_legal_assistance(request, ai_service=ai_service, web_search_service=web_search_service)


@router.get("/states")
async def states() -> StatesResponse:
    """States/UTs list for a frontend dropdown."""
    return StatesResponse(
        states=location_service.all_states(),
        union_territories=location_service.all_union_territories(),
    )
