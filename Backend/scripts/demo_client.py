"""CLI SSE consumer — proves the streaming pipeline works end-to-end with no frontend.

Usage:
  python scripts/demo_client.py "How do I file an FIR?"
  python scripts/demo_client.py "How do I file an FIR?" --base-url http://127.0.0.1:8000
"""

import argparse
import json
import sys
import time

import httpx

# See terminal_chat.py for why this is needed on Windows consoles.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def stream_chat(base_url: str, question: str) -> None:
    url = f"{base_url}/api/chat"
    start = time.monotonic()

    with httpx.Client(timeout=60.0) as client:
        with client.stream("POST", url, json={"question": question}) as response:
            response.raise_for_status()
            event_name = None
            for line in response.iter_lines():
                if line is None:
                    continue
                if line.startswith(":"):
                    continue  # heartbeat comment
                if line.startswith("event:"):
                    event_name = line[len("event:") :].strip()
                    continue
                if line.startswith("data:"):
                    elapsed = time.monotonic() - start
                    raw = line[len("data:") :].strip()
                    try:
                        data = json.loads(raw)
                    except json.JSONDecodeError:
                        data = raw
                    _print_event(elapsed, event_name, data)


def _print_event(elapsed: float, event: str | None, data) -> None:
    prefix = f"[{elapsed:6.2f}s] {event:>10}"
    if event == "chunk" and isinstance(data, dict):
        sys.stdout.write(data.get("text", ""))
        sys.stdout.flush()
        return
    if event == "status" and isinstance(data, dict):
        print(f"\n{prefix} | {data.get('stage')}: {data.get('message')}")
        return
    if event == "analysis" and isinstance(data, dict):
        print(
            f"\n{prefix} | topic={data.get('legal_topic')!r} "
            f"category={data.get('legal_category')} keywords={data.get('keywords')}"
        )
        return
    if event == "sources" and isinstance(data, dict):
        origin = data.get("origin")
        n = len(data.get("citations", []))
        print(f"\n{prefix} | origin={origin} citations={n}")
        for c in data.get("citations", []):
            print(f"           - [{c['id']}] {c['title']} ({c['source']})")
        return
    if event == "done" and isinstance(data, dict):
        print(f"\n\n{prefix} | professional_help_recommended={data.get('professional_help_recommended')}")
        print(f"           providers={data.get('providers')}")
        return
    print(f"\n{prefix} | {data}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stream a /api/chat request and print each SSE event.")
    parser.add_argument("question", help="The legal question to ask")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    print(f"Asking: {args.question!r}\n{'-' * 70}")
    stream_chat(args.base_url, args.question)
    print("\n" + "-" * 70 + "\nDone.")
