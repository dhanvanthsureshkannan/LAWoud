"""Guardrail against overclaiming in legal-assistance responses.

The application must never claim to identify the "best" or "top" lawyer, or
guarantee an outcome — it presents relevance-ranked, publicly available
information only. This is enforced in code, not just in prompt instructions,
because prompt instructions can be defeated by model drift; a mechanical
check cannot.
"""

import re

BANNED_PHRASES: tuple[str, ...] = (
    "best lawyer",
    "best advocate",
    "top lawyer",
    "top advocate",
    "most successful lawyer",
    "most successful advocate",
    "guaranteed lawyer",
    "guaranteed win",
    "guaranteed outcome",
    "number one lawyer",
    "#1 lawyer",
    "highest rated lawyer",
)

STANDARD_DISCLAIMER = (
    "Relevant advocates identified from publicly available case information. "
    "This is a relevance-based list built from public judicial and legal-aid records, "
    "not a ranking of lawyer quality, and not a guarantee of any case outcome. "
    "Please verify credentials independently before engaging any advocate."
)

DIRECTORY_DISCLAIMER = (
    "Advocates listed from LAWoud's curated directory of publicly reported professional "
    "profiles — not a live search of court records, and not a ranking of lawyer quality. "
    "Please verify credentials independently before engaging any advocate."
)

# Used when the search returned no advocates. The standard disclaimer claims
# advocates *were* identified, which would contradict an empty result.
NO_RESULTS_DISCLAIMER = (
    "No advocates could be identified from the publicly available case information "
    "we are able to search. This reflects the limits of what is publicly indexed — "
    "it is not a statement about how many advocates practise in your area. "
    "The official legal-aid services below can help you directly."
)

RELEVANCE_REASON_TEMPLATE = (
    "Advocate with publicly available experience relevant to your legal matter "
    "in this jurisdiction."
)

_BANNED_RE = re.compile(
    "|".join(re.escape(p) for p in BANNED_PHRASES),
    re.IGNORECASE,
)


def contains_banned_phrase(text: str) -> str | None:
    """Return the first banned phrase found in *text*, or None if it's clean."""
    if not text:
        return None
    m = _BANNED_RE.search(text)
    return m.group(0) if m else None


def assert_clean(text: str) -> None:
    """Raise if *text* contains a banned overclaiming phrase.

    Intended to be called on any user-facing string this service produces,
    so a violation fails loudly during development rather than shipping.
    """
    hit = contains_banned_phrase(text)
    if hit:
        raise ValueError(f"Banned overclaiming phrase found in output: {hit!r}")
