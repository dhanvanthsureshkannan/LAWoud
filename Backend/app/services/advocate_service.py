"""Advocate discovery from publicly indexed judicial documents.

The literal eCourts "search by advocate name" feature is CAPTCHA-gated and is
never queried programmatically (see app.core.domains for the URLs we
deliberately do not touch). Instead: search publicly indexed judgment text via
Tavily (which does the crawling, so we never hand-scrape) across an official
+ Indian-Kanoon whitelist, extract COUNSEL names only (never party/litigant
names — a deliberate privacy boundary), group, and rank by relevance.

Progressive widening: if a tight query returns nothing, the search is widened
in stages and the response always reports which stage actually matched
(`match_scope`) so a widened result is never presented as an exact one.
"""

import io
import logging
import re
from dataclasses import dataclass, field

import httpx

from app.core.domains import JUDICIAL_RECORD_DOMAINS, is_official, source_name
from app.models.schemas import AdvocateResult, MatchScope, VerificationSource
from app.services.web_search_service import WebResult, WebSearchService

logger = logging.getLogger("lawoud.advocate_service")

_MAX_RESULTS_RETURNED = 8

# --- Counsel-name extraction --------------------------------------------------

_HONORIFICS = r"(?:Mr\.?|Ms\.?|Mrs\.?|Smt\.?|Shri\.?|Sh\.?|Dr\.?|Adv\.?)"
_NAME_TOKEN = r"[A-Z][a-zA-Z.']*"
# e.g. "Mr. R. K. Sharma", "Adv. Priya Nair", "Shri Anil Kumar Verma"
_NAME_PATTERN = rf"{_HONORIFICS}\s+((?:{_NAME_TOKEN}\s+){{1,3}}{_NAME_TOKEN})"

_COUNSEL_MARKERS = [
    rf"(?:learned\s+)?counsel\s+for\s+the\s+(?:petitioner|respondent|appellant|applicant|complainant|accused)s?\s*[:\-]?\s*{_NAME_PATTERN}",
    rf"for\s+the\s+(?:petitioner|respondent|appellant|applicant|complainant|accused)s?\s*[:\-]?\s*{_NAME_PATTERN}",
    rf"advocate\s+for\s+the\s+(?:petitioner|respondent|appellant|applicant)\s*[:\-]?\s*{_NAME_PATTERN}",
    rf"{_NAME_PATTERN},?\s+(?:learned\s+)?(?:counsel|advocate)\s+for",
    rf"(?:counsel|advocate)\s*[:\-]\s*{_NAME_PATTERN}",
]
_COUNSEL_RE = [re.compile(p, re.IGNORECASE) for p in _COUNSEL_MARKERS]

_REJECT_TOKENS = frozenset(
    """
    court justice bench union state high supreme district government
    public prosecutor india respondent petitioner appellant applicant
    complainant accused registrar judge honble hon'ble additional
    """.split()
)


@dataclass
class AdvocateProfile:
    name: str
    occurrences: int = 0
    district_hits: int = 0
    category_hits: int = 0
    case_titles: list[str] = field(default_factory=list)
    sources: list[VerificationSource] = field(default_factory=list)


def _valid_name(raw: str) -> str | None:
    """Normalize a candidate name; return None if it looks institutional/invalid."""
    cleaned = re.sub(r"\s+", " ", raw).strip(" .,")
    tokens = cleaned.split(" ")
    if not (2 <= len(tokens) <= 4):
        return None
    for tok in tokens:
        bare = tok.strip(".").lower()
        if bare in _REJECT_TOKENS:
            return None
    if not all(t[0].isupper() for t in tokens if t):
        return None
    return cleaned


def _dedupe_key(name: str) -> str:
    """Loose key so 'R. Kumar' and 'R Kumar' merge into one profile."""
    return re.sub(r"[.\s]+", "", name).lower()


def extract_advocate_names(text: str) -> list[str]:
    """Extract distinct counsel names appearing in *text*. Best-effort — judgment
    formatting varies widely, so this will legitimately miss names sometimes."""
    found: list[str] = []
    for pattern in _COUNSEL_RE:
        for m in pattern.finditer(text):
            name = _valid_name(m.group(1))
            if name:
                found.append(name)
    return found


def _build_query(
    district: str, legal_category: str, case_type: str | None, state: str | None, scope: MatchScope
) -> str:
    parts = [f'"{district}" district court']
    if scope in (MatchScope.DISTRICT_CASE_TYPE,) and case_type:
        parts.append(case_type)
    if scope in (MatchScope.DISTRICT_CASE_TYPE, MatchScope.DISTRICT_CATEGORY, MatchScope.STATE_CATEGORY):
        parts.append(f"{legal_category} case")
    if scope == MatchScope.STATE_CATEGORY and state:
        parts = [f'"{state}"', f"{legal_category} case", "judgment"]
    parts.append("judgment advocate counsel")
    return " ".join(parts)


async def find_advocates(
    web_search_service: WebSearchService,
    *,
    district: str,
    state: str | None,
    legal_category: str,
    case_type: str | None,
) -> tuple[list[AdvocateResult], MatchScope]:
    """Progressive widening search for advocates relevant to the case.

    Tries, in order: district+case_type -> district+category -> district_only
    -> state+category. Stops at the first stage that yields at least one
    advocate. Returns (results, match_scope) — match_scope is NONE if every
    stage came up empty, which the caller must treat as "do not fabricate".
    """
    if not web_search_service.is_configured:
        logger.warning("Tavily not configured; advocate search cannot run.")
        return [], MatchScope.NONE

    stages: list[MatchScope] = [MatchScope.DISTRICT_CASE_TYPE, MatchScope.DISTRICT_CATEGORY, MatchScope.DISTRICT_ONLY]
    if state:
        stages.append(MatchScope.STATE_CATEGORY)

    for scope in stages:
        if scope == MatchScope.DISTRICT_CASE_TYPE and not case_type:
            continue
        query = _build_query(district, legal_category, case_type, state, scope)
        results = await web_search_service.search(
            query,
            domains=JUDICIAL_RECORD_DOMAINS,
            max_results=10,
            include_raw_content=True,
        )
        advocates = _rank_advocates(
            results,
            district=district,
            state=state,
            legal_category=legal_category,
            case_type=case_type,
            scope=scope,
        )
        if advocates:
            return advocates, scope

    return [], MatchScope.NONE


def _rank_advocates(
    results: list[WebResult],
    *,
    district: str,
    state: str | None,
    legal_category: str,
    case_type: str | None,
    scope: MatchScope,
) -> list[AdvocateResult]:
    """Group extracted counsel names and score them.

    Geographic relevance is VERIFIED against the document text, never assumed
    from the query. A search for "Vellore" can legitimately return an Allahabad
    High Court judgment; presenting that advocate as relevant to Vellore would
    be misleading, so documents that don't actually mention the location are
    discarded rather than scored.
    """
    district_norm = district.strip().lower()
    state_norm = (state or "").strip().lower()
    category_terms = {t for t in legal_category.lower().split() if len(t) > 3}
    if case_type:
        category_terms.update(t for t in case_type.lower().split() if len(t) > 3)

    profiles: dict[str, AdvocateProfile] = {}

    for result in results:
        text = result.raw_content or result.content
        if not text:
            continue
        text_lower = text.lower()

        mentions_district = district_norm in text_lower
        mentions_state = bool(state_norm) and state_norm in text_lower

        # Geographic gate — discard documents that don't place the advocate in
        # the requested jurisdiction at the scope we're currently searching.
        if scope == MatchScope.STATE_CATEGORY:
            if not (mentions_district or mentions_state):
                continue
        elif not mentions_district:
            continue

        mentions_category = any(term in text_lower for term in category_terms)

        names = extract_advocate_names(text)
        for name in names:
            key = _dedupe_key(name)
            profile = profiles.setdefault(key, AdvocateProfile(name=name))
            profile.occurrences += 1
            if mentions_district:
                profile.district_hits += 1
            if mentions_category:
                profile.category_hits += 1
            if result.title not in profile.case_titles:
                profile.case_titles.append(result.title)
            profile.sources.append(
                VerificationSource(
                    title=result.title,
                    url=result.url,
                    source=result.source_name or source_name(result.url),
                    is_official=is_official(result.url),
                )
            )

    ranked: list[AdvocateResult] = []
    for profile in profiles.values():
        district_match = 3.0 if profile.district_hits else 0.0
        category_match = 3.0 if profile.category_hits else 0.0
        court_match = 2.0 if any(is_official(s.url) for s in profile.sources) else 0.0
        occurrence_score = min(profile.occurrences, 10)
        relevance = district_match + category_match + court_match + occurrence_score

        # Dedupe verification sources by URL while preserving order.
        seen_urls: set[str] = set()
        unique_sources = []
        for s in profile.sources:
            if s.url not in seen_urls:
                seen_urls.add(s.url)
                unique_sources.append(s)

        # Describe only what was actually verified in the source documents.
        location_clause = (
            f" mentioning {district}" if profile.district_hits else f" within {state or district}"
        )
        category_clause = f" {legal_category}" if profile.category_hits else ""
        reason = (
            f"Appears as counsel in {profile.occurrences} publicly available"
            f"{category_clause} case record(s){location_clause}."
        )

        ranked.append(
            AdvocateResult(
                name=profile.name,
                relevant_area=legal_category.title() if profile.category_hits else "General",
                district=district if profile.district_hits else (state or district),
                court_or_jurisdiction=next(
                    (s.source for s in unique_sources if s.is_official),
                    unique_sources[0].source if unique_sources else "",
                ),
                public_case_count=profile.occurrences,
                relevance_score=relevance,
                relevance_reason=reason,
                verification_sources=unique_sources[:3],
            )
        )

    ranked.sort(key=lambda a: a.relevance_score, reverse=True)
    return ranked[:_MAX_RESULTS_RETURNED]


# --- Optional: official DLSA/SLSA panel PDF extraction (best-effort) --------

async def fetch_official_pdf_text(url: str, *, timeout: float = 15.0) -> str:
    """Fetch and extract text from an official .gov.in/.nic.in PDF only.

    Never used for indiankanoon.org — direct fetch is reserved for official
    government documents (e.g. DLSA panel-advocate PDFs on the NIC CDN).
    """
    if not is_official(url):
        raise ValueError(f"Refusing direct fetch of non-official URL: {url}")

    try:
        import pypdf
    except ImportError:
        logger.warning("pypdf not installed; skipping PDF text extraction for %s", url)
        return ""

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        try:
            resp = await client.get(url, headers={"User-Agent": "LAWoud-hackathon-demo/1.0"})
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning("Failed to fetch official PDF %s: %s", url, e)
            return ""

    if "pdf" not in resp.headers.get("content-type", "").lower():
        return ""

    try:
        reader = pypdf.PdfReader(io.BytesIO(resp.content))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as e:  # pypdf can raise several distinct error types
        logger.warning("Failed to parse PDF %s: %s", url, e)
        return ""
