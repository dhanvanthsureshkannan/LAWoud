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

# Phrasing that marks a question as hypothetical/general rather than a real,
# ongoing incident — "can I kick my friend?" must not trigger urgency just
# because the answer explaining assault law uses the word "assault".
_HYPOTHETICAL_RE = re.compile(
    r"^(can i|could i|is it legal|is it illegal|what happens if|what if|"
    r"what is|what are|am i allowed|do i have the right)\b",
    re.IGNORECASE,
)
# A first-person incident marker overrides the hypothetical read even if the
# question also opens with hypothetical phrasing ("what happens if — I was
# actually arrested last night" should still count as real).
_FIRST_PERSON_INCIDENT_RE = re.compile(
    r"\b(i was|i've been|i have been|i got|they arrested me|against me|filed against me)\b",
    re.IGNORECASE,
)

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
    - the QUESTION itself contains an urgency/severity marker and isn't merely
      hypothetical, or
    - the answer itself says the available information was insufficient
      (a genuinely unresolved question is exactly when a human expert helps).

    Urgency is checked against the question only, never the answer — an answer
    that explains assault law in the abstract will naturally contain the word
    "assault" even when the question was a hypothetical ("can I kick my
    friend?"), and that must not read as a real incident needing a lawyer.
    """
    if analysis.professional_help_signal:
        return True

    if _URGENCY_RE.search(question):
        is_hypothetical = bool(_HYPOTHETICAL_RE.search(question.strip()))
        is_first_person_incident = bool(_FIRST_PERSON_INCIDENT_RE.search(question))
        if not is_hypothetical or is_first_person_incident:
            return True

    answer_lower = answer.lower()
    if any(marker in answer_lower for marker in _INSUFFICIENT_INFO_MARKERS):
        return True

    return False
