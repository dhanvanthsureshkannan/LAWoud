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

## 3. Replace the knowledge base

`data/legal_knowledge.md` ships with a small placeholder covering ~11 common
Indian legal topics. Replace it with your own curated file (or point
`KNOWLEDGE_FILE` in `.env` at a different path) — **the server hot-reloads it
automatically on file change, no restart needed.**

Format:
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
after swapping the file.

## 4. API contract

### `POST /api/chat` — primary endpoint, Server-Sent Events

```json
{ "question": "How do I file an FIR?", "history": [{"role": "user", "content": "..."}] }
```
`history` is optional — the backend is stateless, so resend prior turns each
call if you want follow-up context.

SSE events, in order, each an `event:` line + JSON `data:` line:

| Event | Payload | Notes |
|---|---|---|
| `status` | `{stage, message}` | `stage` ∈ `analyzing \| searching_knowledge \| searching_web \| generating` |
| `analysis` | `{legal_topic, legal_category, case_type, intent, keywords[], needs_clarification, clarification_question}` | |
| `sources` | `{origin: "local"\|"web", citations: [{id, title, source, url, snippet}]}` | Sent **before** the answer, so source cards can render while text streams in |
| `chunk` | `{text}` | Append to the answer bubble |
| `done` | `{professional_help_recommended, legal_topic, legal_category, case_type, clarification_question, citations, origin, providers: {analysis, answer}}` | Terminal event |
| `error` | `{message, recoverable}` | |

A `: heartbeat` comment line is sent periodically to keep the connection alive
through proxies — ignore it, `EventSource` already does.

### `GET /api/chat/stream?question=...`
Identical stream, exposed as GET so the browser's native `EventSource` can
connect directly (`EventSource` cannot send a POST body).

### `POST /api/chat/sync`
Same pipeline, collected into one JSON response — useful for quick testing or
a non-streaming client. Returns `{answer, analysis, done}`.

### `POST /api/legal-assistance`
**Call this only after `/api/chat`'s `done` event has
`professional_help_recommended: true` and the user clicks a "Find Legal
Assistance" action in your UI.** `/api/chat` never asks for location itself —
that request belongs here.

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
we don't bypass CAPTCHAs. Instead, advocate names are extracted from publicly
indexed judgment text (via Tavily, searching Indian Kanoon + official court
domains) with progressive query widening. When even the widest search finds
nothing, `advocate_data_available` is `false` with a `reason`, `legal_aid`
contacts are still returned, and `manual_search_url` points the user to the
official eCourts portal to search there themselves.

### `GET /api/legal-assistance/states`
`{states: [...], union_territories: [...]}` — for a location dropdown.

### `GET /api/health`
`{status: "ok", gemini_configured, groq_configured, tavily_configured}`

### `GET /api/knowledge/status`
`{file_path, exists, section_count, last_loaded, last_modified}` — debug aid.

## 5. Architecture

```
app/
  main.py                 FastAPI app, CORS, startup
  config.py                .env settings
  core/                    prompts, SSE framing, text utils, domain whitelist, wording guard
  models/schemas.py        all request/response/event Pydantic models
  services/
    ai/                    ai_service.py (Gemini->Groq fallback), gemini_provider, groq_provider
    query_analysis.py      stage 1: structured analysis
    knowledge_service.py   markdown parsing + keyword search + sufficiency gate
    web_search_service.py  whitelisted Tavily search
    answer_service.py      stage 2: streaming generation from retrieved context only
    citation_service.py    unifies local/web results into one Citation shape
    assessment_service.py  deterministic professional-help decision
    location_service.py    state/district resolution
    advocate_service.py    advocate name extraction + ranking from judicial docs
    legal_assistance_service.py   orchestrates Flow 2
    orchestrator.py        Flow 1 pipeline as one async event generator
  api/routes/               chat.py, legal_assistance.py, health.py
data/
  legal_knowledge.md        placeholder knowledge base — replace this
  legal_aid_directory.json  national legal-aid contacts (NALSA, Tele-Law, ...)
  states.json                canonical states/UTs + known-ambiguous districts
```

**Why retrieval-gated:** the AI is never allowed to answer from its own
unsupported knowledge of Indian law. It's shown numbered context blocks pulled
from the local knowledge base or approved sources and instructed to cite them
inline (`[1]`, `[2]`, ...) or say plainly when something isn't covered.

**Why two flows are separate:** `/api/chat` is pure legal Q&A and never
touches location. `/api/legal-assistance` only runs when the user opts in,
and only ever queries CAPTCHA-free, publicly accessible sources.
