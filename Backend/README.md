# LAWoud Backend

AI-powered legal assistance backend for Indian law — FastAPI, retrieval-gated
answers (local Markdown knowledge base first, whitelisted web search as
fallback), Gemini-primary/Groq-fallback AI, real-time SSE streaming.

Hackathon build: runs entirely on `localhost`. No auth, no database, no
deployment tooling.

## 1. Setup

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env   # then fill in your API keys
```

Required keys in `.env` (get them at the linked pages):
- `GEMINI_API_KEY` — https://aistudio.google.com/apikey (primary AI)
- `GROQ_API_KEY` — https://console.groq.com/keys (automatic fallback AI)
- `TAVILY_API_KEY` — https://app.tavily.com (whitelisted web search fallback)

The server will still start with keys missing, but `/api/chat` needs at least
one AI provider configured, and web-search fallback needs `TAVILY_API_KEY`.

**Verify setup before running the server:**
```bash
python scripts/check_setup.py
```
This pings each configured provider and reports how many knowledge-base
sections were parsed, so config problems surface before you touch an endpoint.

## 2. Run

```bash
python run.py
# or
uvicorn app.main:app --reload
```

Then open `http://127.0.0.1:8000/docs` for interactive API docs.

**Interactive terminal chat** — the easiest way to test the whole thing while
there's no frontend. It talks to the API over HTTP/SSE exactly like a real
frontend would, including the "Find Legal Assistance" hand-off:
```bash
python scripts/terminal_chat.py
```
Commands inside the chat: `/reset` clears history, `/exit` quits.
Multi-turn history is maintained automatically, so follow-up questions work.

**Single-shot SSE event dump** (shows raw event names + timings):
```bash
python scripts/demo_client.py "How do I file an FIR?"
```

## 3. The knowledge corpus

Two Markdown files are loaded together as one searchable corpus, each with its
own parser, each hot-reloading independently on change (no restart needed):

**`General provisions all.md`** (`CONSTITUTION_FILE`) — the Constitution of
India, one entry per Article. This file has **no Markdown headings at all** —
`app/services/constitution_parser.py` finds article boundaries directly from
lines shaped like `Article 22 — Protection against arrest ... — Right to
Freedom`, and merges the file's several label spellings (`Simple:` /
`Simple Explanation:`, `Related:` / `Related Articles:`, ...) onto one field
set. Articles marked `Status: Omitted / Historical` are parsed but excluded
from retrieval by default (`INCLUDE_OMITTED_ARTICLES=true` to include them) —
citing a repealed Article as live law is the failure mode this guards against.

**`data/legal_knowledge.md`** (`KNOWLEDGE_FILE`) — a small guide covering
procedural topics the Constitution doesn't (filing an FIR, tenancy, cheque
bounce, ...), parsed generically by heading:
- Split into sections by `##` headings (falls back to `#` if the file has none).
- Optional metadata lines right after a heading improve search ranking and
  citations — **none are required**, plain markdown with just headings works:
  ```markdown
  ## Filing a Consumer Complaint

  **Topic:** Consumer protection
  **Keywords:** consumer complaint, refund, deficiency in service
  **Law:** Consumer Protection Act, 2019
  **Source:** Department of Consumer Affairs | https://consumeraffairs.nic.in/

  Your section content here...
  ```

Check `GET /api/knowledge/status` to confirm how many sections were parsed
from each file after swapping either one — a Constitution count near 128
instead of ~470 means the per-Article parser didn't engage and the file is
being blind-chunked.

### The lawyer directory (optional)

`LAWYER_DIRECTORY_FILE` (default `LAWOUD_Lawyer_Directory final.md`) is a
curated fallback used only when the live judicial-record search in
`advocate_service.py` finds nothing for a district. It's optional — if the
file is missing, that tier is simply empty and `/api/legal-assistance` falls
through to the national legal-aid contacts, same as if it were never
configured.

`app/services/lawyer_directory_service.py` tolerates three different
authoring styles found in the actual supplied file (plain `Label:` lines,
clean `**Label:**` Markdown, and backslash-escaped `\*\*Label:\*\*` Markdown)
— all three are normalized through the same parser. One advocate is one block:
a name line, then `Label:`/`value` pairs. Recognized labels: `Speciality`,
`City`, `High Court / Bench`, `Experience`, `Cases Handled / Case Activity`,
`Case Types`, `Professional Mobile`, `Office / Location`, `Sources`. There is
no state field in the source data, so matching is by city only.

## 4. API contract

### `POST /api/chat` — primary endpoint, Server-Sent Events

The pipeline is **conversational and phase-aware**: a new question first goes
through an *intake* phase, where the model may ask one clarifying question per
turn (up to 3 rounds) before it has enough to answer — e.g. "I got arrested by
police" gets asked whether a warrant was shown before it answers, while
"can I kick my friend?" is answered immediately since nothing would change
the answer. It also decides a **route** — `legal`, `moral`, or `mixed` —
so "my wife filed for divorce but I want to stay with her" leads with
counselling/mediation options before the legal position, while a normal legal
question doesn't. If the answer indicates professional help may be warranted,
the assistant asks inline for the user's district/state, then hands off to
the same advocate/legal-aid lookup as `/api/legal-assistance` — all within
this one endpoint, so the frontend never has to orchestrate a separate call.

```json
{
  "question": "I got arrested by police",
  "history": [{"role": "user", "content": "..."}],
  "conversation_id": null,
  "skip_questions": false
}
```
`history` is optional context for the model. `conversation_id` is what makes
the multi-turn intake/location flow work: `null` on the first message of a
new topic, then echo back whatever the previous `done` event returned in
`conversation_id` on every later turn in the same conversation — without it,
each turn starts over and the follow-up questions never resolve. Conversation
state is in-memory only (1 hour TTL, no persistence) — this product keeps no
chat history beyond what's needed to finish the turn in progress.

SSE events, in order, each an `event:` line + JSON `data:` line:

| Event | Payload | Notes |
|---|---|---|
| `status` | `{stage, message}` | `stage` ∈ `analyzing \| searching_knowledge \| searching_web \| generating \| finding_help` |
| `analysis` | `{legal_topic, legal_category, case_type, intent, keywords[], needs_clarification, clarification_question, route, route_reason}` | `route` ∈ `legal \| moral \| mixed` |
| `question` | `{text, question_key, round, max_rounds, can_skip}` | Sent instead of `sources`/answer when intake needs more context. The question text is *also* sent as a `chunk` so a client that only understands `chunk` still renders it |
| `sources` | `{origin: "local"\|"web", citations: [{id, title, source, url, snippet}]}` | Sent **before** the answer, so source cards can render while text streams in |
| `chunk` | `{text}` | Append to the answer bubble |
| `assistance` | `{location, match_scope, advocate_data_available, advocates[], legal_aid[], disclaimer, reason, manual_search_url}` | Sent when the inline location hand-off resolves — same shape as `/api/legal-assistance`'s response, field-renamed (`results` → `advocates`) |
| `done` | `{professional_help_recommended, legal_topic, legal_category, case_type, clarification_question, citations, origin, providers: {analysis, answer}, conversation_id, phase, route, awaiting}` | Terminal event. `awaiting` ∈ `clarification \| location \| null` — tells the client what the user's next message means |
| `error` | `{message, recoverable}` | |

A `: heartbeat` comment line is sent periodically to keep the connection alive
through proxies — ignore it, `EventSource` already does.

### `GET /api/chat/stream?question=...&conversation_id=...`
Identical stream, exposed as GET so the browser's native `EventSource` can
connect directly (`EventSource` cannot send a POST body).

### `POST /api/chat/sync`
Same pipeline, collected into one JSON response — useful for quick testing or
a non-streaming client. Returns `{answer, analysis, done}`.

### `POST /api/legal-assistance`
Standalone advocate + legal-aid lookup with an explicit district/state —
useful for a "Find Legal Assistance" button outside the chat flow. The chat
flow above reaches the same underlying logic inline, from a district/state the
assistant parses out of the user's own chat message once it has been asked;
both paths share one implementation (`legal_assistance_service.get_legal_assistance`)
so they can't drift apart.

Request:
```json
{
  "district": "Vellore",
  "state": "Tamil Nadu",
  "legal_category": "civil",
  "legal_topic": "Land / property dispute",
  "case_type": "land dispute"
}
```
`state` is optional — pass the `legal_category`/`legal_topic`/`case_type`
straight through from the prior `/api/chat` `done` event. If `state` is
omitted, the backend infers it from `district` and validates the guess against
a canonical state/UT list before trusting it. If the district name exists in
more than one state (e.g. Aurangabad, Bilaspur, Hamirpur), the response comes
back with `state_required: true` and `candidate_states` for your UI to ask the
user to pick.

Response:
```json
{
  "legal_topic": "Land / property dispute",
  "location": "Vellore, Tamil Nadu",
  "match_scope": "district_category",
  "advocate_data_available": true,
  "results": [
    {
      "name": "...",
      "relevant_area": "Civil",
      "district": "Vellore",
      "court_or_jurisdiction": "...",
      "public_case_count": 3,
      "relevance_score": 11.0,
      "relevance_reason": "Appears as counsel in 3 publicly available civil case record(s)...",
      "verification_sources": [{"title": "...", "url": "...", "source": "...", "is_official": true}]
    }
  ],
  "legal_aid": [ { "name": "NALSA", "description": "...", "contact": "15100", "url": "...", "scope": "national" } ],
  "disclaimer": "Relevant advocates identified from publicly available case information...",
  "reason": null,
  "state_required": false,
  "candidate_states": [],
  "manual_search_url": null
}
```

**Important, and non-negotiable:** the app never claims a "best" or "top"
lawyer, and never guarantees an outcome — results are relevance-ranked from
publicly available judicial records, not a quality ranking. See
`app/core/wording.py`.

**Advocate data can legitimately be empty.** The official eCourts
advocate-search endpoints (`services.ecourts.gov.in`, `judgments.ecourts.gov.in`)
are CAPTCHA-gated and are **never queried programmatically** by this backend —
we don't bypass CAPTCHAs. Three tiers run in order, and the response reports
which one actually matched:
1. Advocate names extracted from publicly indexed judgment text (via Tavily,
   searching Indian Kanoon + official court domains) with progressive query
   widening (`match_scope`).
2. The curated `LAWYER_DIRECTORY_FILE` (city-only match — see §3), if the
   above found nothing.
3. If even that finds nothing, `advocate_data_available` is `false` with a
   `reason`, `legal_aid` contacts are still returned, and `manual_search_url`
   points the user to the official eCourts portal to search there themselves.

### `GET /api/legal-assistance/states`
`{states: [...], union_territories: [...]}` — for a location dropdown.

### `GET /api/health`
`{status: "ok", gemini_configured, groq_configured, tavily_configured}`

### `GET /api/knowledge/status`
`{file_path, exists, section_count, last_loaded, last_modified, file_paths[], section_counts}`
— debug aid; `section_counts` breaks the total down per source file.

## 5. Architecture

```
app/
  main.py                     FastAPI app, CORS, startup
  config.py                   .env settings
  core/                       prompts, SSE framing, text utils, domain whitelist, wording guard
  models/schemas.py           all request/response/event Pydantic models
  services/
    ai/                       ai_service.py (Gemini->Groq fallback), gemini_provider, groq_provider
    session_store.py          in-memory per-conversation state (TTL, no persistence)
    intake_service.py         one LLM call/turn: analysis + moral/legal/mixed routing + next question
    constitution_parser.py    per-Article parser for the headingless Constitution file
    knowledge_service.py      loads both corpus files, keyword search + sufficiency gate
    web_search_service.py     whitelisted Tavily search
    answer_service.py         streaming generation from retrieved context only (route-aware prompt)
    citation_service.py       unifies local/web results into one Citation shape
    assessment_service.py     deterministic professional-help decision
    location_service.py       state/district resolution + free-text location parsing
    advocate_service.py       tier 1: advocate extraction + ranking from judicial docs (Tavily)
    lawyer_directory_service.py  tier 2: curated local advocate directory (see §3)
    legal_assistance_service.py  orchestrates all three lookup tiers + legal aid
    orchestrator.py            the whole /chat pipeline as one phase-aware async event generator
  api/routes/                 chat.py, legal_assistance.py, health.py
data/
  legal_knowledge.md          procedural guide corpus (FIR, tenancy, cheque bounce, ...)
  legal_aid_directory.json    national legal-aid contacts (NALSA, Tele-Law, ...)
  states.json                 canonical states/UTs + known-ambiguous districts
General provisions all.md     Constitution of India, one entry per Article
LAWOUD_Lawyer_Directory final.md   curated advocate directory (optional)
```

**Why retrieval-gated:** the AI is never allowed to answer from its own
unsupported knowledge of Indian law. It's shown numbered context blocks pulled
from the local knowledge base or approved sources and instructed to cite them
inline (`[1]`, `[2]`, ...) or say plainly when something isn't covered.

**Why the location hand-off lives inside `/chat` now:** conversational context
gathering only works if the assistant can ask for a location as part of the
same conversation, rather than handing the user off to a separate form. The
underlying lookup logic is still one function
(`legal_assistance_service.get_legal_assistance`), reused by both the inline
flow and the standalone `/api/legal-assistance` endpoint, so they can't drift
apart.
