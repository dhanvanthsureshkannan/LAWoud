"""Orchestrates the /legal-assistance flow: location resolution, advocate
discovery, and legal-aid fallback. Never fabricates — an empty result stays
empty, with legal-aid contacts and a manual-search link offered instead.
"""

import json
import logging

from app.config import PROJECT_ROOT
from app.core.domains import ECOURTS_ADVOCATE_SEARCH_URL
from app.core.wording import NO_RESULTS_DISCLAIMER, STANDARD_DISCLAIMER, assert_clean
from app.models.schemas import (
    LegalAidResource,
    LegalAssistanceRequest,
    LegalAssistanceResponse,
    MatchScope,
)
from app.services import location_service
from app.services.advocate_service import find_advocates
from app.services.ai.ai_service import AIService
from app.services.web_search_service import WebSearchService

logger = logging.getLogger("lawoud.legal_assistance_service")

_LEGAL_AID_PATH = PROJECT_ROOT / "data" / "legal_aid_directory.json"


def _load_national_legal_aid() -> list[LegalAidResource]:
    with open(_LEGAL_AID_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return [LegalAidResource(**item) for item in data.get("national", [])]


async def get_legal_assistance(
    request: LegalAssistanceRequest,
    *,
    ai_service: AIService,
    web_search_service: WebSearchService,
) -> LegalAssistanceResponse:
    legal_aid = _load_national_legal_aid()

    # Users type locations inconsistently ("vellore ", "tamilnadu"), so tidy the
    # input before matching or displaying it.
    district = request.district.strip().title()

    # --- Location resolution -------------------------------------------
    state = None
    if request.state and request.state.strip():
        state = location_service.resolve_state(request.state)
        if state is None:
            candidates = location_service.ambiguous_candidates(district) or []
            return LegalAssistanceResponse(
                legal_topic=request.legal_topic,
                location=district,
                match_scope=MatchScope.NONE,
                advocate_data_available=False,
                legal_aid=legal_aid,
                disclaimer=NO_RESULTS_DISCLAIMER,
                reason=(
                    f"'{request.state.strip()}' is not a recognized Indian state or "
                    "union territory. Please pick one from the list."
                ),
                state_required=True,
                candidate_states=candidates or location_service.all_state_names(),
            )

    if not state:
        inferred, candidates = await location_service.infer_state(ai_service, district)
        if inferred:
            state = inferred
        else:
            return LegalAssistanceResponse(
                legal_topic=request.legal_topic,
                location=district,
                match_scope=MatchScope.NONE,
                advocate_data_available=False,
                legal_aid=legal_aid,
                disclaimer=NO_RESULTS_DISCLAIMER,
                reason=(
                    "This district exists in more than one state — please specify the state."
                    if candidates
                    else "Could not determine the state for this district — please specify it."
                ),
                state_required=True,
                candidate_states=candidates,
            )

    location_label = f"{district}, {state}"

    # --- Advocate discovery (progressive widening) -----------------------
    results, match_scope = await find_advocates(
        web_search_service,
        district=district,
        state=state,
        legal_category=request.legal_category,
        case_type=request.case_type,
    )

    for result in results:
        assert_clean(result.relevance_reason)

    if results:
        return LegalAssistanceResponse(
            legal_topic=request.legal_topic,
            location=location_label,
            match_scope=match_scope,
            advocate_data_available=True,
            results=results,
            legal_aid=legal_aid,
            disclaimer=STANDARD_DISCLAIMER,
        )

    # --- Never fabricate: no advocates found at any search tier -----------
    reason = (
        "No publicly available judicial records could be found matching this district and "
        "legal category. This does not mean no relevant advocates exist locally — it means "
        "our search of publicly indexed sources did not surface any. Please use official "
        "legal-aid contacts below, or complete a manual search on the official eCourts portal "
        "(requires solving a CAPTCHA there, which we cannot do on your behalf)."
    )
    return LegalAssistanceResponse(
        legal_topic=request.legal_topic,
        location=location_label,
        match_scope=MatchScope.NONE,
        advocate_data_available=False,
        legal_aid=legal_aid,
        disclaimer=NO_RESULTS_DISCLAIMER,
        reason=reason,
        manual_search_url=ECOURTS_ADVOCATE_SEARCH_URL,
    )
