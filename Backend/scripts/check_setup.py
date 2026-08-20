"""Verify configuration before touching any endpoint.

Run: python scripts/check_setup.py
Checks each configured key by making a minimal live call, and reports the
parsed knowledge-base section count.
"""

import asyncio
import sys
from pathlib import Path

# See terminal_chat.py for why this is needed on Windows consoles.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.services.ai.gemini_provider import GeminiProvider  # noqa: E402
from app.services.ai.groq_provider import GroqProvider  # noqa: E402
from app.services.ai.base import AIProviderError  # noqa: E402
from app.services.knowledge_service import KnowledgeService  # noqa: E402
from tavily import AsyncTavilyClient  # noqa: E402


def _ok(msg: str) -> None:
    print(f"  [OK]   {msg}")


def _fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")


def _skip(msg: str) -> None:
    print(f"  [SKIP] {msg}")


async def check_gemini() -> None:
    print("Gemini (primary AI provider):")
    if not settings.has_gemini:
        _skip("GEMINI_API_KEY not set in .env")
        return
    try:
        provider = GeminiProvider(settings.gemini_api_key, settings.gemini_model)
        text = await provider.generate_text("Reply with exactly one word: OK")
        _ok(f"responded ({settings.gemini_model}): {text.strip()[:60]!r}")
    except AIProviderError as e:
        _fail(str(e))


async def check_groq() -> None:
    print("Groq (fallback AI provider):")
    if not settings.has_groq:
        _skip("GROQ_API_KEY not set in .env")
        return
    try:
        provider = GroqProvider(settings.groq_api_key, settings.groq_model)
        text = await provider.generate_text("Reply with exactly one word: OK")
        _ok(f"responded ({settings.groq_model}): {text.strip()[:60]!r}")
    except AIProviderError as e:
        _fail(str(e))


async def check_tavily() -> None:
    print("Tavily (web search fallback):")
    if not settings.has_tavily:
        _skip("TAVILY_API_KEY not set in .env")
        return
    try:
        client = AsyncTavilyClient(settings.tavily_api_key)
        resp = await client.search(query="Right to Information Act India", max_results=1)
        n = len(resp.get("results", []))
        _ok(f"responded with {n} result(s)")
    except Exception as e:
        _fail(str(e))


def check_knowledge() -> None:
    print("Local knowledge base:")
    ks = KnowledgeService(settings)
    if not ks.file_exists:
        _fail(f"file not found: {settings.knowledge_path}")
        return
    if ks.section_count == 0:
        _fail(f"file exists but 0 sections parsed: {settings.knowledge_path}")
        return
    _ok(f"{ks.section_count} sections parsed from {settings.knowledge_path}")


async def main() -> None:
    print("=" * 70)
    print("LAWoud backend — setup check")
    print("=" * 70)
    check_knowledge()
    print()
    await check_gemini()
    print()
    await check_groq()
    print()
    await check_tavily()
    print()
    if not settings.has_gemini and not settings.has_groq:
        print("WARNING: No AI provider configured at all — /api/chat cannot function.")
    print("Done. Fix any [FAIL] lines above before running the server.")


if __name__ == "__main__":
    asyncio.run(main())
