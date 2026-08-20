"""All request/response/event shapes. This is the frontend contract."""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


# =============================================================================
# Shared enums
# =============================================================================


class Origin(str, Enum):
    LOCAL = "local"
    WEB = "web"
    NONE = "none"


class Stage(str, Enum):
    ANALYZING = "analyzing"
    SEARCHING_KNOWLEDGE = "searching_knowledge"
    SEARCHING_WEB = "searching_web"
    GENERATING = "generating"


class ProviderName(str, Enum):
    GEMINI = "gemini"
    GROQ = "groq"
    HEURISTIC = "heuristic"
    NONE = "none"


# =============================================================================
# /api/chat
# =============================================================================


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)
    history: list[ChatMessage] | None = Field(
        default=None,
        description="Prior turns for follow-up context. Backend is stateless; "
        "the frontend resends this each call.",
    )


class QueryAnalysis(BaseModel):
    legal_topic: str = Field(..., description="Short label, e.g. 'Tenant eviction'")
    legal_category: str = Field(
        ...,
        description="One of: civil, criminal, family, consumer, labour, property, "
        "cyber, tax, constitutional, other",
    )
    case_type: str = Field(default="", description="e.g. 'land dispute', 'cheque bounce'")
    intent: str = Field(..., description="What the user is trying to accomplish")
    keywords: list[str] = Field(default_factory=list)
    needs_clarification: bool = False
    clarification_question: str | None = None
    professional_help_signal: bool = Field(
        default=False,
        description="Analysis-stage guess; the real decision is made after the answer "
        "by assessment_service, deterministically.",
    )


class Citation(BaseModel):
    id: int
    title: str
    source: str
    url: str | None = None
    snippet: str = ""
    origin: Origin


class ProvidersUsed(BaseModel):
    analysis: ProviderName = ProviderName.NONE
    answer: ProviderName = ProviderName.NONE


class ChatDone(BaseModel):
    professional_help_recommended: bool
    legal_topic: str
    legal_category: str
    case_type: str
    clarification_question: str | None = None
    citations: list[Citation] = Field(default_factory=list)
    origin: Origin
    providers: ProvidersUsed


class ChatSyncResponse(BaseModel):
    """Non-streaming shape — same data /api/chat/sync assembles from the SSE events."""

    answer: str
    analysis: QueryAnalysis
    done: ChatDone


# =============================================================================
# /api/legal-assistance
# =============================================================================


class LegalAssistanceRequest(BaseModel):
    district: str = Field(..., min_length=2, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    legal_category: str = Field(..., min_length=2, max_length=100)
    legal_topic: str = Field(..., min_length=2, max_length=200)
    case_type: str | None = Field(default=None, max_length=200)


class VerificationSource(BaseModel):
    title: str
    url: str
    source: str
    is_official: bool


class AdvocateResult(BaseModel):
    name: str
    relevant_area: str
    district: str
    court_or_jurisdiction: str = ""
    public_case_count: int
    relevance_score: float
    relevance_reason: str
    verification_sources: list[VerificationSource]


class LegalAidResource(BaseModel):
    name: str
    description: str
    contact: str | None = None
    url: str | None = None
    scope: Literal["national", "state", "district"]


class MatchScope(str, Enum):
    DISTRICT_CASE_TYPE = "district_case_type"
    DISTRICT_CATEGORY = "district_category"
    DISTRICT_ONLY = "district_only"
    STATE_CATEGORY = "state_category"
    NONE = "none"


class LegalAssistanceResponse(BaseModel):
    legal_topic: str
    location: str
    match_scope: MatchScope
    advocate_data_available: bool
    results: list[AdvocateResult] = Field(default_factory=list)
    legal_aid: list[LegalAidResource] = Field(default_factory=list)
    disclaimer: str
    reason: str | None = Field(
        default=None, description="Set when advocate_data_available is false."
    )
    state_required: bool = False
    candidate_states: list[str] = Field(default_factory=list)
    manual_search_url: str | None = Field(
        default=None,
        description="Official eCourts advocate search — CAPTCHA-gated, "
        "user completes it manually; we never query it programmatically.",
    )


class StatesResponse(BaseModel):
    states: list[str]
    union_territories: list[str]


# =============================================================================
# /api/health, /api/knowledge/status
# =============================================================================


class HealthResponse(BaseModel):
    status: Literal["ok"]
    gemini_configured: bool
    groq_configured: bool
    tavily_configured: bool


class KnowledgeStatusResponse(BaseModel):
    file_path: str
    exists: bool
    section_count: int
    last_loaded: str | None
    last_modified: str | None
