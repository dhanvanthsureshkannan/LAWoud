"""POST /api/chat (SSE), GET /api/chat/stream (EventSource-compatible), POST /api/chat/sync."""

import asyncio
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.deps import get_ai_service, get_knowledge_service, get_web_search_service
from app.core.sse import sse_event, sse_heartbeat
from app.models.schemas import ChatDone, ChatRequest, ChatSyncResponse, QueryAnalysis
from app.services import orchestrator
from app.services.ai.ai_service import AIService
from app.services.knowledge_service import KnowledgeService
from app.services.web_search_service import WebSearchService

logger = logging.getLogger("lawoud.api.chat")
router = APIRouter(prefix="/api/chat", tags=["chat"])

_HEARTBEAT_INTERVAL_SECONDS = 15.0


async def _sse_stream(
    request: ChatRequest,
    ai_service: AIService,
    knowledge_service: KnowledgeService,
    web_search_service: WebSearchService,
) -> AsyncIterator[str]:
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def produce() -> None:
        try:
            async for event in orchestrator.run(
                request,
                ai_service=ai_service,
                knowledge_service=knowledge_service,
                web_search_service=web_search_service,
            ):
                await queue.put(sse_event(event.event, event.data))
        except Exception:
            logger.exception("Unhandled error in chat pipeline")
            await queue.put(
                sse_event("error", {"message": "An unexpected error occurred.", "recoverable": False})
            )
        finally:
            await queue.put(None)

    producer_task = asyncio.create_task(produce())
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=_HEARTBEAT_INTERVAL_SECONDS)
            except asyncio.TimeoutError:
                yield sse_heartbeat()
                continue
            if item is None:
                break
            yield item
    finally:
        if not producer_task.done():
            producer_task.cancel()


@router.post("")
async def chat(
    request: ChatRequest,
    ai_service: AIService = Depends(get_ai_service),
    knowledge_service: KnowledgeService = Depends(get_knowledge_service),
    web_search_service: WebSearchService = Depends(get_web_search_service),
) -> StreamingResponse:
    """Primary chat endpoint. Streams the full analyze -> retrieve -> answer flow as SSE."""
    return StreamingResponse(
        _sse_stream(request, ai_service, knowledge_service, web_search_service),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/stream")
async def chat_stream_get(
    question: str,
    ai_service: AIService = Depends(get_ai_service),
    knowledge_service: KnowledgeService = Depends(get_knowledge_service),
    web_search_service: WebSearchService = Depends(get_web_search_service),
) -> StreamingResponse:
    """Same stream as POST /api/chat, but via GET so browsers can use EventSource
    directly (EventSource cannot send a POST body)."""
    request = ChatRequest(question=question)
    return StreamingResponse(
        _sse_stream(request, ai_service, knowledge_service, web_search_service),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/sync")
async def chat_sync(
    request: ChatRequest,
    ai_service: AIService = Depends(get_ai_service),
    knowledge_service: KnowledgeService = Depends(get_knowledge_service),
    web_search_service: WebSearchService = Depends(get_web_search_service),
) -> ChatSyncResponse:
    """Same pipeline as POST /api/chat, drained into one JSON response.
    For testing or clients that don't want to handle SSE."""
    answer_parts: list[str] = []
    analysis_data: dict = {}
    done_data: dict = {}

    async for event in orchestrator.run(
        request,
        ai_service=ai_service,
        knowledge_service=knowledge_service,
        web_search_service=web_search_service,
    ):
        if event.event == "analysis":
            analysis_data = event.data
        elif event.event == "chunk":
            answer_parts.append(event.data["text"])
        elif event.event == "done":
            done_data = event.data
        elif event.event == "error":
            answer_parts.append(f"\n\n[Error: {event.data.get('message', 'unknown error')}]")

    analysis = QueryAnalysis(
        legal_topic=analysis_data.get("legal_topic", ""),
        legal_category=analysis_data.get("legal_category", "other"),
        case_type=analysis_data.get("case_type", ""),
        intent=analysis_data.get("intent", ""),
        keywords=analysis_data.get("keywords", []),
        needs_clarification=analysis_data.get("needs_clarification", False),
        clarification_question=analysis_data.get("clarification_question"),
    )
    done = ChatDone(**done_data) if done_data else ChatDone(
        professional_help_recommended=False,
        legal_topic=analysis.legal_topic,
        legal_category=analysis.legal_category,
        case_type=analysis.case_type,
        origin="none",
        providers={"analysis": "none", "answer": "none"},
    )

    return ChatSyncResponse(answer="".join(answer_parts), analysis=analysis, done=done)
