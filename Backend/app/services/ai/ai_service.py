"""Centralized AI service: Gemini primary, Groq automatic fallback.

This is the ONLY module in the application that should import a vendor SDK
(directly, or via gemini_provider/groq_provider). Every other service depends
on AIService, never on a specific provider — so swapping providers, or adding
a third, never touches business logic.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

from app.config import Settings
from app.models.schemas import ProviderName
from app.services.ai.base import AIProvider, AIProviderError
from app.services.ai.gemini_provider import GeminiProvider
from app.services.ai.groq_provider import GroqProvider

logger = logging.getLogger("lawoud.ai_service")


class AllProvidersFailedError(Exception):
    """Both Gemini and Groq failed (or neither is configured)."""


class AIService:
    def __init__(self, settings: Settings):
        self._timeout = settings.ai_timeout_seconds
        self._providers: list[AIProvider] = []
        if settings.has_gemini:
            self._providers.append(GeminiProvider(settings.gemini_api_key, settings.gemini_model))
        if settings.has_groq:
            self._providers.append(GroqProvider(settings.groq_api_key, settings.groq_model))
        if not self._providers:
            logger.warning(
                "No AI provider configured (GEMINI_API_KEY and GROQ_API_KEY both empty). "
                "generate_text/generate_json will raise AllProvidersFailedError."
            )

    @property
    def configured_providers(self) -> list[str]:
        return [p.name for p in self._providers]

    async def generate_text(
        self, prompt: str, *, system: str | None = None
    ) -> tuple[str, ProviderName]:
        """Try each provider in order; return (text, provider_used)."""
        last_error: Exception | None = None
        for provider in self._providers:
            try:
                text = await asyncio.wait_for(
                    provider.generate_text(prompt, system=system), timeout=self._timeout
                )
                return text, ProviderName(provider.name)
            except (AIProviderError, TimeoutError, asyncio.TimeoutError) as e:
                logger.warning("Provider %s failed for generate_text: %s", provider.name, e)
                last_error = e
                continue
        raise AllProvidersFailedError(str(last_error) if last_error else "no provider configured")

    async def generate_json(
        self, prompt: str, *, schema: dict[str, Any], system: str | None = None
    ) -> tuple[str, ProviderName]:
        """Try each provider in order; return (raw_json_text, provider_used)."""
        last_error: Exception | None = None
        for provider in self._providers:
            try:
                text = await asyncio.wait_for(
                    provider.generate_json(prompt, schema=schema, system=system),
                    timeout=self._timeout,
                )
                return text, ProviderName(provider.name)
            except (AIProviderError, TimeoutError, asyncio.TimeoutError) as e:
                logger.warning("Provider %s failed for generate_json: %s", provider.name, e)
                last_error = e
                continue
        raise AllProvidersFailedError(str(last_error) if last_error else "no provider configured")

    async def stream_text(
        self, prompt: str, *, system: str | None = None
    ) -> AsyncIterator[tuple[str, ProviderName]]:
        """Yield (chunk, provider_used) tuples.

        Fallback policy: if a provider fails before yielding any chunk, the next
        provider is tried transparently. If a provider fails *after* it has
        already yielded chunks, we cannot silently restart mid-answer without
        risking a duplicated or garbled response — so we re-raise and let the
        caller (the orchestrator) emit an `error` event and close the stream
        with whatever was already delivered.
        """
        last_error: Exception | None = None
        for provider in self._providers:
            yielded_any = False
            try:
                async for chunk in provider.stream_text(prompt, system=system):
                    yielded_any = True
                    yield chunk, ProviderName(provider.name)
                return
            except (AIProviderError, TimeoutError, asyncio.TimeoutError) as e:
                logger.warning("Provider %s failed for stream_text: %s", provider.name, e)
                last_error = e
                if yielded_any:
                    raise
                continue
        raise AllProvidersFailedError(str(last_error) if last_error else "no provider configured")
