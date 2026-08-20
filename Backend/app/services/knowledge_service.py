"""Local Markdown knowledge corpus: parse, index, search, sufficiency gate.

Two files are loaded side by side and searched as one corpus:

* the Constitution of India file, which has no Markdown headings and is parsed
  per-Article by :mod:`app.services.constitution_parser`;
* a heading-structured guide file (``data/legal_knowledge.md``) covering the
  procedural topics the Constitution does not — FIR filing, tenancy, cheque
  bounce and so on — parsed by the generic heading parser below.

The generic parser works on PLAIN markdown with nothing but headings; metadata
lines are an optional scoring boost, never a requirement. Both files hot-reload
independently on mtime change, so either can be swapped mid-demo without a
restart.
"""

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app.config import Settings
from app.core.text import normalize
from app.services import constitution_parser

logger = logging.getLogger("lawoud.knowledge_service")

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_META_RE = re.compile(r"^\*\*(Topic|Keywords|Law|Source)\s*:?\s*\*\*\s*:?\s*(.*\S)\s*$", re.IGNORECASE)

_FIELD_WEIGHTS = {"title": 3.0, "meta_keywords": 2.5, "meta_topic": 2.0, "body": 1.0}
_MAX_BODY_HITS_PER_TERM = 3
_PHRASE_MATCH_BONUS = 2.0

# A query naming an Article explicitly ("what does Article 21 say") must return
# that Article itself, not the dozens of sections that merely cross-reference it.
# This has to outweigh any accumulation of ordinary keyword hits.
_ARTICLE_EXACT_BONUS = 25.0
_ARTICLE_MENTION_RE = re.compile(r"\b(?:article|art\.?)\s*(\d+[A-Za-z]{0,3})\b", re.IGNORECASE)


@dataclass
class KnowledgeSection:
    breadcrumb: str  # e.g. "Criminal Law > FIR > How to File"
    title: str  # last heading segment, used as the citation title
    body: str
    level: int
    topic: str = ""
    meta_keywords: list[str] = field(default_factory=list)
    law: str = ""
    source_name: str = ""
    source_url: str | None = None
    # Which file this came from, so the frontend can tell a constitutional
    # Article apart from a procedural how-to note.
    corpus: str = "guide"
    article_number: str = ""  # constitution corpus only, e.g. "22", "51A(a)"
    status: str = ""  # constitution corpus only, e.g. "Active", "Omitted / Historical"

    @property
    def citation_label(self) -> str:
        return self.source_name or self.breadcrumb


@dataclass
class ScoredSection:
    section: KnowledgeSection
    score: float
    coverage: float  # fraction of query keywords matched anywhere in this section


class KnowledgeSource:
    """One Markdown file plus the parser that understands its layout."""

    def __init__(self, path: Path, parser: Callable[[str], list[KnowledgeSection]], label: str):
        self.path = path
        self.parser = parser
        self.label = label
        self.sections: list[KnowledgeSection] = []
        self.mtime: float | None = None


class KnowledgeService:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._last_loaded: datetime | None = None
        self._sources: list[KnowledgeSource] = [
            KnowledgeSource(
                settings.constitution_path,
                constitution_parser.parse,
                constitution_parser.CORPUS_NAME,
            ),
            KnowledgeSource(
                settings.knowledge_path,
                lambda text: self._parse(text, settings.knowledge_max_section_chars),
                "guide",
            ),
        ]
        self.reload_if_changed()

    # -- public API -----------------------------------------------------

    @property
    def _sections(self) -> list[KnowledgeSection]:
        return [s for source in self._sources for s in source.sections]

    @property
    def section_count(self) -> int:
        return len(self._sections)

    @property
    def section_counts(self) -> dict[str, int]:
        """Per-file section counts, so a mis-parsed file is obvious at a glance."""
        return {source.label: len(source.sections) for source in self._sources}

    @property
    def last_loaded(self) -> datetime | None:
        return self._last_loaded

    @property
    def file_exists(self) -> bool:
        """True only when every configured source file is present."""
        return all(source.path.exists() for source in self._sources)

    @property
    def file_mtime(self) -> datetime | None:
        """Most recent mtime across all sources."""
        mtimes = [s.mtime for s in self._sources if s.mtime is not None and s.mtime > 0]
        return datetime.fromtimestamp(max(mtimes), tz=timezone.utc) if mtimes else None

    @property
    def file_paths(self) -> list[str]:
        return [str(source.path) for source in self._sources]

    def reload_if_changed(self) -> bool:
        """Re-parse any source file that changed on disk. True if anything reloaded."""
        reloaded = any([self._reload_source(source) for source in self._sources])
        if reloaded:
            self._last_loaded = datetime.now(timezone.utc)
        return reloaded

    def _reload_source(self, source: KnowledgeSource) -> bool:
        if not source.path.exists():
            if source.sections:
                logger.warning(
                    "Knowledge file %s no longer exists; keeping last-loaded data.", source.path
                )
            elif source.mtime is None:
                # Log the miss once, not on every request that calls reload.
                source.mtime = -1.0
                logger.warning("Knowledge file %s not found; that source is empty.", source.path)
            return False

        mtime = source.path.stat().st_mtime
        if source.mtime is not None and mtime == source.mtime:
            return False

        try:
            text = source.path.read_text(encoding="utf-8")
        except OSError as e:
            logger.error("Failed to read knowledge file %s: %s", source.path, e)
            return False

        try:
            source.sections = source.parser(text)
        except Exception:
            # A malformed file must not take the rest of the corpus down with it.
            logger.exception(
                "Failed to parse knowledge file %s; keeping previous sections.", source.path
            )
            return False

        source.mtime = mtime
        logger.info("Loaded %d %s sections from %s", len(source.sections), source.label, source.path)
        return True

    def search(self, keywords: list[str], *, top_k: int | None = None) -> list[ScoredSection]:
        """Rank sections by relevance to *keywords*. Empty keywords -> empty result."""
        self.reload_if_changed()
        if not keywords or not self._sections:
            return []

        top_k = top_k or self._settings.knowledge_top_k
        norm_keywords = [normalize(k) for k in keywords if normalize(k)]
        if not norm_keywords:
            return []

        wanted_articles = self._articles_mentioned(norm_keywords)

        scored: list[ScoredSection] = []
        for section in self._sections:
            # Never surface a repealed Article. Presenting removed text as live
            # law is the most damaging mistake this system could make, so the
            # filter lives here rather than in a prompt instruction.
            if not self._settings.include_omitted_articles and constitution_parser.is_omitted_status(
                section.status
            ):
                continue
            score, coverage = self._score_section(section, norm_keywords)
            if section.article_number and section.article_number.lower() in wanted_articles:
                score += _ARTICLE_EXACT_BONUS
                coverage = 1.0
            if score > 0:
                scored.append(ScoredSection(section=section, score=score, coverage=coverage))

        scored.sort(key=lambda s: s.score, reverse=True)
        return scored[:top_k]

    def is_sufficient(self, scored: list[ScoredSection]) -> bool:
        """Sufficiency gate deciding local-knowledge vs. web-search fallback."""
        if not scored:
            return False
        best = scored[0]
        total_chars = sum(len(s.section.body) for s in scored)
        return (
            best.score >= self._settings.knowledge_min_score
            and best.coverage >= self._settings.knowledge_min_coverage
            and total_chars >= self._settings.knowledge_min_context_chars
        )

    # -- scoring ----------------------------------------------------------

    @staticmethod
    def _articles_mentioned(norm_keywords: list[str]) -> set[str]:
        """Article numbers named explicitly in the query, e.g. {"21", "51a"}.

        The analysis stage often splits "Article 21" into two keywords, so the
        joined keyword string is searched rather than each keyword alone.
        """
        return {
            m.group(1).lower() for m in _ARTICLE_MENTION_RE.finditer(" ".join(norm_keywords))
        }

    def _score_section(
        self, section: KnowledgeSection, norm_keywords: list[str]
    ) -> tuple[float, float]:
        title_norm = normalize(section.title)
        topic_norm = normalize(section.topic)
        meta_kw_norm = [normalize(k) for k in section.meta_keywords]
        body_norm = normalize(section.body)

        score = 0.0
        matched = 0
        for kw in norm_keywords:
            hit = False
            if kw in title_norm:
                score += _FIELD_WEIGHTS["title"]
                hit = True
            if any(kw == mk or kw in mk for mk in meta_kw_norm):
                score += _FIELD_WEIGHTS["meta_keywords"]
                hit = True
            if kw in topic_norm:
                score += _FIELD_WEIGHTS["meta_topic"]
                hit = True
            body_hits = min(body_norm.count(kw), _MAX_BODY_HITS_PER_TERM) if len(kw) >= 3 else 0
            if body_hits:
                score += _FIELD_WEIGHTS["body"] * body_hits
                hit = True
            if hit:
                matched += 1

        # Whole-phrase bonus: keywords joined as a phrase appearing verbatim.
        phrase = " ".join(norm_keywords)
        if len(norm_keywords) > 1 and (phrase in title_norm or phrase in body_norm):
            score += _PHRASE_MATCH_BONUS

        coverage = matched / len(norm_keywords) if norm_keywords else 0.0
        return score, coverage

    # -- parsing ------------------------------------------------------------

    @staticmethod
    def _parse(text: str, max_section_chars: int) -> list[KnowledgeSection]:
        lines = text.splitlines()

        # Decide split level: prefer "##" if present anywhere, else "#".
        levels_present = {
            len(m.group(1))
            for line in lines
            if (m := _HEADING_RE.match(line))
        }
        if not levels_present:
            # No headings at all -- treat the whole file as one section.
            body = text.strip()
            if not body:
                return []
            return KnowledgeService._split_oversized(
                KnowledgeSection(breadcrumb="Document", title="Document", body=body, level=0),
                max_section_chars,
            )
        split_level = min(2, max(levels_present)) if 2 in levels_present else min(levels_present)

        sections: list[KnowledgeSection] = []
        heading_stack: dict[int, str] = {}
        current_title = ""
        current_level = split_level
        current_lines: list[str] = []

        def flush() -> None:
            body = "\n".join(current_lines).strip()
            if not current_title and not body:
                return
            # A heading shallower than the split level is a document container
            # (e.g. the file's H1 title). Its body is front-matter/instructions,
            # not legal content, so it must not become a searchable, citable
            # section — otherwise the file's own preamble shows up as a source.
            if current_level < split_level:
                return
            breadcrumb_parts = [heading_stack[lvl] for lvl in sorted(heading_stack) if lvl <= current_level]
            breadcrumb = " > ".join(breadcrumb_parts) if breadcrumb_parts else current_title
            section, meta_body = KnowledgeService._extract_metadata(body)
            section.breadcrumb = breadcrumb or current_title or "Document"
            if breadcrumb_parts:
                section.title = current_title or breadcrumb_parts[-1]
            else:
                section.title = "Document"
            section.body = meta_body
            section.level = current_level
            if section.title or section.body:
                sections.extend(
                    KnowledgeService._split_oversized(section, max_section_chars)
                )

        for line in lines:
            m = _HEADING_RE.match(line)
            if m:
                level, heading_text = len(m.group(1)), m.group(2).strip()
                if level <= split_level:
                    flush()
                    current_title = heading_text
                    current_level = level
                    current_lines = []
                    # Clear deeper levels from the breadcrumb stack, set this one.
                    heading_stack = {lvl: v for lvl, v in heading_stack.items() if lvl < level}
                    heading_stack[level] = heading_text
                else:
                    # Sub-heading within a section: keep as content, track in breadcrumb too.
                    heading_stack = {lvl: v for lvl, v in heading_stack.items() if lvl < level}
                    heading_stack[level] = heading_text
                    current_lines.append(line)
            else:
                current_lines.append(line)
        flush()

        return sections

    @staticmethod
    def _extract_metadata(body: str) -> tuple[KnowledgeSection, str]:
        """Pull optional **Topic:**/**Keywords:**/**Law:**/**Source:** lines out of body."""
        section = KnowledgeSection(breadcrumb="", title="", body="", level=0)
        remaining_lines = []
        for line in body.splitlines():
            m = _META_RE.match(line.strip())
            if not m:
                remaining_lines.append(line)
                continue
            field_name, value = m.group(1).lower(), m.group(2).strip()
            if field_name == "topic":
                section.topic = value
            elif field_name == "keywords":
                section.meta_keywords = [k.strip() for k in re.split(r"[,;]", value) if k.strip()]
            elif field_name == "law":
                section.law = value
            elif field_name == "source":
                if "|" in value:
                    name, _, url = value.partition("|")
                    section.source_name = name.strip()
                    section.source_url = url.strip() or None
                else:
                    section.source_name = value
        return section, "\n".join(remaining_lines).strip()

    @staticmethod
    def _split_oversized(section: KnowledgeSection, max_chars: int) -> list[KnowledgeSection]:
        """Split a section's body on paragraph boundaries if it exceeds max_chars."""
        if len(section.body) <= max_chars:
            return [section]

        paragraphs = re.split(r"\n\s*\n", section.body)
        chunks: list[str] = []
        current = ""
        for para in paragraphs:
            candidate = f"{current}\n\n{para}" if current else para
            if len(candidate) > max_chars and current:
                chunks.append(current)
                current = para
            else:
                current = candidate
        if current:
            chunks.append(current)

        if len(chunks) <= 1:
            return [section]

        result = []
        for i, chunk in enumerate(chunks):
            part = KnowledgeSection(
                breadcrumb=f"{section.breadcrumb} (part {i + 1})",
                title=section.title,
                body=chunk,
                level=section.level,
                topic=section.topic,
                meta_keywords=section.meta_keywords,
                law=section.law,
                source_name=section.source_name,
                source_url=section.source_url,
            )
            result.append(part)
        return result
