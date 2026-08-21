"""The /chat pipeline as a single async generator of typed events.

Both the SSE route and the /chat/sync route drain this same generator, so they
cannot drift apart: SSE serializes each event to the wire as it arrives,
/sync collects them into one JSON body.

Phase-aware: each turn dispatches on the conversation's current phase rather
than always running the same five stages. A brand-new question starts in
INTAKE, where the assistant may ask one clarifying question per turn before it
has enough to answer; once it does, the SAME request falls through into
ANSWERING so the user isn't kept waiting on an extra round trip for the turn
that finally has enough context. If the answer flags that professional help
may be warranted, the assistant appends an inline request for the user's
district/state and the conversation moves to AWAITING_LOCATION, where the
user's next message is parsed as a location rather than a new question.
"""

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from app.core.prompts import LOCATION_REQUEST_MESSAGE, build_history_text
from app.core.text import keywords as extract_keywords
from app.core.wording import NO_RESULTS_DISCLAIMER
from app.models.schemas import (
    Awaiting,
    ChatRequest,
    Citation,
    ConversationPhase,
    LegalAssistanceRequest,
    LegalAssistanceResponse,
    MatchScope,
    Origin,
    ProviderName,
    ProvidersUsed,
    QueryAnalysis,
    Route,
    Stage,
)
from app.services import location_service
from app.services.ai.ai_service import AIService
from app.services.answer_service import AnswerStreamError, stream_answer
from app.services.assessment_service import assess_professional_help
from app.services.citation_service import (
    citations_from_knowledge,
    citations_from_web,
    context_blocks_from_knowledge,
    context_blocks_from_web,
)
from app.services.intake_service import run_intake_turn, wants_to_skip
from app.services.knowledge_service import KnowledgeService
from app.services.lawyer_directory_service import LawyerDirectoryService
from app.services.legal_assistance_service import get_legal_assistance, load_national_legal_aid
from app.services.session_store import ConversationState, SessionStore
from app.services.web_search_service import WebSearchService

logger = logging.getLogger("lawoud.orchestrator")


@dataclass
class PipelineEvent:
    event: str  # "status" | "analysis" | "sources" | "chunk" | "question" | "assistance" | "done" | "error"
    data: dict[str, Any]


async def run(
    request: ChatRequest,
    *,
    ai_service: AIService,
    knowledge_service: KnowledgeService,
    web_search_service: WebSearchService,
    lawyer_directory_service: LawyerDirectoryService,
    session_store: SessionStore,
) -> AsyncIterator[PipelineEvent]:
    history = [h.model_dump() for h in request.history] if request.history else None

    state = session_store.get_or_create(request.conversation_id, request.question)

    # A conversation that already delivered an answer (or assistance) and is
    # back in INTAKE with no pending question is being handed a NEW topic, not
    # a reply — start that topic fresh rather than dragging the old slots and
    # asked-questions list into it.
    is_new_topic = (
        state.phase == ConversationPhase.INTAKE
        and not state.pending_slot_key
        and state.analysis is not None
    )
    if is_new_topic and wants_to_skip(request.question):
        # A content-free message right after a completed topic ("skip", "ok",
        # a blank send) isn't a new question — running retrieval on it would
        # search for the literal word "skip" and answer nonsense. Prompt for
        # a real question instead of guessing one.
        yield PipelineEvent("chunk", {"text": "Sure — what would you like to ask?"})
        yield PipelineEvent(
            "done",
            {
                "professional_help_recommended": False,
                "legal_topic": "",
                "legal_category": "other",
                "case_type": "",
                "clarification_question": None,
                "citations": [],
                "origin": Origin.NONE,
                "providers": ProvidersUsed(analysis=ProviderName.NONE, answer=ProviderName.NONE).model_dump(),
                "conversation_id": state.conversation_id,
                "phase": ConversationPhase.INTAKE,
                "route": state.route,
                "awaiting": None,
            },
        )
        return
    if is_new_topic:
        state.reset_for_new_topic(request.question)

    if state.phase == ConversationPhase.AWAITING_LOCATION:
        async for event in _run_location_phase(
            request, state, ai_service=ai_service, web_search_service=web_search_service,
            lawyer_directory_service=lawyer_directory_service,
        ):
            yield event
        return

    async for event in _run_intake_and_answer(
        request, state, history,
        ai_service=ai_service, knowledge_service=knowledge_service, web_search_service=web_search_service,
    ):
        yield event


async def _run_intake_and_answer(
    request: ChatRequest,
    state: ConversationState,
    history: list[dict[str, str]] | None,
    *,
    ai_service: AIService,
    knowledge_service: KnowledgeService,
    web_search_service: WebSearchService,
) -> AsyncIterator[PipelineEvent]:
    # A reply to a question we asked last turn is filed against that slot
    # before intake runs again, so the fact survives even if the model's own
    # extraction misses it.
    if state.pending_slot_key:
        state.record_answer_to_pending(request.question)

    # --- Stage 1: intake -----------------------------------------------
    yield PipelineEvent("status", {"stage": Stage.ANALYZING, "message": "Understanding your situation..."})

    # A later turn re-derives legal_topic/category/route from the whole
    # conversation every time (see INTAKE_SYSTEM_PROMPT) — but a short reply
    # like "skip" gives the model little to work with, and it can revert to
    # the generic defaults ("other"/"legal") even though an earlier turn in
    # THIS SAME topic already identified something more specific. Once
    # something specific is known, only a genuinely more specific answer
    # should replace it — never a fall-back to the default.
    previous_category = state.analysis.legal_category if state.analysis else None
    previous_route = state.route if state.analysis else None

    intake_result, intake_provider = await run_intake_turn(ai_service, state, request.question, history)

    if previous_category and previous_category != "other" and intake_result.legal_category == "other":
        intake_result.legal_category = previous_category
    if previous_route and previous_route != Route.LEGAL and intake_result.route == Route.LEGAL:
        intake_result.route = previous_route

    state.slots.update(intake_result.slots_filled)
    state.route = Route(intake_result.route)
    state.analysis = QueryAnalysis(
        legal_topic=intake_result.legal_topic,
        legal_category=intake_result.legal_category,
        case_type=intake_result.case_type,
        intent=intake_result.intent,
        keywords=intake_result.keywords,
        needs_clarification=not intake_result.sufficient,
        clarification_question=intake_result.next_question or None,
        professional_help_signal=intake_result.professional_help_signal,
    )

    yield PipelineEvent(
        "analysis",
        {
            "legal_topic": intake_result.legal_topic,
            "legal_category": intake_result.legal_category,
            "case_type": intake_result.case_type,
            "intent": intake_result.intent,
            "keywords": intake_result.keywords,
            "needs_clarification": not intake_result.sufficient,
            "clarification_question": intake_result.next_question or None,
            "route": state.route,
            "route_reason": intake_result.route_reason,
        },
    )

    if not intake_result.sufficient:
        state.record_question(intake_result.next_question, intake_result.next_question_key)
        yield PipelineEvent(
            "question",
            {
                "text": intake_result.next_question,
                "question_key": intake_result.next_question_key,
                "round": state.rounds_asked,
                "max_rounds": 3,
                "can_skip": True,
            },
        )
        # Rendered as a normal reply bubble too, so a frontend that only
        # understands "chunk" (or the /sync endpoint) still shows the question.
        yield PipelineEvent("chunk", {"text": intake_result.next_question})
        yield PipelineEvent(
            "done",
            {
                "professional_help_recommended": False,
                "legal_topic": intake_result.legal_topic,
                "legal_category": intake_result.legal_category,
                "case_type": intake_result.case_type,
                "clarification_question": intake_result.next_question,
                "citations": [],
                "origin": Origin.NONE,
                "providers": ProvidersUsed(analysis=intake_provider, answer=ProviderName.NONE).model_dump(),
                "conversation_id": state.conversation_id,
                "phase": ConversationPhase.INTAKE,
                "route": state.route,
                "awaiting": Awaiting.CLARIFICATION,
            },
        )
        return

    # Enough context gathered (or the user skipped) — fall through to the
    # answer in this same turn rather than making them wait another round trip.
    state.phase = ConversationPhase.ANSWERING
    async for event in _run_answer(
        request, state, history, intake_provider,
        ai_service=ai_service, knowledge_service=knowledge_service, web_search_service=web_search_service,
    ):
        yield event


async def _run_answer(
    request: ChatRequest,
    state: ConversationState,
    history: list[dict[str, str]] | None,
    analysis_provider: ProviderName,
    *,
    ai_service: AIService,
    knowledge_service: KnowledgeService,
    web_search_service: WebSearchService,
) -> AsyncIterator[PipelineEvent]:
    analysis = state.analysis
    history_text = build_history_text(history)

    # --- Stage 2: local knowledge retrieval ---------------------------------
    yield PipelineEvent(
        "status",
        {"stage": Stage.SEARCHING_KNOWLEDGE, "message": "Searching local legal knowledge base..."},
    )

    # Two passes, most specific first. After a few clarifying questions the
    # intake keywords drift onto the detail just discussed ("arrest without
    # warrant", "Vellore police station") and stop matching the Article that
    # actually governs the situation. Merging both sets into one query is worse,
    # not better: coverage is measured across every keyword, so the extra terms
    # drag the ratio below the sufficiency bar and push an answerable question
    # out to the web. So try the precise set, and only if it falls short, retry
    # with the user's own words before giving up on the local corpus.
    search_keywords = list(analysis.keywords)
    scored_sections = knowledge_service.search(search_keywords)
    if not knowledge_service.is_sufficient(scored_sections):
        original_keywords = extract_keywords(state.original_question, max_keywords=8)
        # Decide sufficiency on the user's own words alone — a small, focused
        # set gives an honest coverage ratio. Then retrieve across both sets,
        # because the question's bare words ("got", "arrested", "police") rank
        # Article 22 too low to survive on their own.
        if knowledge_service.is_sufficient(knowledge_service.search(original_keywords)):
            search_keywords = _dedupe(search_keywords + original_keywords)
            scored_sections = knowledge_service.search(search_keywords)
            logger.info(
                "Local retry on the original question rescued %r", state.original_question[:60]
            )

    origin = Origin.NONE
    context_blocks: list[str] = []
    citations: list[Citation] = []

    if knowledge_service.is_sufficient(scored_sections):
        origin = Origin.LOCAL
        context_blocks = context_blocks_from_knowledge(scored_sections)
        citations = citations_from_knowledge(scored_sections)
    else:
        # --- Stage 3: web search fallback -----------------------------------
        yield PipelineEvent(
            "status",
            {"stage": Stage.SEARCHING_WEB, "message": "Local knowledge insufficient — searching approved official sources..."},
        )
        query = " ".join(search_keywords) or state.original_question
        web_results = await web_search_service.search(query)
        if web_results:
            origin = Origin.WEB
            context_blocks = context_blocks_from_web(web_results)
            citations = citations_from_web(web_results)
        elif scored_sections:
            # Web search found nothing either — fall back to the best local
            # matches we do have rather than answering from total emptiness.
            origin = Origin.LOCAL
            context_blocks = context_blocks_from_knowledge(scored_sections)
            citations = citations_from_knowledge(scored_sections)

    yield PipelineEvent("sources", {"origin": origin, "citations": [c.model_dump() for c in citations]})

    # --- Stage 4: answer generation -----------------------------------------
    yield PipelineEvent("status", {"stage": Stage.GENERATING, "message": "Generating your answer..."})

    full_answer = ""
    answer_provider = ProviderName.NONE
    stream_error: str | None = None
    generated_nothing = False
    try:
        async for chunk, provider in stream_answer(
            ai_service, state.original_question, context_blocks, history_text,
            route=state.route.value, slots=state.slots,
        ):
            full_answer += chunk
            answer_provider = provider
            yield PipelineEvent("chunk", {"text": chunk})
    except AnswerStreamError as e:
        full_answer = e.partial_text
        stream_error = str(e)
        generated_nothing = e.generated_nothing
        logger.error("Answer stream failed (generated_nothing=%s): %s", generated_nothing, e)

    if stream_error:
        # No answer was produced, so the professional-help assessment below is
        # deliberately skipped: offering to find a lawyer for a question we
        # never managed to answer is worse than saying nothing.
        if generated_nothing:
            message = (
                "The AI service is temporarily unavailable or rate-limited, so no answer "
                "could be generated. Please try again in a few minutes."
            )
        else:
            message = "The answer generation was interrupted before completing."
        yield PipelineEvent("error", {"message": message, "recoverable": generated_nothing})
        return

    state.last_answer = full_answer

    # --- Stage 5: deterministic professional-help assessment ---------------
    professional_help = assess_professional_help(analysis, state.original_question, full_answer)

    if professional_help:
        location_prompt = f"\n\n{LOCATION_REQUEST_MESSAGE}"
        yield PipelineEvent("chunk", {"text": location_prompt})
        state.phase = ConversationPhase.AWAITING_LOCATION
        awaiting = Awaiting.LOCATION
        phase = ConversationPhase.AWAITING_LOCATION
    else:
        # Ready for a new topic. Left in INTAKE with `analysis` still set, so
        # the next incoming message is recognized as a new topic (see
        # `is_new_topic` in `run`) rather than a reply to a stale question.
        state.phase = ConversationPhase.INTAKE
        awaiting = None
        phase = ConversationPhase.INTAKE

    yield PipelineEvent(
        "done",
        {
            "professional_help_recommended": professional_help,
            "legal_topic": analysis.legal_topic,
            "legal_category": analysis.legal_category,
            "case_type": analysis.case_type,
            "clarification_question": None,
            "citations": [c.model_dump() for c in citations],
            "origin": origin,
            "providers": ProvidersUsed(analysis=analysis_provider, answer=answer_provider).model_dump(),
            "conversation_id": state.conversation_id,
            "phase": phase,
            "route": state.route,
            "awaiting": awaiting,
        },
    )


async def _run_location_phase(
    request: ChatRequest,
    state: ConversationState,
    *,
    ai_service: AIService,
    web_search_service: WebSearchService,
    lawyer_directory_service: LawyerDirectoryService,
) -> AsyncIterator[PipelineEvent]:
    yield PipelineEvent(
        "status", {"stage": Stage.FINDING_HELP, "message": "Looking for advocates and legal-aid contacts..."}
    )

    # Escape hatch: a user who can't or doesn't want to give a location must
    # not be stuck in a loop asking for one. Fall back to the national
    # legal-aid contacts, which need no location at all.
    if wants_to_skip(request.question):
        state.awaiting_state_only = False
        state.phase = ConversationPhase.INTAKE
        response = LegalAssistanceResponse(
            legal_topic=(state.analysis.legal_topic if state.analysis else state.original_question)
            or "General legal matter",
            location="",
            match_scope=MatchScope.NONE,
            advocate_data_available=False,
            legal_aid=load_national_legal_aid(),
            disclaimer=NO_RESULTS_DISCLAIMER,
            reason="No location was given, so I can't narrow this to local advocates. "
            "The national legal-aid contacts below can help regardless of where you are.",
        )
        yield PipelineEvent("assistance", _assistance_payload(response))
        yield PipelineEvent("chunk", {"text": _assistance_summary_text(response)})
        yield PipelineEvent(
            "done",
            {
                "professional_help_recommended": False,
                "legal_topic": response.legal_topic,
                "legal_category": state.analysis.legal_category if state.analysis else "other",
                "case_type": (state.analysis.case_type if state.analysis else "") or "",
                "clarification_question": None,
                "citations": [],
                "origin": Origin.NONE,
                "providers": ProvidersUsed(analysis=ProviderName.NONE, answer=ProviderName.NONE).model_dump(),
                "conversation_id": state.conversation_id,
                "phase": ConversationPhase.ASSISTANCE,
                "route": state.route,
                "awaiting": None,
            },
        )
        return

    if state.awaiting_state_only and state.district:
        district, state_name = state.district, request.question.strip()
    else:
        district, state_name = location_service.parse_location_text(request.question)
        state.district = district

    analysis = state.analysis
    la_request = LegalAssistanceRequest(
        district=district or "Unknown",
        state=state_name,
        legal_category=(analysis.legal_category if analysis else "other") or "other",
        legal_topic=(analysis.legal_topic if analysis else state.original_question) or "General legal matter",
        case_type=analysis.case_type if analysis else None,
    )

    response = await get_legal_assistance(
        la_request,
        ai_service=ai_service,
        web_search_service=web_search_service,
        lawyer_directory_service=lawyer_directory_service,
    )

    if response.state_required:
        state.awaiting_state_only = True
        text = response.reason or "I couldn't determine the state for that district."
        if response.candidate_states:
            text += "\n\nPlease tell me the state — for example: " + ", ".join(response.candidate_states[:8])
        yield PipelineEvent("chunk", {"text": text})
        yield PipelineEvent(
            "done",
            {
                "professional_help_recommended": True,
                "legal_topic": la_request.legal_topic,
                "legal_category": la_request.legal_category,
                "case_type": la_request.case_type or "",
                "clarification_question": None,
                "citations": [],
                "origin": Origin.NONE,
                "providers": ProvidersUsed(analysis=ProviderName.NONE, answer=ProviderName.NONE).model_dump(),
                "conversation_id": state.conversation_id,
                "phase": ConversationPhase.AWAITING_LOCATION,
                "route": state.route,
                "awaiting": Awaiting.LOCATION,
            },
        )
        return

    state.awaiting_state_only = False
    state.state_name = state_name or ""

    yield PipelineEvent("assistance", _assistance_payload(response))
    yield PipelineEvent("chunk", {"text": _assistance_summary_text(response)})

    # Delivered — leave the conversation ready for a new topic next turn.
    state.phase = ConversationPhase.INTAKE

    yield PipelineEvent(
        "done",
        {
            "professional_help_recommended": False,
            "legal_topic": la_request.legal_topic,
            "legal_category": la_request.legal_category,
            "case_type": la_request.case_type or "",
            "clarification_question": None,
            "citations": [],
            "origin": Origin.NONE,
            "providers": ProvidersUsed(analysis=ProviderName.NONE, answer=ProviderName.NONE).model_dump(),
            "conversation_id": state.conversation_id,
            "phase": ConversationPhase.ASSISTANCE,
            "route": state.route,
            "awaiting": None,
        },
    )


def _dedupe(keywords: list[str]) -> list[str]:
    """Order-preserving de-duplication, case-insensitive."""
    seen: dict[str, None] = {}
    for kw in keywords:
        cleaned = kw.strip()
        if cleaned:
            seen.setdefault(cleaned.lower(), None)
    return list(seen)


def _assistance_payload(response: LegalAssistanceResponse) -> dict[str, Any]:
    return {
        "location": response.location,
        "match_scope": response.match_scope,
        "advocate_data_available": response.advocate_data_available,
        "advocates": [r.model_dump() for r in response.results],
        "legal_aid": [r.model_dump() for r in response.legal_aid],
        "disclaimer": response.disclaimer,
        "reason": response.reason,
        "manual_search_url": response.manual_search_url,
    }


def _assistance_summary_text(response: LegalAssistanceResponse) -> str:
    lines: list[str] = []
    if response.advocate_data_available and response.results:
        lines.append(f"Here's what I found for **{response.location}**:\n")
        for r in response.results:
            where = f", {r.court_or_jurisdiction}" if r.court_or_jurisdiction else ""
            lines.append(f"- **{r.name}** — {r.relevant_area}{where}")
    else:
        lines.append(response.reason or "No advocates could be identified from publicly available sources for this location.")

    if response.legal_aid:
        lines.append("\nFree / official legal-aid contacts:")
        for aid in response.legal_aid[:3]:
            contact = f" — {aid.contact}" if aid.contact else ""
            lines.append(f"- **{aid.name}**{contact}")

    if response.manual_search_url:
        lines.append(f"\nYou can also search manually on the official eCourts portal: {response.manual_search_url}")

    lines.append(f"\n{response.disclaimer}")
    return "\n".join(lines)
