"""Local Markdown knowledge base: parse, index, search, sufficiency gate.

Designed to work on PLAIN markdown with nothing but headings — metadata lines
are an optional scoring boost, never a requirement, since the real knowledge
file is supplied by the user after this is built. Hot-reloads on file mtime
change so the file can be swapped mid-demo without restarting the server.
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.config import Settings
from app.core.text import normalize

logger = logging.getLogger("lawoud.knowledge_service")

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_META_RE = re.compile(r"^\*\*(Topic|Keywords|Law|Source)\s*:?\s*\*\*\s*:?\s*(.*\S)\s*$", re.IGNORECASE)

_FIELD_WEIGHTS = {"title": 3.0, "meta_keywords": 2.5, "meta_topic": 2.0, "body": 1.0}
_MAX_BODY_HITS_PER_TERM = 3
_PHRASE_MATCH_BONUS = 2.0


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

    @property
    def citation_label(self) -> str:
        return self.source_name or self.breadcrumb


@dataclass
class ScoredSection:
    section: KnowledgeSection
    score: float
    coverage: float  # fraction of query keywords matched anywhere in this section


class KnowledgeService:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._sections: list[KnowledgeSection] = []
        self._mtime: float | None = None
        self._last_loaded: datetime | None = None
        self.reload_if_changed()

    # -- public API -----------------------------------------------------

    @property
    def section_count(self) -> int:
        return len(self._sections)

    @property
    def last_loaded(self) -> datetime | None:
        return self._last_loaded

    @property
    def file_exists(self) -> bool:
        return self._settings.knowledge_path.exists()

    @property
    def file_mtime(self) -> datetime | None:
        if self._mtime is None:
            return None
        return datetime.fromtimestamp(self._mtime, tz=timezone.utc)

    def reload_if_changed(self) -> bool:
        """Re-parse the knowledge file if it changed on disk. Returns True if reloaded."""
        path = self._settings.knowledge_path
        if not path.exists():
            if self._sections:
                logger.warning("Knowledge file %s no longer exists; keeping last-loaded data.", path)
            return False

        mtime = path.stat().st_mtime
        if self._mtime is not None and mtime == self._mtime:
            return False

        try:
            text = path.read_text(encoding="utf-8")
        except OSError as e:
            logger.error("Failed to read knowledge file %s: %s", path, e)
            return False

        self._sections = self._parse(text, self._settings.knowledge_max_section_chars)
        self._mtime = mtime
        self._last_loaded = datetime.now(timezone.utc)
        logger.info("Loaded %d knowledge sections from %s", len(self._sections), path)
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

        scored: list[ScoredSection] = []
        for section in self._sections:
            score, coverage = self._score_section(section, norm_keywords)
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
