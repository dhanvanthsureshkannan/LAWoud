"""Interactive terminal client for LAWoud — a stand-in for the frontend while
it doesn't exist yet. Talks to the running backend over HTTP/SSE exactly like
a real frontend would, so this is a genuine end-to-end test of the API
contract, not a shortcut around it.

Usage:
  python scripts/terminal_chat.py
  python scripts/terminal_chat.py --base-url http://127.0.0.1:8000

Commands inside the chat:
  /reset      clear conversation history
  /exit       quit (also: /quit, Ctrl+C, Ctrl+D)
"""

import argparse
import json
import sys

import httpx

# Windows consoles default to a legacy codepage (e.g. cp1252) that can't
# represent characters models commonly emit (curly quotes, em dashes, narrow
# no-break spaces). Force UTF-8 with a safe fallback so a surprising character
# degrades gracefully instead of crashing the whole session.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")

_DIM = "\033[2m"
_BOLD = "\033[1m"
_CYAN = "\033[36m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_RED = "\033[31m"
_RESET = "\033[0m"


def _c(text: str, code: str) -> str:
    return f"{code}{text}{_RESET}"


class ChatSession:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.history: list[dict[str, str]] = []
        self.conversation_id: str | None = None
        self.client = httpx.Client(timeout=120.0)

    def close(self) -> None:
        self.client.close()

    def ask(self, question: str) -> None:
        payload = {
            "question": question,
            "history": self.history or None,
            "conversation_id": self.conversation_id,
        }
        url = f"{self.base_url}/api/chat"

        answer_started = False
        full_answer = ""
        last_done: dict | None = None
        last_analysis: dict | None = None

        try:
            with self.client.stream("POST", url, json=payload) as response:
                response.raise_for_status()
                event_name = None
                for line in response.iter_lines():
                    if line is None or line.startswith(":"):
                        continue
                    if line.startswith("event:"):
                        event_name = line[len("event:") :].strip()
                        continue
                    if not line.startswith("data:"):
                        continue
                    raw = line[len("data:") :].strip()
                    try:
                        data = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    if event_name == "status":
                        print(_c(f"  … {data.get('message', '')}", _DIM))
                    elif event_name == "analysis":
                        last_analysis = data
                        print(
                            _c(
                                f"  [analysis] topic={data.get('legal_topic')!r} "
                                f"category={data.get('legal_category')} "
                                f"case_type={data.get('case_type') or '-'}",
                                _DIM,
                            )
                        )
                        if data.get("needs_clarification") and data.get("clarification_question"):
                            print(_c(f"  [tip] {data['clarification_question']}", _YELLOW))
                    elif event_name == "sources":
                        citations = data.get("citations", [])
                        origin = data.get("origin")
                        if citations:
                            print(_c(f"  [sources: {origin}]", _DIM))
                            for c in citations:
                                url_part = f" — {c['url']}" if c.get("url") else ""
                                print(_c(f"    [{c['id']}] {c['title']} ({c['source']}){url_part}", _DIM))
                    elif event_name == "question":
                        print(
                            _c(
                                f"  [question {data.get('round')}/{data.get('max_rounds')}"
                                f"{' — say skip to answer anyway' if data.get('can_skip') else ''}]",
                                _DIM,
                            )
                        )
                    elif event_name == "chunk":
                        if not answer_started:
                            print(f"\n{_c('LAWoud:', _BOLD + _GREEN)} ", end="")
                            answer_started = True
                        text = data.get("text", "")
                        sys.stdout.write(text)
                        sys.stdout.flush()
                        full_answer += text
                    elif event_name == "assistance":
                        self._print_assistance(data)
                    elif event_name == "done":
                        last_done = data
                    elif event_name == "error":
                        print(_c(f"\n  [error] {data.get('message')}", _RED))
        except httpx.HTTPStatusError as e:
            print(_c(f"HTTP error: {e.response.status_code} {e.response.text}", _RED))
            return
        except httpx.HTTPError as e:
            print(_c(f"Connection error: {e}. Is the server running? (python run.py)", _RED))
            return

        print()  # newline after streamed answer

        if last_done:
            self.conversation_id = last_done.get("conversation_id") or self.conversation_id
            self.history.append({"role": "user", "content": question})
            self.history.append({"role": "assistant", "content": full_answer})

            if last_done.get("awaiting") == "clarification":
                print(_c("  (answer the question above, or type 'skip' to answer anyway)", _DIM))
            elif last_done.get("professional_help_recommended") and last_done.get("awaiting") == "location":
                print(_c("  (this may need professional legal assistance — see the request above)", _YELLOW))

    def _print_assistance(self, data: dict) -> None:
        print(f"\n{_c('Legal Assistance — ' + data.get('location', ''), _BOLD + _CYAN)}")

        if data.get("advocate_data_available"):
            print(_c(f"  match_scope: {data.get('match_scope')}", _DIM))
            for r in data.get("advocates", []):
                print(f"\n  {_c(r['name'], _BOLD)}  (relevance {r['relevance_score']:.1f})")
                print(f"    {r['relevant_area']} — {r['district']}, {r.get('court_or_jurisdiction', '')}")
                print(_c(f"    {r['relevance_reason']}", _DIM))
                for src in r.get("verification_sources", []):
                    print(_c(f"      verify: {src['title']} — {src['url']}", _DIM))
        else:
            print(_c(f"  {data.get('reason')}", _YELLOW))
            if data.get("manual_search_url"):
                print(_c(f"  Manual search (official, CAPTCHA required): {data['manual_search_url']}", _DIM))

        print(_c(f"\n  {data.get('disclaimer')}", _DIM))
        if data.get("legal_aid"):
            print(_c("\n  Legal aid contacts:", _DIM))
            for item in data["legal_aid"][:4]:
                contact = f" — {item['contact']}" if item.get("contact") else ""
                print(_c(f"    {item['name']}{contact}", _DIM))


def main() -> None:
    parser = argparse.ArgumentParser(description="Interactive terminal chat for LAWoud")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    print(_c("LAWoud — terminal chat", _BOLD))
    print(_c(f"Connected to {args.base_url}  (type /exit to quit, /reset to clear history)\n", _DIM))

    session = ChatSession(args.base_url)
    try:
        while True:
            try:
                question = input(_c("You: ", _BOLD + _CYAN)).strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if not question:
                continue
            if question.lower() in ("/exit", "/quit"):
                break
            if question.lower() == "/reset":
                session.history.clear()
                session.conversation_id = None
                print(_c("  History cleared.", _DIM))
                continue

            session.ask(question)
            print()
    finally:
        session.close()
        print(_c("Goodbye.", _DIM))


if __name__ == "__main__":
    main()
