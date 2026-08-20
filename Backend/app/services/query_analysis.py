"""Stage 1: analyze the user's question. Does NOT generate an answer."""

import json
import logging

from app.core.prompts import ANALYSIS_SYSTEM_PROMPT, build_analysis_prompt, build_history_text
from app.core.text import keywords as extract_keywords
from app.models.schemas import ProviderName, QueryAnalysis
from app.services.ai.ai_service import AIService, AllProvidersFailedError

logger = logging.getLogger("lawoud.query_analysis")

_ANALYSIS_JSON_SCHEMA: dict = {
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
        "needs_clarification": {"type": "boolean"},
        # No union types / "null" here — Gemini's response_schema validator rejects
        # them outright, which silently drops every request to the offline heuristic.
        # Empty string means "no question".
        "clarification_question": {"type": "string"},
        "professional_help_signal": {"type": "boolean"},
    },
    "required": [
        "legal_topic", "legal_category", "case_type", "intent", "keywords",
        "needs_clarification", "professional_help_signal",
    ],
}

# Words that, if present, strongly suggest the user may need urgent professional help —
# used only by the offline heuristic fallback (both AI providers unavailable).
_URGENCY_HINTS = frozenset(
    """
    arrest arrested fir summon summons notice bail custody police remand
    court case hearing deadline eviction divorce dowry harassment
    """.split()
)

_CATEGORY_HINTS: dict[str, frozenset[str]] = {
    "criminal": frozenset("fir arrest police bail theft assault murder criminal crime accused".split()),
    "family": frozenset("divorce marriage custody maintenance alimony dowry domestic".split()),
    "consumer": frozenset("refund warranty product defective consumer purchase seller".split()),
    "labour": frozenset("salary wages employer employee termination pf gratuity workplace".split()),
    "property": frozenset("land tenant landlord rent eviction property lease house".split()),
    "cyber": frozenset("online fraud hacking cybercrime phishing otp scam internet".split()),
    "tax": frozenset("tax income gst return filing itr".split()),
    "constitutional": frozenset("rights fundamental constitution writ petition".split()),
}


async def analyze_query(
    ai_service: AIService,
    question: str,
    history: list[dict[str, str]] | None = None,
) -> tuple[QueryAnalysis, ProviderName]:
    """Run structured query analysis. Falls back to a keyword heuristic if both
    AI providers fail, so retrieval can still proceed."""
    history_text = build_history_text(history)
    prompt = build_analysis_prompt(question, history_text)

    try:
        raw, provider = await ai_service.generate_json(
            prompt, schema=_ANALYSIS_JSON_SCHEMA, system=ANALYSIS_SYSTEM_PROMPT
        )
        data = json.loads(raw)
        analysis = QueryAnalysis(**data)
        return analysis, provider
    except AllProvidersFailedError as e:
        logger.warning("Both AI providers failed during query analysis, using heuristic: %s", e)
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        logger.warning("Malformed analysis JSON, using heuristic: %s", e)

    return _heuristic_analysis(question), ProviderName.HEURISTIC


def _heuristic_analysis(question: str) -> QueryAnalysis:
    """Offline fallback when Gemini and Groq are both unavailable.

    Not as good as AI analysis, but keeps the retrieval pipeline functional
    rather than hard-failing the whole request.
    """
    kws = extract_keywords(question, max_keywords=8)
    q_lower = question.lower()

    category = "other"
    for cat, hints in _CATEGORY_HINTS.items():
        if any(h in q_lower for h in hints):
            category = cat
            break

    urgent = any(h in q_lower for h in _URGENCY_HINTS)
    is_vague = len(kws) < 2

    return QueryAnalysis(
        legal_topic=question.strip()[:80] or "General legal question",
        legal_category=category,
        case_type="",
        intent="Understand the relevant legal information",
        keywords=kws,
        needs_clarification=is_vague,
        clarification_question=(
            "Could you share a few more details about your situation?" if is_vague else None
        ),
        professional_help_signal=urgent,
    )
