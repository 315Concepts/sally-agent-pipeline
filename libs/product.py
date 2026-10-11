import hashlib
import re
import sys
import time

from libs.utils import clamp, fetch_url, html_to_text, read_cached_inference, url_slug

from .config import PRODUCT_RESEARCH_MAX_TOKENS, PRODUCT_RESEARCH_MODEL_TEMP, ROOT, SOURCES_DIR, OUTPUT_DIR, WRITING_MODEL, SLEEP_BETWEEN_CALLS
from .model import call_model

TEXT_EXTS = {".md", ".txt", ".html", ".htm"}
MAX_DOC_CHARS = 24000
MAX_SYNTH_CHARS = 60000
FETCHED_DIR = SOURCES_DIR / "fetched"
SOURCE_TAG = re.compile(r"\A<!-- source: (\S+) -->\n")
MIN_USEFUL_CHARS = 300

# Per-source research notes. Placeholders: {source}, {text}
PRODUCT_RESEARCH_INSTRUCTIONS = """
You are researching a product for a social media campaign planner. 
Read the source document below and write research notes in Markdown. 
Extract ONLY what the document explicitly states; do not add outside knowledge or infer claims.

Use exactly these sections (write "None stated." for an empty one):

## Summary
2-3 sentences, including what kind of document this is (blog post, product listing, other).

## Products
Product names and what each is.

## Facts
Bullet list. Each bullet is one stated fact followed by a short verbatim quote in quotation marks.

## Pricing and availability

## Limitations
Price, scope, compatibility, maturity, or anything else the document says that limits or qualifies the product.

## Audience signals
Who the document is written for or what problems it addresses.

## Story angles
Narrative hooks the document itself offers.

SOURCE: {source}

===== DOCUMENT =====
{text}
"""

def prefetch_urls(refetch: bool = False) -> None:
    """Download every URL in sources/urls.txt to sources/fetched/ as plain text.

    The models have no browsing, so pages are fetched here and the research stage only ever
    reads local files. Already-fetched URLs are skipped unless refetch is set.
    """
    urls_file = SOURCES_DIR / "urls.txt"
    if not urls_file.exists():
        return
    urls = [l.strip() for l in urls_file.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.strip().startswith("#")]
    FETCHED_DIR.mkdir(parents=True, exist_ok=True)
    for url in urls:
        target = FETCHED_DIR / url_slug(url)
        if target.exists() and not refetch:
            continue
        print(f"Fetching {url}")
        text = ""
        try:
            raw = fetch_url(url)
            text = html_to_text(raw) if "<" in raw[:2000] else raw.strip()
        except Exception as exc:
            print(f"  Plain fetch failed: {exc}", file=sys.stderr)
        if len(text) < MIN_USEFUL_CHARS:
            print("  Little or no text in the raw HTML; rendering in headless browser...")
            try:
                text = render_url(url)
            except Exception as exc:
                print(f"  Could not render {url}: {exc}. Save the page text into sources/ by hand instead.", file=sys.stderr)
                continue
        if len(text) < MIN_USEFUL_CHARS:
            print(f"  Only {len(text)} characters of text from {url} even after rendering (login wall or blocked?). "
                  f"Not saved; copy the page text into sources/ by hand.", file=sys.stderr)
            continue
        target.write_text(f"<!-- source: {url} -->\n{text}\n", encoding="utf-8")
        print(f"  Saved {target.relative_to(ROOT).as_posix()} ({len(text)} chars)")

def render_url(url: str) -> str:
    """Load a page in headless Chromium so JavaScript-rendered content (React etc.) is present."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError("playwright is not installed (pip install playwright && playwright install chromium)")
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass  # chatty pages never go idle; use whatever has rendered
            page.evaluate("document.querySelectorAll('script,style,noscript,nav,footer,header').forEach(e => e.remove())")
            return re.sub(r"\n\s*\n+", "\n\n", page.inner_text("body")).strip()
        finally:
            browser.close()

def load_sources() -> list[dict[str, str]]:
    """Collect docs from sources/ (md/txt/html files, including those pre-fetched from urls.txt)."""
    docs: list[dict[str, str]] = []
    if not SOURCES_DIR.exists():
        return docs
    
    for path in sorted(SOURCES_DIR.rglob("*")):
        if not path.is_file() or path.name == "urls.txt" or path.suffix.lower() not in TEXT_EXTS:
            continue

        text = path.read_text(encoding="utf-8", errors="replace")
        if path.suffix.lower() in {".html", ".htm"}:
            text = html_to_text(text)

        label = path.relative_to(ROOT).as_posix()
        tag = SOURCE_TAG.match(text)
        if tag:
            label, text = tag.group(1), text[tag.end():]
            
        docs.append({"source": label, "text": text})

    return [d for d in docs if d["text"].strip()]

def _slug(label: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", re.sub(r"^https?://", "", label.lower())).strip("-")[:60]
    return f"{slug}-{hashlib.sha256(label.encode()).hexdigest()[:8]}"

def research_source(doc: dict[str, str], research_instructions: str) -> str:
    prompt = research_instructions.replace("{source}", doc["source"]).replace("{text}", clamp(doc["text"], MAX_DOC_CHARS, f"source document {doc['source']}"))
    notes = call_model(
        WRITING_MODEL, 
        [{"role": "user", "content": prompt}], 
        max_tokens=PRODUCT_RESEARCH_MAX_TOKENS, 
        temperature=PRODUCT_RESEARCH_MODEL_TEMP
    )
    return notes.strip()

def build_research(docs: list[dict[str, str]], research_instructions: str) -> list[tuple[str, str, str]]:
    """Write research notes to output/research/<source>.md. Cached by content hash.

    Returns (source_label, notes_markdown, digest) for every source that succeeded.
    """
    research_output_directory = (OUTPUT_DIR / "research")
    research_output_directory.mkdir(parents=True, exist_ok=True)

    results = []
    for doc in docs:
        digest = hashlib.sha256(doc["text"].encode("utf-8")).hexdigest()[:16]
        path = research_output_directory / f"{_slug(doc['source'])}.md"

        notes = read_cached_inference(path, "hash", digest)
        if notes is None:
            print(f"Researching {doc['source']}...")
            try:
                notes = research_source(doc, research_instructions)
            except Exception as exc:
                print(f"Research failed for {doc['source']}; skipping. Error: {exc}", file=sys.stderr)
                continue
            path.write_text(f"<!-- hash: {digest} -->\n{notes}\n", encoding="utf-8")
            if SLEEP_BETWEEN_CALLS:
                time.sleep(SLEEP_BETWEEN_CALLS)

        results.append((doc["source"], notes.strip(), digest))

    return results

def build_product_research_inference_cache(refetch: bool = False):

    prefetch_urls(refetch)

    docs = load_sources()
    if not docs:
        print(f"No product sources found in {SOURCES_DIR} (add .md/.txt/.html files or a urls.txt). "
              "Continuing.", file=sys.stderr)
        return []
    print(f"Product research: {len(docs)} source(s).")

    results = build_research(docs, PRODUCT_RESEARCH_INSTRUCTIONS)
    if not results:
        print("No source could be researched. Continuing.", file=sys.stderr)
        return []
    
    return results
