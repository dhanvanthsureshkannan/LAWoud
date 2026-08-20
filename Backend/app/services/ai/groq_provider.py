"""Fallback AI provider: Groq. Used automatically when Gemini errors, times out, or hits quota."""

import json
from collections.abc import AsyncIterator
from typing import Any

import groq

from app.services.ai.base import AIProvider, AIProviderError

# Exceptions that mean "this call failed, try the fallback" rather than a bug in our code.
_RETRYABLE_ERRORS = (
    groq.APIConnectionError,
    groq.APITimeoutError,
    groq.RateLimitError,
    groq.APIStatusError,
    groq.AuthenticationError,
    groq.PermissionDeniedError,
)


class GroqProvider(AIProvider):
    name = "groq"

    def __init__(self, api_key: str, model: str):
        self._model = model
        self._client = groq.AsyncGroq(api_key=api_key)

    async def generate_text(self, prompt: str, *, system: str | None = None) -> str:
        messages = self._build_messages(prompt, system)
        try:
            completion = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,
            )
        except _RETRYABLE_ERRORS as e:
            raise AIProviderError(self.name, f"generate_text failed: {e}", cause=e) from e
        content = completion.choices[0].message.content
        if not content:
            raise AIProviderError(self.name, "empty response from generate_text")
        return content

    async def generate_json(
        self,
        prompt: str,
        *,
        schema: dict[str, Any],
        system: str | None = None,
    ) -> str:
        # Groq's json_object mode doesn't accept a schema natively — it must be
        # described in the prompt itself. We inject it here so callers pass the
        # same Pydantic-derived schema dict to both providers.
        schema_instruction = (
            "\n\nRespond with ONLY a JSON object matching this schema "
            "(no markdown fences, no commentary):\n"
            f"{json.dumps(schema)}"
        )
        messages = self._build_messages(prompt + schema_instruction, system)
        try:
            completion = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                response_format={"type": "json_object"},
            )
        except _RETRYABLE_ERRORS as e:
            raise AIProviderError(self.name, f"generate_json failed: {e}", cause=e) from e
        content = completion.choices[0].message.content
        if not content:
            raise AIProviderError(self.name, "empty response from generate_json")
        return content

    async def stream_text(
        self, prompt: str, *, system: str | None = None
    ) -> AsyncIterator[str]:
        messages = self._build_messages(prompt, system)
        try:
            stream = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                stream=True,
            )
        except _RETRYABLE_ERRORS as e:
            raise AIProviderError(self.name, f"stream_text failed to start: {e}", cause=e) from e

        try:
            async for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
        except _RETRYABLE_ERRORS as e:
            raise AIProviderError(
                self.name, f"stream_text failed mid-stream: {e}", cause=e
            ) from e

    @staticmethod
    def _build_messages(prompt: str, system: str | None) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return messages
