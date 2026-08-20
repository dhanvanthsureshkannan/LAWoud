"""Parser for the Constitution of India Markdown file.

The source file (``General provisions all.md``) contains no Markdown headings at
all, so the generic heading-based parser in :mod:`app.services.knowledge_service`
cannot see article boundaries — it would blind-chunk 500 KB of text and label
every citation "Document". This module reads the file's *actual* structure
instead: each article begins on a line like

    Article 22 — Protection against arrest and detention in certain cases — Right to Freedom

followed by ``Label: value`` blocks. The file was authored in three passes and
uses three different sets of labels for the same concepts (``Simple:`` vs
``Simple Explanation:``, ``Related:`` vs ``Related Articles:``, and so on), so
labels are matched case-insensitively against a synonym table.

Output is a list of the same ``KnowledgeSection`` objects the generic parser
produces, so scoring, citations and context blocks downstream are unchanged.
"""

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.knowledge_service import KnowledgeSection

logger = logging.getLogger("lawoud.constitution_parser")

CORPUS_NAME = "constitution"
INDIA_CODE_URL = "https://www.indiacode.nic.in/"

# An article heading must use a DASH separator. This matters: sub-clauses listed
# inside a body use a colon ("Article 39(a): Adequate means of livelihood...")
# and must stay part of their parent article, while genuinely separate clause
# entries use a dash ("Article 51A(a) — Respect for the Constitution...").
_ARTICLE_RE = re.compile(
    r"^\**\s*Article\s+(\d+[A-Z]{0,3}(?:\([a-z0-9]+\))?)\s*[—–-]\s*(.+?)\s*\**\s*$"
)
# The file's very first entry is the one bold-italic outlier, with the title in
# parentheses instead of after a dash: ***Article 12(Definition — General)***
_ARTICLE_PAREN_RE = re.compile(r"^\**\s*Article\s+(\d+[A-Z]{0,3})\((.+?)\)\s*\**\s*$")

_LABEL_RE = re.compile(r"^\**\s*([A-Za-z][A-Za-z /]{2,45}?)\s*\**\s*:\s*(.*)$")

# Canonical field <- every label spelling that appears in the file.
_LABEL_SYNONYMS: dict[str, str] = {
    "accurate explanation": "explanation",
    "law": "explanation",
    "simple": "simple",
    "simple explanation": "simple",
    "applies to": "applies",
    "applies to / conditions / relevance": "applies",
    "conditions": "applies",
    "practical relevance": "applies",
    "important exceptions": "exceptions",
    "exceptions / limitations": "exceptions",
    "important conditions": "exceptions",
    "important notes": "exceptions",
    "common misunderstanding": "exceptions",
    "important warning": "warning",
    "related": "related",
    "related provisions": "related",
    "related articles": "related",
    "related acts / procedures": "related",
    "status": "status",
    "category": "category",
    "type": "category",
    "provision type": "category",
    "what changed": "notes",
    "source": "source",
    "official sources": "source",
    "last verified": "verified",
}

# Body order. "simple" leads because it is the plain-language text the answer
# prompt is meant to paraphrase; the formal wording follows as backing.
_BODY_ORDER: list[tuple[str, str]] = [
    ("simple", "In plain language"),
    ("explanation", "What the Article says"),
    ("applies", "Applies to / conditions"),
    ("exceptions", "Exceptions and limitations"),
    ("warning", "Important warning"),
    ("notes", "Notes"),
    ("related", "Related provisions"),
]

# Articles whose Status says they were repealed. Never retrieved by default —
# citing a removed Article as live law is the worst failure this system can make.
_OMITTED_RE = re.compile(r"omitted|repealed|historical", re.IGNORECASE)


def is_omitted_status(status: str) -> bool:
    return bool(status) and bool(_OMITTED_RE.search(status))


def parse(text: str) -> list["KnowledgeSection"]:
    """Parse the Constitution Markdown *text* into one section per article."""
    from app.services.knowledge_service import KnowledgeSection

    raw_blocks = _split_into_articles(text)
    sections: list[KnowledgeSection] = []
    seen_ordinals: dict[str, int] = {}
    seen_fingerprints: set[str] = set()

    for number, heading_rest, body_lines in raw_blocks:
        title_text, group = _split_title_and_group(heading_rest)
        fields = _extract_fields(body_lines)
        body = _render_body(fields)
        if not body.strip():
            continue

        # The file repeats a few blocks verbatim (Article 51A's intro appears
        # twice). Drop exact duplicates rather than double-weighting them.
        fingerprint = f"{number}|{title_text}|{body[:400]}"
        if fingerprint in seen_fingerprints:
            continue
        seen_fingerprints.add(fingerprint)

        # Article numbers are NOT unique (51A heads 14 clause entries), so the
        # stable key carries an occurrence ordinal.
        ordinal = seen_ordinals.get(number, 0) + 1
        seen_ordinals[number] = ordinal

        label = f"Article {number}"
        title = f"{label} — {title_text}" if title_text else label
        breadcrumb = " > ".join(p for p in ("Constitution of India", group, label) if p)

        sections.append(
            KnowledgeSection(
                breadcrumb=breadcrumb if ordinal == 1 else f"{breadcrumb} ({ordinal})",
                title=title,
                body=body,
                level=2,
                topic=group or "Constitution of India",
                meta_keywords=_build_keywords(number, title_text, group, fields),
                law=f"Constitution of India, {label}",
                source_name=f"Constitution of India, {label}",
                source_url=INDIA_CODE_URL,
                corpus=CORPUS_NAME,
                article_number=number,
                status=fields.get("status", ""),
            )
        )

    logger.info("Parsed %d constitution article sections", len(sections))
    return sections


def _split_into_articles(text: str) -> list[tuple[str, str, list[str]]]:
    """Slice *text* at article headings -> (number, heading_remainder, body_lines)."""
    blocks: list[tuple[str, str, list[str]]] = []
    number = heading_rest = ""
    current: list[str] = []
    started = False

    for line in text.splitlines():
        stripped = line.strip()
        match = _ARTICLE_RE.match(stripped) if stripped else None
        paren_match = None if match else (_ARTICLE_PAREN_RE.match(stripped) if stripped else None)

        if match or paren_match:
            if started:
                blocks.append((number, heading_rest, current))
            m = match or paren_match
            number, heading_rest = m.group(1), m.group(2).strip()
            current = []
            started = True
        elif started:
            current.append(line)
        # Text before the first article heading is a file preamble — discarded.

    if started:
        blocks.append((number, heading_rest, current))
    return blocks


def _split_title_and_group(heading_rest: str) -> tuple[str, str]:
    """Split "Protection against arrest — Right to Freedom" into (title, group).

    Only the LAST dash-separated segment is treated as a thematic group, and only
    when it is short — many article titles legitimately contain a dash
    ("Laws inconsistent with or in derogation of Fundamental Rights — General").
    """
    parts = [p.strip() for p in re.split(r"\s+[—–]\s+", heading_rest) if p.strip()]
    if len(parts) >= 2 and len(parts[-1]) <= 60:
        group = parts[-1]
        title = " — ".join(parts[:-1])
        return title, ("" if group.lower() == "general" else group)
    return heading_rest, ""


def _extract_fields(body_lines: list[str]) -> dict[str, str]:
    """Collect ``Label: value`` blocks into canonical fields.

    A label with an empty inline value (``Exceptions / Limitations:`` followed by
    a blank line) keeps absorbing subsequent paragraphs until the next label, so
    those multi-paragraph blocks are not lost.
    """
    fields: dict[str, list[str]] = {}
    current: str | None = None

    for line in body_lines:
        stripped = line.strip()
        if not stripped or stripped == ".":
            continue

        match = _LABEL_RE.match(stripped)
        canonical = _LABEL_SYNONYMS.get(match.group(1).strip().lower()) if match else None
        if canonical:
            current = canonical
            value = match.group(2).strip()
            fields.setdefault(canonical, [])
            if value:
                fields[canonical].append(value)
            continue

        # Unlabelled prose: continuation of the field in progress, or — when the
        # article opens with bare prose — the explanation.
        target = current or "explanation"
        fields.setdefault(target, []).append(stripped)

    return {k: " ".join(v).strip() for k, v in fields.items() if v}


def _render_body(fields: dict[str, str]) -> str:
    parts = [f"{heading}: {fields[key]}" for key, heading in _BODY_ORDER if fields.get(key)]
    return "\n\n".join(parts)


def _build_keywords(number: str, title: str, group: str, fields: dict[str, str]) -> list[str]:
    """Keywords that let both "Article 22" and "arrest" reach this section."""
    keywords = [f"article {number}".lower(), f"art {number}".lower(), number.lower()]
    base = re.sub(r"\([a-z0-9]+\)", "", number).strip()
    if base and base.lower() != number.lower():
        keywords.append(f"article {base}".lower())
    for source in (title, group, fields.get("category", "")):
        keywords.extend(w for w in re.split(r"[\s,;/]+", source.lower()) if len(w) > 3)
    seen: dict[str, None] = {}
    for k in keywords:
        if k:
            seen.setdefault(k, None)
    return list(seen)
