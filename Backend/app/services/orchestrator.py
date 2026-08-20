"""The /chat pipeline as a single async generator of typed events.

Both the SSE route and the /chat/sync route drain this same generator, so they
cannot drift apart: SSE serializes each event to the wire as it arrives,
/sync collects them into one JSON body.
"""

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from app.core.prompts import build_history_text
from app.models.schemas import (
    ChatRequest,
    Citation,
    Origin,
    ProviderName,
    ProvidersUsed,
    Stage,
)
from app.services.ai.ai_service import AIService
from app.services.answer_service import AnswerStreamError, stream_answer
from app.services.assessment_service import assess_professional_help
from app.services.citation_service import (
    citations_from_knowledge,
    citations_from_web,
    context_blocks_from_knowledge,
    context_blocks_from_web,
)
from app.services.knowledge_service import KnowledgeService
from app.services.query_analysis import analyze_query
from app.services.web_search_service import WebSearchService

logger = logging.getLogger("lawoud.orchestrator")


@dataclass
class PipelineEvent:
    event: str  # "status" | "analysis" | "sources" | "chunk" | "done" | "error"
    data: dict[str, Any]


async def run(
    request: ChatRequest,
    *,
    ai_service: AIService,
    knowledge_service: KnowledgeService,
    web_search_service: WebSearchService,
) -> AsyncIterator[PipelineEvent]:
    history = [h.model_dump() for h in request.history] if request.history else None
    history_text = build_history_text(history)

    # --- Stage 1: query analysis -------------------------------------------
    yield PipelineEvent("status", {"stage": Stage.ANALYZING, "message": "Analyzing your question..."})

    analysis, analysis_provider = await analyze_query(ai_service, request.question, history)

    yield PipelineEvent(
        "analysis",
        {
            "legal_topic": analysis.legal_topic,
            "legal_category": analysis.legal_category,
            "case_type": analysis.case_type,
            "intent": analysis.intent,
            "keywords": analysis.keywords,
            "needs_clarification": analysis.needs_clarification,
            "clarification_question": analysis.clarification_question,
        },
    )

    # --- Stage 2: local knowledge retrieval ---------------------------------
    yield PipelineEvent(
        "status",
        {"stage": Stage.SEARCHING_KNOWLEDGE, "message": "Searching local legal knowledge base..."},
    )

    scored_sections = knowledge_service.search(analysis.keywords)
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
        query = " ".join(analysis.keywords) or request.question
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
    try:
        async for chunk, provider in stream_answer(
            ai_service, request.question, context_blocks, history_text
        ):
            full_answer += chunk
            answer_provider = provider
            yield PipelineEvent("chunk", {"text": chunk})
    except AnswerStreamError as e:
        full_answer = e.partial_text
        stream_error = str(e)
        logger.error("Answer stream failed after partial delivery: %s", e)

    if stream_error:
        yield PipelineEvent(
            "error",
            {"message": "The answer generation was interrupted before completing.", "recoverable": False},
        )
        return

    # --- Stage 5: deterministic professional-help assessment ---------------
    professional_help = assess_professional_help(analysis, request.question, full_answer)

    yield PipelineEvent(
        "done",
        {
            "professional_help_recommended": professional_help,
            "legal_topic": analysis.legal_topic,
            "legal_category": analysis.legal_category,
            "case_type": analysis.case_type,
            "clarification_question": analysis.clarification_question if analysis.needs_clarification else None,
            "citations": [c.model_dump() for c in citations],
            "origin": origin,
            "providers": ProvidersUsed(analysis=analysis_provider, answer=answer_provider).model_dump(),
        },
    )
