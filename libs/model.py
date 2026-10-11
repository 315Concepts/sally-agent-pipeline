
import random
import sys
import time
import json

from typing import Any

from .client import client
from .config import (
    API_KEY,
    PERSONA_CONTEXT_LIMIT,
    PERSONA_MARKDOWNS,
    MAX_RETRIES, LOGS_DIR, REASONING_EFFORT
)
from .utils import clamp, dump_http_bodies

def read_personality() -> str:
    """Personality instructions: the agent/*.md persona files joined into one block."""
    chunks = []
    missing = []
    for name in PERSONA_MARKDOWNS:
        path = name
        if path.exists():
            chunks.append(f"\n\n===== {name} =====\n{path.read_text(encoding='utf-8', errors='replace')}")
        else:
            missing.append(name)
    if missing:
        print("Note: these instruction files were not found and will be skipped: " + ", ".join(missing))
    if not chunks:
        raise SystemExit("No instruction files found. Put AGENT.md, IDENTITY.md, SOUL.md, and USER.md beside run_agent.py.")
    return clamp("\n".join(chunks), PERSONA_CONTEXT_LIMIT, "persona instructions")

PERSONA_INSTRUCTIONS = read_personality()

def call_model(model: str, messages: list[dict[str, Any]], *, max_tokens: int = 5000, temperature: float = 0.7) -> str:
    if not API_KEY:
        raise SystemExit("OPENROUTER_API_KEY is missing. Add it to .env or your environment.")
    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES):
        # Nanosecond Unix timestamp keeps filenames unique even during rapid retries.
        stamp = str(time.time_ns())
        request_payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        request_body = json.dumps(request_payload, ensure_ascii=False, separators=(",", ":"))
        response_body = "<no HTTP response body>"
        try:
            raw_response = client.chat.completions.with_raw_response.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                extra_body={"reasoning": {"effort": REASONING_EFFORT}} if REASONING_EFFORT else None,
            )
            http_response = raw_response.http_response
            request_body = http_response.request.content.decode("utf-8", errors="replace")
            response_body = http_response.content.decode("utf-8", errors="replace")
            dump_http_bodies(stamp, request_body, response_body)
            response = raw_response.parse()
            provider_error = getattr(response, "error", None)
            if provider_error:
                if isinstance(provider_error, dict):
                    message = provider_error.get("message", str(provider_error))
                    code = provider_error.get("code")
                else:
                    message = getattr(provider_error, "message", str(provider_error))
                    code = getattr(provider_error, "code", None)
                raise RuntimeError(f"OpenRouter provider error {code}: {message}")
            if not response.choices:
                raise RuntimeError(f"OpenRouter returned no choices; see logs/RES-{stamp}.txt")
            text = response.choices[0].message.content
            if not text:
                finish = response.choices[0].finish_reason
                hint = " (ran out of max_tokens while reasoning; lower REASONING_EFFORT or raise max_tokens)" if finish == "length" else ""
                raise RuntimeError(f"The model returned an empty response, finish_reason={finish}{hint}; see logs/RES-{stamp}.json")
            return text
        except Exception as exc:
            # HTTP status exceptions expose the actual request/response even when parse() fails.
            http_request = getattr(exc, "request", None)
            http_error_response = getattr(exc, "response", None)
            if http_request is not None and getattr(http_request, "content", None):
                request_body = http_request.content.decode("utf-8", errors="replace")
            if http_error_response is not None:
                try:
                    response_body = http_error_response.content.decode("utf-8", errors="replace")
                except Exception:
                    response_body = str(http_error_response)
            # Avoid overwriting a pair already written for a parsed HTTP response.
            req_path = LOGS_DIR / f"REQ-{stamp}.txt"
            res_path = LOGS_DIR / f"RES-{stamp}.txt"
            if not req_path.exists() or not res_path.exists():
                dump_http_bodies(stamp, request_body, response_body)
            last_error = exc
            wait = min(30, (2 ** attempt) * 2 + random.random())
            print(f"Request failed ({attempt + 1}/{MAX_RETRIES}): {exc} [logs/REQ-{stamp}.txt, logs/RES-{stamp}.txt]", file=sys.stderr)
            if attempt + 1 < MAX_RETRIES:
                print(f"Retrying in {wait:.1f}s...", file=sys.stderr)
                time.sleep(wait)
    raise RuntimeError(f"Model request failed after {MAX_RETRIES} attempts: {last_error}")
