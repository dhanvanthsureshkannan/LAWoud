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
    FINDING_HELP = "finding_help"


class Route(str, Enum):
    """How the matter should be approached, decided at intake.

    A divorce the user does not want is not answered the same way as an arrest:
    the first needs counselling and reconciliation options offered before the
    legal position, the second needs the law immediately.
    """

    LEGAL = "legal"
    MORAL = "moral"
    MIXED = "mixed"


class ConversationPhase(str, Enum):
    INTAKE = "intake"  # gathering context, one question at a time
    ANSWERING = "answering"  # enough context; retrieve and answer
    AWAITING_LOCATION = "awaiting_location"  # answered; need district/state for lawyer search
    ASSISTANCE = "assistance"  # assistance delivered


class Awaiting(str, Enum):
    """What the frontend should expect the user to supply next."""

    CLARIFICATION = "clarification"
    LOCATION = "location"


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
        description="Prior turns for follow-up context. The frontend resends this each call.",
    )
    conversation_id: str | None = Field(
        default=None,
        description="Returned in the first `done` event. Resend it on every later turn so the "
        "server can continue the same intake — without it, each turn starts a fresh "
        "conversation and the follow-up questions restart from scratch.",
    )
    skip_questions: bool = Field(
        default=False,
        description="Set by the frontend's Skip control: answer now with whatever context has "
        "been gathered, asking nothing further.",
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


class IntakeResult(BaseModel):
    """One intake turn: what we now know, and the single next thing to ask."""

    legal_topic: str = ""
    legal_category: str = "other"
    case_type: str = ""
    intent: str = ""
    keywords: list[str] = Field(default_factory=list)
    route: Route = Route.LEGAL
    route_reason: str = ""
    slots_filled: dict[str, str] = Field(default_factory=dict)
    next_question: str = ""
    next_question_key: str = ""
    sufficient: bool = True
    professional_help_signal: bool = False


class ClarificationQuestion(BaseModel):
    """Payload of the `question` SSE event."""

    text: str
    question_key: str = ""
    round: int
    max_rounds: int
    can_skip: bool = True


class AssistancePayload(BaseModel):
    """Payload of the `assistance` SSE event — the lawyer/legal-aid hand-off."""

    location: str
    match_scope: "MatchScope"
    advocate_data_available: bool
    advocates: list["AdvocateResult"] = Field(default_factory=list)
    legal_aid: list["LegalAidResource"] = Field(default_factory=list)
    disclaimer: str
    reason: str | None = None
    manual_search_url: str | None = None


class ChatDone(BaseModel):
    professional_help_recommended: bool
    legal_topic: str
    legal_category: str
    case_type: str
    clarification_question: str | None = None
    citations: list[Citation] = Field(default_factory=list)
    origin: Origin
    providers: ProvidersUsed
    conversation_id: str = ""
    phase: ConversationPhase = ConversationPhase.INTAKE
    route: Route = Route.LEGAL
    awaiting: Awaiting | None = Field(
        default=None,
        description="Set when this turn ended on a question rather than an answer, so the "
        "frontend knows the user's next message is a reply, not a new topic.",
    )


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
    file_paths: list[str] = Field(default_factory=list)
    section_counts: dict[str, int] = Field(
        default_factory=dict,
        description="Sections per source file. A Constitution count near 128 instead of ~473 "
        "means the per-Article parser did not engage and the file is being blind-chunked.",
    )


# AssistancePayload is declared above MatchScope/AdvocateResult/LegalAidResource so it
# sits with the other chat events; resolve those forward references now that they exist.
AssistancePayload.model_rebuild()
