"""Curated advocate directory: local fallback when the live judicial-record
search in :mod:`app.services.advocate_service` turns up nothing.

The supplied file mixes THREE authoring passes in one document:

* a plain-text section (Chennai, Vellore) with bare ``Label:`` lines and bare
  one-line city/category/name headers, no Markdown markup at all;
* a Markdown section (a Vellore expansion) that is the same shape but with
  every ``#``/``*`` backslash-escaped (``\\## Name``, ``\\*\\*Speciality:\\*\\*``)
  — a leftover from whatever tool rendered a markdown preview into the file;
* a clean Markdown section (Delhi, Lucknow) using ``# City``, ``## Category``,
  ``### Name`` headings and ``**Label:**`` bold fields, with leftover
  ``:contentReference[...]`` citation artifacts from the research tool that
  produced it.

All three are handled by one tolerant, line-driven parser: backslash-escapes
are undone and Markdown markup is stripped before matching, so the same
label/heading logic works on every format. There is no separate "state" field
anywhere in the file — advocates are only located by city — so matching here
is city-only; a district with no matching city simply yields nothing and the
caller falls through to the national legal-aid contacts, exactly as an absent
file would.

**This module must never raise because the file is missing or malformed** —
that is the entire point of it being a *fallback*.
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.core.text import normalize
from app.core.wording import assert_clean
from app.models.schemas import AdvocateResult, MatchScope

logger = logging.getLogger("lawoud.lawyer_directory_service")

_MAX_RESULTS = 6

# Undoes "\## " / "\*\*...\*\*" backslash-escaping seen in the Vellore-expansion
# block, so it normalizes through the same path as real, unescaped markdown.
_UNESCAPE_RE = re.compile(r"\\([#*])")
# Strips leading #/blank/asterisks and trailing asterisks/whitespace from a
# line, so "### Name", "**Label:**  " and bare "Label:" all normalize the same way.
_MARKUP_RE = re.compile(r"^#{0,6}\s*\**\s*(.*?)\s*\**\s*$")
_LABEL_RE = re.compile(r"^([A-Za-z][A-Za-z/ ]{1,60}?)\s*:\s*(.*)$")
_ARTIFACT_RE = re.compile(r":contentReference\[[^\]]*\]\{[^}]*\}")

_LABEL_MAP: dict[str, str] = {
    "speciality": "practice_areas",
    "specialty": "practice_areas",
    "city": "city",
    "high court / bench": "court",
    "experience": "experience",
    "cases handled / case activity": "case_activity",
    "case types": "case_types",
    "professional mobile": "contact",
    "office / location": "office",
    "sources": "sources",
}


@dataclass
class DirectoryEntry:
    name: str
    city: str = ""
    category_heading: str = ""
    practice_areas: list[str] = field(default_factory=list)
    court: str = ""
    experience: str = ""
    case_activity: str = ""
    case_types: str = ""
    contact: str = ""
    office: str = ""
    sources: str = ""


def _strip_markup(line: str) -> str:
    return _MARKUP_RE.match(line).group(1).strip()


def parse(text: str) -> list[DirectoryEntry]:
    """Parse the directory file into one entry per advocate-per-practice-area block."""
    entries: list[DirectoryEntry] = []
    pending_headings: list[str] = []
    fields: dict[str, list[str]] = {}
    current_field: str | None = None
    # Whether `current_field` has captured any content line yet. Needed because
    # one of the three formats mixed into this file puts a blank line between a
    # label and its own value (`**Speciality:**\n\n Criminal Law; ...`) — a
    # blank must only end a field that has already started, never the gap
    # between a fresh label and its first content line.
    field_has_content = False
    name = category_heading = ""

    def flush() -> None:
        if not name or not fields:
            return
        entries.append(
            DirectoryEntry(
                name=name,
                city=" ".join(fields.get("city", [])).strip(),
                category_heading=category_heading,
                practice_areas=[
                    p.strip()
                    for p in re.split(r"[;,]", " ".join(fields.get("practice_areas", [])))
                    if p.strip()
                ],
                court=" ".join(fields.get("court", [])).strip(),
                experience=" ".join(fields.get("experience", [])).strip(),
                case_activity=" ".join(fields.get("case_activity", [])).strip(),
                case_types=" ".join(fields.get("case_types", [])).strip(),
                contact=" ".join(fields.get("contact", [])).strip(),
                office=" ".join(fields.get("office", [])).strip(),
                sources=_ARTIFACT_RE.sub("", " ".join(fields.get("sources", []))).strip(),
            )
        )

    for raw_line in text.splitlines():
        stripped = _UNESCAPE_RE.sub(r"\1", raw_line.strip())

        if not stripped or stripped == "---":
            # Only close a field that has actually started — a blank line
            # sitting between a label and its own first content line must not
            # end the field early (see `field_has_content` above). A "---"
            # rule is always a no-op: by the time one appears, the preceding
            # field has already been closed by the blank line before it.
            if current_field is not None and field_has_content:
                current_field = None
            continue

        clean = _strip_markup(stripped)
        match = _LABEL_RE.match(clean) if clean else None
        canonical = _LABEL_MAP.get(match.group(1).strip().lower()) if match else None

        if match:
            if current_field is None and pending_headings:
                # First label of a new block: flush the previous one and open this
                # one using whatever short heading lines led up to it. The file
                # nests up to three deep (city, category, name); only the name is
                # required, the rest degrade gracefully when shallower.
                flush()
                name = pending_headings[-1]
                category_heading = pending_headings[-2] if len(pending_headings) >= 2 else ""
                fields = {}
                pending_headings = []
            value = match.group(2).strip()
            current_field = canonical or "_ignore"
            field_has_content = bool(value)
            if canonical:
                fields.setdefault(canonical, [])
                if value:
                    fields[canonical].append(value)
            continue

        if current_field == "_ignore":
            field_has_content = True
            continue
        if current_field:
            fields[current_field].append(_ARTIFACT_RE.sub("", clean).strip())
            field_has_content = True
            continue

        # Not a label, not mid-field: a candidate city/category/name heading line.
        if not clean.startswith(":contentReference"):
            pending_headings.append(clean)
            if len(pending_headings) > 3:
                pending_headings.pop(0)

    flush()
    logger.info("Parsed %d lawyer directory entries", len(entries))
    return entries


class LawyerDirectoryService:
    """Hot-reloading wrapper, mirroring KnowledgeService's mtime-check pattern."""

    def __init__(self, path: Path):
        self._path = path
        self._entries: list[DirectoryEntry] = []
        self._mtime: float | None = None
        self.reload_if_changed()

    @property
    def is_available(self) -> bool:
        return bool(self._entries)

    @property
    def entry_count(self) -> int:
        return len(self._entries)

    def reload_if_changed(self) -> bool:
        if not self._path.exists():
            if self._mtime is None:
                logger.info(
                    "Lawyer directory %s not found; that fallback tier will be empty "
                    "until the file is added.",
                    self._path,
                )
                self._mtime = -1.0
            return False

        mtime = self._path.stat().st_mtime
        if self._mtime is not None and mtime == self._mtime:
            return False

        try:
            text = self._path.read_text(encoding="utf-8")
            self._entries = parse(text)
        except Exception:
            logger.exception("Failed to parse lawyer directory %s; keeping previous entries.", self._path)
            return False

        self._mtime = mtime
        return True

    def find(
        self,
        *,
        district: str,
        legal_category: str,
        case_type: str | None,
    ) -> tuple[list[AdvocateResult], MatchScope]:
        """City-only match (see module docstring — the file has no state field),
        ranked by practice-area overlap with the requested category/case type."""
        self.reload_if_changed()
        if not self._entries:
            return [], MatchScope.NONE

        district_key = normalize(district)
        category_terms = {t for t in legal_category.lower().split() if len(t) > 3}
        if case_type:
            category_terms.update(t for t in case_type.lower().split() if len(t) > 3)

        matched = [e for e in self._entries if normalize(e.city) == district_key]
        if not matched:
            return [], MatchScope.NONE

        scored: list[tuple[float, DirectoryEntry]] = []
        for entry in matched:
            entry_terms = " ".join(entry.practice_areas + [entry.category_heading]).lower()
            overlap = sum(1 for term in category_terms if term in entry_terms)
            scored.append((3.0 + overlap * 2.0, entry))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        any_category_match = any(overlap for overlap, _ in scored if overlap > 3.0)
        scope = MatchScope.DISTRICT_CATEGORY if any_category_match else MatchScope.DISTRICT_ONLY

        results: list[AdvocateResult] = []
        for score, entry in scored[:_MAX_RESULTS]:
            reason_bits = [f"Listed in the LAWoud curated advocate directory for {entry.city}"]
            if entry.category_heading:
                reason_bits.append(f"under {entry.category_heading}")
            reason = " ".join(reason_bits) + "."
            if entry.sources:
                reason += f" Noted source: {entry.sources[:200]}"
            assert_clean(reason)

            results.append(
                AdvocateResult(
                    name=entry.name,
                    relevant_area=entry.category_heading or (legal_category.title() if legal_category else "General"),
                    district=entry.city or district,
                    court_or_jurisdiction=entry.court,
                    public_case_count=0,
                    relevance_score=score,
                    relevance_reason=reason,
                    verification_sources=[],
                )
            )
        return results, scope
