"""Intake stage: one LLM call per turn that analyzes the question, routes it
moral/legal/mixed, and decides the single next thing to ask — or that we
already know enough to answer.

Combining analysis + routing + next-question into one call (rather than three
separate round-trips) is what keeps the conversational back-and-forth feeling
responsive; splitting them would triple the latency of every intake turn for
no benefit, since all three decisions depend on the same context.
"""

import json
import logging

from app.core.prompts import INTAKE_SYSTEM_PROMPT, build_history_text, build_intake_prompt
from app.core.text import keywords as extract_keywords
from app.models.schemas import IntakeResult, ProviderName, Route
from app.services.ai.ai_service import AIService, AllProvidersFailedError
from app.services.session_store import ConversationState

logger = logging.getLogger("lawoud.intake_service")

_INTAKE_JSON_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "legal_topic": {"type": "string"},
        "legal_category": {
            "type": "string",
            "enum": [
                "civil", "criminal", "family", "consumer", "labour",
                "property", "cyber", "tax", "constitutional", "other",
            ],
        },
        "case_type": {"type": "string"},
        "intent": {"type": "string"},
        "keywords": {"type": "array", "items": {"type": "string"}},
        "route": {"type": "string", "enum": ["legal", "moral", "mixed"]},
        "route_reason": {"type": "string"},
        "slots_filled": {"type": "object"},
        "next_question": {"type": "string"},
        "next_question_key": {"type": "string"},
        "sufficient": {"type": "boolean"},
        "professional_help_signal": {"type": "boolean"},
    },
    "required": [
        "legal_topic", "legal_category", "case_type", "intent", "keywords",
        "route", "route_reason", "next_question", "sufficient", "professional_help_signal",
    ],
}

# User replies that mean "stop asking, just answer" regardless of what the model decides.
_SKIP_PHRASES = frozenset(
    """
    skip idk unsure notsure justanswer answeranyway idontknow dontknow
    justtellme noidea whatever justgo proceed continue
    """.split()
)


def wants_to_skip(user_text: str) -> bool:
    compact = "".join(ch for ch in user_text.lower() if ch.isalnum())
    return any(phrase in compact for phrase in _SKIP_PHRASES) or len(compact) == 0


async def run_intake_turn(
    ai_service: AIService,
    state: ConversationState,
    latest_message: str,
    history: list[dict[str, str]] | None,
) -> tuple[IntakeResult, ProviderName]:
    """Run one intake turn. Falls back to a heuristic pass-through (no questions
    asked) if both AI providers are unavailable, so retrieval can still proceed."""
    history_text = build_history_text(history)
    prompt = build_intake_prompt(state.original_question, state.slots, state.asked_questions, history_text)

    try:
        raw, provider = await ai_service.generate_json(
            prompt, schema=_INTAKE_JSON_SCHEMA, system=INTAKE_SYSTEM_PROMPT
        )
        data = json.loads(raw)
        result = IntakeResult(**data)
    except AllProvidersFailedError as e:
        logger.warning("Both AI providers failed during intake, skipping to answer: %s", e)
        return _heuristic_intake(state.original_question), ProviderName.HEURISTIC
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        logger.warning("Malformed intake JSON, skipping to answer: %s", e)
        return _heuristic_intake(state.original_question), ProviderName.HEURISTIC

    if wants_to_skip(latest_message) or not state.can_ask_more:
        result.sufficient = True
        result.next_question = ""

    return result, provider


def _heuristic_intake(question: str) -> IntakeResult:
    """Offline fallback when both AI providers are down: answer immediately with
    whatever the keyword heuristic can infer, never leaving the user stuck on
    a question that will never resolve."""
    kws = extract_keywords(question, max_keywords=8)
    return IntakeResult(
        legal_topic=question.strip()[:80] or "General legal question",
        legal_category="other",
        case_type="",
        intent="Understand the relevant legal information",
        keywords=kws,
        route=Route.LEGAL,
        route_reason="Offline fallback — routing defaulted to legal.",
        slots_filled={},
        next_question="",
        next_question_key="",
        sufficient=True,
        professional_help_signal=False,
    )
