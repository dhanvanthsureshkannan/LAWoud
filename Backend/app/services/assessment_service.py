"""Decides whether professional legal help should be flagged. Deterministic —
no extra AI call, so it adds no latency and its behavior is easy to reason about
and demo. Runs AFTER the answer, using the analysis, the question, and the answer.
"""

import re

from app.models.schemas import QueryAnalysis

# Signals that a situation is urgent, serious, or case-specific rather than a
# general informational question.
_URGENCY_PATTERNS = [
    r"\barrest(ed)?\b",
    r"\bcustody\b",
    r"\bbail\b",
    r"\bfir\b",
    r"\bsummons?\b",
    r"\bnotice\b.*\b(receiv|got|sent)",
    r"\bcourt\s+(date|hearing|order)\b",
    r"\bdeadline\b",
    r"\bpolice\s+(complaint|station)\b",
    r"\bdomestic\s+violence\b",
    r"\bharassment\b",
    r"\bthreat(en(ed|ing))?\b",
    r"\bdivorce\b",
    r"\beviction\b",
    r"\bsue(d)?\b",
    r"\blawsuit\b",
    r"\bcase\s+against\s+me\b",
    r"\bcheque\s+bounce\b",
    r"\bsuicide\b",
    r"\bassault(ed)?\b",
]
_URGENCY_RE = re.compile("|".join(_URGENCY_PATTERNS), re.IGNORECASE)

_INSUFFICIENT_INFO_MARKERS = (
    "don't have enough verified information",
    "not enough information",
    "sources don't cover",
    "does not cover this",
    "could not find reliable information",
    "cannot provide a complete answer",
)


def assess_professional_help(
    analysis: QueryAnalysis,
    question: str,
    answer: str,
) -> bool:
    """True if the situation may warrant professional legal assistance.

    Deliberately not triggered for every question — only when at least one of:
    - the analysis stage already flagged an urgency signal, or
    - the question or answer contains an urgency/severity marker, or
    - the answer itself says the available information was insufficient
      (a genuinely unresolved question is exactly when a human expert helps).
    """
    if analysis.professional_help_signal:
        return True

    combined = f"{question}\n{answer}"
    if _URGENCY_RE.search(combined):
        return True

    answer_lower = answer.lower()
    if any(marker in answer_lower for marker in _INSUFFICIENT_INFO_MARKERS):
        return True

    return False
