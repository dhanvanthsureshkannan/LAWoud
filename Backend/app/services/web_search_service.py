"""Fallback web search: Tavily, restricted to a whitelist of approved legal domains.

Runs ONLY when the local knowledge base is insufficient (see knowledge_service's
sufficiency gate). Every result is re-checked against the whitelist by hostname
after the API responds, so an off-list URL can never reach the model even if
the provider's domain filter is imperfect or ignored.
"""

import asyncio
import logging
from dataclasses import dataclass

from tavily import AsyncTavilyClient

from app.config import Settings
from app.core.domains import LEGAL_INFO_DOMAINS, is_allowed, source_name

logger = logging.getLogger("lawoud.web_search_service")

# Tavily caps include_domains; we chunk our whitelist and query concurrently, then merge.
_TAVILY_DOMAIN_LIMIT = 300
_CHUNK_SIZE = 20


@dataclass
class WebResult:
    title: str
    url: str
    content: str
    source_name: str
    score: float = 0.0
    raw_content: str = ""


class WebSearchService:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._client: AsyncTavilyClient | None = (
            AsyncTavilyClient(settings.tavily_api_key) if settings.has_tavily else None
        )

    @property
    def is_configured(self) -> bool:
        return self._client is not None

    async def search(
        self,
        query: str,
        *,
        domains: list[str] | None = None,
        max_results: int | None = None,
        include_raw_content: bool = False,
    ) -> list[WebResult]:
        """Search *query* across the approved legal-info domain whitelist.

        *domains* overrides the default LEGAL_INFO_DOMAINS whitelist (used by
        the legal-assistance flow, which searches a different whitelist).
        *include_raw_content* pulls full page text — used only for advocate-name
        extraction from judgment pages, where snippets are too short to mine.
        """
        if not self._client:
            logger.warning("Tavily not configured (TAVILY_API_KEY empty); returning no results.")
            return []

        whitelist = domains if domains is not None else LEGAL_INFO_DOMAINS
        max_results = max_results or self._settings.web_search_max_results
        chunks = [whitelist[i : i + _CHUNK_SIZE] for i in range(0, len(whitelist), _CHUNK_SIZE)]

        tasks = [
            self._search_chunk(query, chunk, max_results, include_raw_content)
            for chunk in chunks
        ]
        chunk_results = await asyncio.gather(*tasks, return_exceptions=True)

        merged: dict[str, WebResult] = {}
        for outcome in chunk_results:
            if isinstance(outcome, Exception):
                logger.warning("A Tavily search chunk failed: %s", outcome)
                continue
            for result in outcome:
                if result.url not in merged or result.score > merged[result.url].score:
                    merged[result.url] = result

        ranked = sorted(merged.values(), key=lambda r: r.score, reverse=True)
        return ranked[:max_results]

    async def _search_chunk(
        self, query: str, domain_chunk: list[str], max_results: int, include_raw_content: bool
    ) -> list[WebResult]:
        try:
            response = await self._client.search(
                query=query,
                include_domains=domain_chunk,
                max_results=max_results,
                search_depth="basic",
                include_raw_content=include_raw_content,
            )
        except Exception as e:  # Tavily SDK error surface is not fully documented publicly.
            logger.warning("Tavily search failed for domain chunk %s: %s", domain_chunk, e)
            return []

        results: list[WebResult] = []
        for item in response.get("results", []):
            url = item.get("url", "")
            # Second, authoritative check: never trust the provider's domain filter alone.
            if not url or not is_allowed(url, domain_chunk):
                continue
            results.append(
                WebResult(
                    title=item.get("title", "") or url,
                    url=url,
                    content=item.get("content", ""),
                    source_name=source_name(url),
                    score=float(item.get("score", 0.0) or 0.0),
                    raw_content=item.get("raw_content") or "",
                )
            )
        return results
