"""Stage 2: generate the final answer, streaming, from retrieved context ONLY."""

import logging
from collections.abc import AsyncIterator

from app.core.prompts import ANSWER_SYSTEM_PROMPT, NO_CONTEXT_FALLBACK_ANSWER, build_answer_prompt
from app.models.schemas import ProviderName
from app.services.ai.ai_service import AIService, AllProvidersFailedError

logger = logging.getLogger("lawoud.answer_service")


class AnswerStreamError(Exception):
    """Raised when generation fails partway through streaming, after some text
    has already been sent. The caller (orchestrator) must not silently retry —
    it should surface this to the client and close the stream."""

    def __init__(self, message: str, partial_text: str):
        self.partial_text = partial_text
        super().__init__(message)


async def stream_answer(
    ai_service: AIService,
    question: str,
    context_blocks: list[str],
    history_text: str,
) -> AsyncIterator[tuple[str, ProviderName]]:
    """Yield (chunk, provider_used) tuples for the final answer.

    If there is no context at all, skips the AI call entirely and yields a
    single explanatory chunk — the model must never be asked to answer from
    nothing, since that's exactly the "confidently guess" failure mode this
    system exists to prevent.
    """
    if not context_blocks:
        yield NO_CONTEXT_FALLBACK_ANSWER, ProviderName.NONE
        return

    prompt = build_answer_prompt(question, context_blocks, history_text)

    partial = ""
    try:
        async for chunk, provider in ai_service.stream_text(prompt, system=ANSWER_SYSTEM_PROMPT):
            partial += chunk
            yield chunk, provider
    except AllProvidersFailedError as e:
        logger.error("Both AI providers failed during answer generation: %s", e)
        if partial:
            raise AnswerStreamError(str(e), partial) from e
        yield (
            "Both AI providers are currently unavailable, so I can't generate an answer "
            "right now. Please try again shortly.",
            ProviderName.NONE,
        )
