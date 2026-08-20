"""Provider-agnostic AI interface. Gemini and Groq providers both implement this."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any


class AIProviderError(Exception):
    """Raised by a provider on any failure — API error, timeout, quota, bad response.

    AIService catches this (and only this) to trigger fallback, so provider
    implementations must wrap vendor SDK exceptions rather than let them escape.
    """

    def __init__(self, provider: str, message: str, *, cause: Exception | None = None):
        self.provider = provider
        self.cause = cause
        super().__init__(f"[{provider}] {message}")


class AIProvider(ABC):
    """One AI backend. Implementations: GeminiProvider, GroqProvider."""

    name: str

    @abstractmethod
    async def generate_text(self, prompt: str, *, system: str | None = None) -> str:
        """Return a complete text response."""
        raise NotImplementedError

    @abstractmethod
    async def generate_json(
        self,
        prompt: str,
        *,
        schema: dict[str, Any],
        system: str | None = None,
    ) -> str:
        """Return a raw JSON string conforming (as closely as the provider allows) to *schema*.

        Callers validate the result through a Pydantic model themselves, so both
        providers can return here regardless of how each enforces structure natively.
        """
        raise NotImplementedError

    @abstractmethod
    def stream_text(self, prompt: str, *, system: str | None = None) -> AsyncIterator[str]:
        """Yield text chunks as they're generated."""
        raise NotImplementedError
