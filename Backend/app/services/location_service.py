"""Canonical states/UTs list, and district -> state inference.

The AI is asked which state a district belongs to, but its answer is always
validated against the canonical list below — it cannot cause an invented state
name to reach the response. Districts known to exist in more than one state are
never auto-resolved; the caller is asked to disambiguate instead.
"""

import json
import logging
from functools import lru_cache

from app.config import PROJECT_ROOT
from app.core.text import normalize
from app.services.ai.ai_service import AIService, AllProvidersFailedError

logger = logging.getLogger("lawoud.location_service")

_STATES_PATH = PROJECT_ROOT / "data" / "states.json"


@lru_cache
def _load() -> dict:
    with open(_STATES_PATH, encoding="utf-8") as f:
        return json.load(f)


def all_states() -> list[str]:
    return list(_load()["states"])


def all_union_territories() -> list[str]:
    return list(_load()["union_territories"])


def all_state_names() -> list[str]:
    """States + union territories, for validating AI-inferred answers."""
    return all_states() + all_union_territories()


# Common alternate spellings, former names, and abbreviations users actually
# type. Keys are already in canonical-key form (lowercase, alphanumeric only).
_STATE_ALIASES: dict[str, str] = {
    "orissa": "Odisha",
    "pondicherry": "Puducherry",
    "pondichery": "Puducherry",
    "newdelhi": "Delhi",
    "delhincr": "Delhi",
    "ncr": "Delhi",
    "nctofdelhi": "Delhi",
    "jk": "Jammu and Kashmir",
    "jandk": "Jammu and Kashmir",
    "jammukashmir": "Jammu and Kashmir",
    "up": "Uttar Pradesh",
    "mp": "Madhya Pradesh",
    "ap": "Andhra Pradesh",
    "tn": "Tamil Nadu",
    "wb": "West Bengal",
    "hp": "Himachal Pradesh",
    "uk": "Uttarakhand",
    "uttaranchal": "Uttarakhand",
    "chattisgarh": "Chhattisgarh",
    "andaman": "Andaman and Nicobar Islands",
    "andamannicobar": "Andaman and Nicobar Islands",
    "dadranagarhaveli": "Dadra and Nagar Haveli and Daman and Diu",
    "damananddiu": "Dadra and Nagar Haveli and Daman and Diu",
}


def _canonical_key(name: str) -> str:
    """Reduce a place name to a comparison key: lowercase, alphanumeric only.

    This is what makes 'tamilnadu', 'Tamil Nadu', and 'TAMIL  NADU' all match —
    users type state names inconsistently and shouldn't be penalised for it.
    """
    return "".join(ch for ch in name.lower() if ch.isalnum())


def resolve_state(name: str) -> str | None:
    """Resolve user input to a canonical state/UT name, or None if unrecognized.

    Handles spacing/casing differences, the ' and '/' & ' variants, common
    former names (Orissa), and standard abbreviations (TN, UP, J&K).
    """
    if not name or not name.strip():
        return None
    key = _canonical_key(name)
    if not key:
        return None

    for canonical in all_state_names():
        if _canonical_key(canonical) == key:
            return canonical

    # '&' and 'and' are used interchangeably in official names.
    key_and = key.replace("and", "")
    for canonical in all_state_names():
        if _canonical_key(canonical).replace("and", "") == key_and:
            return canonical

    return _STATE_ALIASES.get(key)


def is_valid_state(name: str) -> bool:
    return resolve_state(name) is not None


def parse_location_text(text: str) -> tuple[str, str | None]:
    """Split a free-text chat reply like "Vellore, Tamil Nadu" into
    (district, state_or_None). Used by the orchestrator's inline
    AWAITING_LOCATION turn, where the user types a location as a normal chat
    message rather than filling a form field.

    Only a comma (the natural way people write "district, state") is treated
    as a separator; a bare "Vellore" is passed through as district-only and
    left to `infer_state` to resolve.
    """
    cleaned = text.strip()
    if "," in cleaned:
        district, _, state = cleaned.partition(",")
        return district.strip(), (state.strip() or None)
    return cleaned, None


def ambiguous_candidates(district: str) -> list[str] | None:
    """Returns candidate states if *district* is known to be ambiguous, else None."""
    key = normalize(district).replace(" ", "")
    entry = _load()["ambiguous_districts"].get(key)
    return list(entry) if entry else None


async def infer_state(ai_service: AIService, district: str) -> tuple[str | None, list[str]]:
    """Infer the state for *district*.

    Returns (state, candidates):
    - (state, []) if confidently and validly resolved
    - (None, candidates) if the district is ambiguous or could not be resolved,
      where candidates is a non-empty list when known, else empty
    """
    ambiguous = ambiguous_candidates(district)
    if ambiguous:
        return None, ambiguous

    valid_names = all_state_names()
    prompt = (
        f"Which Indian state or union territory is the district \"{district}\" located in? "
        f"Reply with ONLY the exact state/UT name, chosen from this list, and nothing else:\n"
        f"{', '.join(valid_names)}\n"
        f"If you are not confident, or the district could belong to more than one of these, "
        f"reply with exactly: UNKNOWN"
    )
    try:
        text, _ = await ai_service.generate_text(prompt)
    except AllProvidersFailedError as e:
        logger.warning("State inference failed (both providers down) for %r: %s", district, e)
        return None, []

    candidate = text.strip().strip(".")
    if candidate.upper() == "UNKNOWN":
        return None, []
    if is_valid_state(candidate):
        # Return the canonical casing, not necessarily the model's casing.
        for name in valid_names:
            if normalize(name) == normalize(candidate):
                return name, []
    logger.warning("AI returned an unvalidatable state %r for district %r", candidate, district)
    return None, []
