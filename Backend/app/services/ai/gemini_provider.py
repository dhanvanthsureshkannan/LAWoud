"""Primary AI provider: Google Gemini."""

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types

from app.services.ai.base import AIProvider, AIProviderError

# The SDK raises APIError for server-side failures, but plain ValueError /
# TypeError for client-side ones (an unsupported schema keyword, a bad
# argument). Both must become AIProviderError, otherwise the exception
# escapes AIService and the Groq fallback never gets a turn.
_PROVIDER_ERRORS = (genai_errors.APIError, ValueError, TypeError)

# The SDK logs a WARNING on every generate_content call recommending AsyncChat
# for automatic function calling. We don't use function calling at all, so the
# advice doesn't apply and the noise obscures our own logs. Errors still surface.
logging.getLogger("google_genai.models").setLevel(logging.ERROR)


class GeminiProvider(AIProvider):
    name = "gemini"

    def __init__(self, api_key: str, model: str):
        self._model = model
        self._client = genai.Client(api_key=api_key).aio

    async def generate_text(self, prompt: str, *, system: str | None = None) -> str:
        try:
            response = await self._client.models.generate_content(
                model=self._model,
                contents=prompt,
                config=genai_types.GenerateContentConfig(system_instruction=system),
            )
        except _PROVIDER_ERRORS as e:
            raise AIProviderError(self.name, f"generate_text failed: {e}", cause=e) from e
        text = response.text
        if not text:
            raise AIProviderError(self.name, "empty response from generate_text")
        return text

    async def generate_json(
        self,
        prompt: str,
        *,
        schema: dict[str, Any],
        system: str | None = None,
    ) -> str:
        try:
            response = await self._client.models.generate_content(
                model=self._model,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    system_instruction=system,
                    response_mime_type="application/json",
                    response_schema=schema,
                ),
            )
        except _PROVIDER_ERRORS as e:
            raise AIProviderError(self.name, f"generate_json failed: {e}", cause=e) from e
        text = response.text
        if not text:
            raise AIProviderError(self.name, "empty response from generate_json")
        return text

    async def stream_text(
        self, prompt: str, *, system: str | None = None
    ) -> AsyncIterator[str]:
        try:
            stream = await self._client.models.generate_content_stream(
                model=self._model,
                contents=prompt,
                config=genai_types.GenerateContentConfig(system_instruction=system),
            )
        except _PROVIDER_ERRORS as e:
            raise AIProviderError(self.name, f"stream_text failed to start: {e}", cause=e) from e

        try:
            async for chunk in stream:
                if chunk.text:
                    yield chunk.text
        except _PROVIDER_ERRORS as e:
            raise AIProviderError(
                self.name, f"stream_text failed mid-stream: {e}", cause=e
            ) from e
        except asyncio.CancelledError:
            raise
