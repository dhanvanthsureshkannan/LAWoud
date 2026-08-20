"""Central configuration. Everything comes from .env — nothing is hardcoded."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- AI providers ---
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.6-flash"
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    ai_timeout_seconds: float = 30.0

    # --- Web search ---
    tavily_api_key: str = ""
    web_search_max_results: int = 6

    # --- Local knowledge base ---
    knowledge_file: str = "data/legal_knowledge.md"
    knowledge_min_score: float = 3.0
    knowledge_min_coverage: float = 0.34
    knowledge_min_context_chars: int = 400
    knowledge_top_k: int = 4
    knowledge_max_section_chars: int = 4000

    # --- Server ---
    host: str = "127.0.0.1"
    port: int = 8000
    cors_origins: str = "*"
    log_level: str = "INFO"

    @property
    def knowledge_path(self) -> Path:
        """Absolute path to the knowledge file, resolved against the project root."""
        p = Path(self.knowledge_file)
        return p if p.is_absolute() else PROJECT_ROOT / p

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def has_gemini(self) -> bool:
        return bool(self.gemini_api_key.strip())

    @property
    def has_groq(self) -> bool:
        return bool(self.groq_api_key.strip())

    @property
    def has_tavily(self) -> bool:
        return bool(self.tavily_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
