"""In-memory conversation state for the multi-turn intake flow.

Deliberately not a database. The product keeps no chat history — this holds only
the context needed to finish the conversation in progress (which questions have
been asked, what the user has answered, which phase we are in), and it dies with
the process. Entries expire after an hour and the map is capped, so a long demo
session cannot grow memory without bound.

Everything the *model* sees is still passed per-request as `history`; this store
exists for the state a transcript cannot reliably encode, such as "we have
already asked two questions" or "the answer is delivered and we are waiting for
a district".
"""

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field

from app.config import settings
from app.models.schemas import ConversationPhase, QueryAnalysis, Route

logger = logging.getLogger("lawoud.session_store")

_MAX_CONVERSATIONS = 200
_TTL_SECONDS = 60 * 60


@dataclass
class ConversationState:
    conversation_id: str
    phase: ConversationPhase = ConversationPhase.INTAKE
    original_question: str = ""
    # What the user has told us, keyed by the slot the intake stage asked for
    # (e.g. {"warrant": "no", "police_station": "Vellore Town"}).
    slots: dict[str, str] = field(default_factory=dict)
    asked_questions: list[str] = field(default_factory=list)
    rounds_asked: int = 0
    # The slot the last question was asking about, so a free-text reply can be
    # filed correctly even when the model does not echo the key back.
    pending_slot_key: str = ""
    analysis: QueryAnalysis | None = None
    route: Route = Route.LEGAL
    last_answer: str = ""
    district: str = ""
    state_name: str = ""
    # True when the last legal-assistance attempt could not resolve a state
    # (ambiguous district, or an unrecognized name) and is waiting on a
    # state-only reply rather than a fresh "district, state" message.
    awaiting_state_only: bool = False
    updated_at: float = field(default_factory=time.time)

    @property
    def can_ask_more(self) -> bool:
        return self.rounds_asked < settings.max_clarification_rounds

    def record_question(self, question: str, key: str) -> None:
        self.rounds_asked += 1
        self.asked_questions.append(question)
        self.pending_slot_key = key

    def record_answer_to_pending(self, text: str) -> None:
        """File a free-text reply against whichever slot we last asked about."""
        key = self.pending_slot_key or f"answer_{len(self.slots) + 1}"
        self.slots[key] = text
        self.pending_slot_key = ""

    def reset_for_new_topic(self, question: str) -> None:
        """Start a fresh matter while keeping the same conversation id."""
        self.phase = ConversationPhase.INTAKE
        self.original_question = question
        self.slots = {}
        self.asked_questions = []
        self.rounds_asked = 0
        self.pending_slot_key = ""
        self.analysis = None
        self.route = Route.LEGAL
        self.last_answer = ""


class SessionStore:
    def __init__(self) -> None:
        self._conversations: dict[str, ConversationState] = {}
        self._lock = threading.Lock()

    def get_or_create(self, conversation_id: str | None, question: str) -> ConversationState:
        """Fetch an existing conversation, or start one.

        An unknown or expired id is treated as a new conversation rather than an
        error — a user whose session aged out mid-demo should get an answer, not
        a failure.
        """
        with self._lock:
            self._evict_expired()
            if conversation_id:
                state = self._conversations.get(conversation_id)
                if state:
                    state.updated_at = time.time()
                    return state
                logger.info("Unknown conversation id %s; starting a new one.", conversation_id)

            new_id = uuid.uuid4().hex
            state = ConversationState(conversation_id=new_id, original_question=question)
            self._conversations[new_id] = state
            self._evict_overflow()
            return state

    def drop(self, conversation_id: str) -> None:
        with self._lock:
            self._conversations.pop(conversation_id, None)

    def _evict_expired(self) -> None:
        cutoff = time.time() - _TTL_SECONDS
        for key in [k for k, v in self._conversations.items() if v.updated_at < cutoff]:
            del self._conversations[key]

    def _evict_overflow(self) -> None:
        while len(self._conversations) > _MAX_CONVERSATIONS:
            oldest = min(self._conversations.items(), key=lambda kv: kv[1].updated_at)[0]
            del self._conversations[oldest]
