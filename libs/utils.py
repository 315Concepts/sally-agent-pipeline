
import hashlib
from html.parser import HTMLParser
import json
import re
import base64
import sys

from PIL import Image
from pathlib import Path

import urllib.request

from .config import FORCE_REINVENTORY, LOGS_DIR, MAX_IMAGE_EDGE

from typing import Any

def clamp(text: str, limit: int, label: str) -> str:
    """Truncate text to limit characters, warning on the console when something is dropped."""
    if len(text) > limit:
        print(f"WARNING: {label} is {len(text):,} chars; truncating to {limit:,} ({len(text) - limit:,} dropped).", file=sys.stderr)
    return text[:limit]

def _pretty_json(body: str) -> str:
    """Indent a JSON body for readability; return it unchanged if it isn't valid JSON."""
    body = body.strip()
    try:
        return json.dumps(json.loads(body), indent=2, ensure_ascii=False)
    except json.JSONDecodeError:
        return body

def dump_http_bodies(stamp: str, request_body: str, response_body: str) -> None:
    """Persist one API attempt's request/response bodies for debugging."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    (LOGS_DIR / f"REQ-{stamp}.json").write_text(_pretty_json(request_body), encoding="utf-8", errors="replace")
    (LOGS_DIR / f"RES-{stamp}.json").write_text(_pretty_json(response_body), encoding="utf-8", errors="replace")

def extract_json(text: str) -> Any:
    """Extract the first complete JSON value, even if the model adds commentary after it."""
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    # Fast path for responses that are already exactly one JSON value.
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Scan candidate object/array starts and find balanced boundaries. Braces inside
    # quoted strings (including escaped quotes and backslashes) do not affect depth.
    last_error: json.JSONDecodeError | None = None
    for start, char in enumerate(cleaned):
        if char not in "{[":
            continue
        stack: list[str] = []
        in_string = False
        escaped = False
        for end in range(start, len(cleaned)):
            current = cleaned[end]
            if in_string:
                if escaped:
                    escaped = False
                elif current == "\\":
                    escaped = True
                elif current == '"':
                    in_string = False
                continue
            if current == '"':
                in_string = True
            elif current in "{[":
                stack.append("}" if current == "{" else "]")
            elif current in "}]":
                if not stack or current != stack[-1]:
                    break
                stack.pop()
                if not stack:
                    candidate = cleaned[start:end + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError as exc:
                        last_error = exc
                    break
    if last_error is not None:
        raise last_error
    raise ValueError("Model response did not contain a complete JSON object or array.")

def encode_image(path: Path) -> tuple[str, str]:
    """Resize/re-encode photos before sending them, keeping requests reasonably small."""
    with Image.open(path) as source:
        image = source.convert("RGB")
        image.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE))
        from io import BytesIO
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=84, optimize=True)
        data = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{data}", "image/jpeg"

def read_cached_inference(path: Path, tag: str, digest: str) -> str | None:
    """Return a cached inference body if its header carries the expected hash."""
    if FORCE_REINVENTORY or not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    header = f"<!-- {tag}: {digest} -->\n"
    return text[len(header):] if text.startswith(header) else None

## RESEARCH UTILS


class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip_depth += 1
        elif tag in {"p", "br", "li", "h1", "h2", "h3", "h4", "tr", "div"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip_depth:
            self.skip_depth -= 1

    def handle_data(self, data):
        if not self.skip_depth:
            self.parts.append(data)

def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    text = "".join(parser.parts)
    return re.sub(r"\n\s*\n+", "\n\n", re.sub(r"[ \t]+", " ", text)).strip()

def fetch_url(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (research-phase)"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")

def url_slug(url: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", re.sub(r"^https?://", "", url.lower())).strip("-")[:80]
    return f"{slug}-{hashlib.sha256(url.encode()).hexdigest()[:8]}.md"