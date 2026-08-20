"""Normalizes both retrieval sources into one Citation shape for the frontend."""

from app.models.schemas import Citation, Origin
from app.services.knowledge_service import ScoredSection
from app.services.web_search_service import WebResult


def citations_from_knowledge(scored_sections: list[ScoredSection]) -> list[Citation]:
    citations = []
    for i, scored in enumerate(scored_sections, start=1):
        section = scored.section
        snippet = section.body.strip()
        if len(snippet) > 240:
            snippet = snippet[:240].rsplit(" ", 1)[0] + "…"
        citations.append(
            Citation(
                id=i,
                title=section.title or section.breadcrumb,
                source=section.citation_label,
                url=section.source_url,
                snippet=snippet,
                origin=Origin.LOCAL,
            )
        )
    return citations


def citations_from_web(results: list[WebResult]) -> list[Citation]:
    citations = []
    for i, result in enumerate(results, start=1):
        snippet = result.content.strip()
        if len(snippet) > 240:
            snippet = snippet[:240].rsplit(" ", 1)[0] + "…"
        citations.append(
            Citation(
                id=i,
                title=result.title,
                source=result.source_name,
                url=result.url,
                snippet=snippet,
                origin=Origin.WEB,
            )
        )
    return citations


def context_blocks_from_knowledge(scored_sections: list[ScoredSection]) -> list[str]:
    blocks = []
    for scored in scored_sections:
        section = scored.section
        header = section.title or section.breadcrumb
        blocks.append(f"({section.citation_label}) {header}\n{section.body.strip()}")
    return blocks


def context_blocks_from_web(results: list[WebResult]) -> list[str]:
    blocks = []
    for result in results:
        blocks.append(f"({result.source_name}) {result.title}\n{result.content.strip()}")
    return blocks
