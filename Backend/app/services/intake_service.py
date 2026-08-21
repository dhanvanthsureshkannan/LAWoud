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
import re

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
        # Left as a bare object on purpose: the Gemini Developer API rejects
        # `additionalProperties`, and models answer yes/no slots with real
        # booleans anyway — IntakeResult coerces the values instead.
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


# --- Deterministic floor on context gathering --------------------------------
# The model decides *what* to ask well, but is inconsistent about *whether* to
# ask: the same "I got arrested by police" asks a question on one run and
# answers cold on the next. Gathering context is the whole point of this stage,
# so whether to ask at least once is decided in code, not left to sampling.

# Something has actually happened, to this user.
_INCIDENT_RE = re.compile(
    r"\b(?:i|we|my|me)\b.{0,40}\b(?:was|were|got|have been|has been|am being|received|"
    r"filed|arrested|detained|charged|sued|evicted|fired|terminated|cheated|scammed|"
    r"harassed|threatened|assaulted|robbed)\b"
    r"|\b(?:police|court|landlord|employer|bank|company|husband|wife|neighbour|neighbor)\b"
    r".{0,40}\b(?:arrest|detain|charg|summon|evict|fir|su|seiz|refus|threaten|harass|assault)"
    r"(?:ed|ing|s)?\b.{0,20}\b(?:me|us|my|our)\b"
    r"|\bagainst\s+me\b|\bmy\s+(?:case|fir|bail|arrest|divorce|land|property|salary)\b",
    re.IGNORECASE,
)

# Asking about the law in the abstract — these must never be interrogated.
_HYPOTHETICAL_RE = re.compile(
    r"^\s*(?:can|could|may|is|are|does|do|what|how|when|where|why|which|who)\b"
    r"(?!.*\b(?:i was|i got|i have been|i am being|happened to me|against me|my case)\b)",
    re.IGNORECASE,
)

# Used only when the floor fires but the model returned no question of its own.
_FALLBACK_QUESTIONS: dict[str, tuple[str, str]] = {
    "criminal": ("What reason did the police or authorities give you for this?", "stated_reason"),
    "family": ("Has anything been formally filed in court yet?", "court_filing_status"),
    "property": ("Is there a written agreement or document covering this?", "written_agreement"),
    "consumer": ("Do you still have the bill, receipt, or order confirmation?", "proof_of_purchase"),
    "labour": ("Do you have a written employment contract or appointment letter?", "written_contract"),
    "cyber": ("Have you already reported this to your bank or the cybercrime portal?", "reported_yet"),
    "tax": ("Which assessment year does this relate to?", "assessment_year"),
}
_DEFAULT_FALLBACK = (
    "Could you tell me a little more about what has happened so far?",
    "situation_detail",
)


def describes_incident(question: str) -> bool:
    """True when the user is reporting something that happened to them, rather
    than asking about the law in general."""
    if _HYPOTHETICAL_RE.match(question) and not _INCIDENT_RE.search(question):
        return False
    return bool(_INCIDENT_RE.search(question))


def _apply_question_floor(result: IntakeResult, state: ConversationState) -> IntakeResult:
    """Force at least one context question for a real incident reported cold."""
    already_gathered = bool(state.slots) or state.rounds_asked > 0
    if already_gathered or not result.sufficient:
        return result
    if not describes_incident(state.original_question):
        return result

    # The model often supplies a good question yet still marks itself sufficient.
    # Prefer its question; fall back to a category default only if it gave none.
    if result.next_question.strip():
        question, key = result.next_question, result.next_question_key or "situation_detail"
    else:
        question, key = _FALLBACK_QUESTIONS.get(result.legal_category, _DEFAULT_FALLBACK)

    logger.info(
        "Question floor engaged for %r (category=%s): asking %r before answering.",
        state.original_question[:60],
        result.legal_category,
        question[:60],
    )
    result.sufficient = False
    result.next_question = question
    result.next_question_key = key
    return result


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

    raw = ""
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
        # Log the payload too: a validation error here silently disables the
        # whole follow-up-question feature, and without the raw JSON it reads
        # like model flakiness rather than a schema mismatch.
        logger.warning("Malformed intake JSON, skipping to answer: %s | raw=%.500s", e, raw)
        return _heuristic_intake(state.original_question), ProviderName.HEURISTIC

    if wants_to_skip(latest_message) or not state.can_ask_more:
        result.sufficient = True
        result.next_question = ""
        return result, provider

    # A question the model already asked would loop the user forever; drop it
    # and answer instead of repeating ourselves.
    if result.next_question and result.next_question in state.asked_questions:
        logger.info("Intake repeated an earlier question; answering instead.")
        result.sufficient = True
        result.next_question = ""
        return result, provider

    return _apply_question_floor(result, state), provider


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
