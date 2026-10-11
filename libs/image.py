
import json
from pathlib import Path
import sys
import time
from typing import Any

from libs.config import BATCH_SIZE, FORCE_REINVENTORY, IMAGE_INFERENCE_CACHE, ROOT, SLEEP_BETWEEN_CALLS, VISION_MODEL
from libs.model import call_model
from libs.utils import encode_image, extract_json

IMAGE_INSTRUCTIONS = (
    "Analyze these brand photo assets for a social media manager. "
    "The images are supplied in a specific order. Return exactly one record per image, "
    "in that same order. Do not output filenames or invent identifiers; the program assigns "
    "the real filenames by position. Do not infer unsupported facts about people, products, "
    "locations, or brand claims. For each image return: visual_description, moods, "
    "use_cases, composition. Use concise factual descriptions. Return ONLY valid JSON in this shape: "
    '{"images":[{"visual_description":"...","moods":["..."],'
    '"use_cases":["..."],"composition":"..."}]}\n\n'
)

def build_image_inference_cache(files: list[Path], persona_instructions: str) -> list[dict[str, Any]]:
    target = IMAGE_INFERENCE_CACHE
    previous: dict[str, Any] = {}
    if target.exists() and not FORCE_REINVENTORY:
        try:
            previous = json.loads(target.read_text(encoding="utf-8"))
        except Exception:
            previous = {}
    by_name = {item.get("filename"): item for item in previous.get("images", []) if isinstance(item, dict)}
    # Drop stale entries, keep cached entries for existing files.
    current_names = {p.relative_to(ROOT).as_posix() for p in files}
    by_name = {k: v for k, v in by_name.items() if k in current_names}
    todo = [p for p in files if FORCE_REINVENTORY or p.relative_to(ROOT).as_posix() not in by_name]
    print(f"Photo cache: {len(files)} files; {len(by_name)} cached; {len(todo)} to analyze.")
    for start in range(0, len(todo), BATCH_SIZE):
        batch = todo[start:start + BATCH_SIZE]
        print(f"Analyzing batch {start // BATCH_SIZE + 1}/{(len(todo) + BATCH_SIZE - 1) // BATCH_SIZE}: "
              + ", ".join(p.name for p in batch))
        try:
            for item in analyze_batch(batch, persona_instructions, IMAGE_INSTRUCTIONS):
                by_name[item["filename"]] = item
            target.write_text(json.dumps({"images": [by_name[k] for k in sorted(by_name)]}, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            print(f"Batch failed; continuing with remaining batches. Error: {exc}", file=sys.stderr)
        if SLEEP_BETWEEN_CALLS:
            time.sleep(SLEEP_BETWEEN_CALLS)
    cache = [by_name[k] for k in sorted(by_name)]
    if not cache:
        raise SystemExit("No image cache could be created. Check model ID, API key, and image support.")
    return cache
    
def analyze_batch(batch: list[Path], personality_instructions: str, image_instructions: str) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = [{
        "type": "text",
        "text": (
            image_instructions + "Brand/agent instructions (context only):\n" + personality_instructions
        )
    }]
    for path in batch:
        data_url, _ = encode_image(path)
        content.append({"type": "text", "text": f"Image filename: {path.relative_to(ROOT).as_posix()}"})
        content.append({"type": "image_url", "image_url": {"url": data_url}})
    result = call_model(
        VISION_MODEL,
        [{"role": "user", "content": content}],
        max_tokens=4500,
        temperature=0.2,
    )
    parsed = extract_json(result)
    records = parsed if isinstance(parsed, list) else parsed.get("images", []) if isinstance(parsed, dict) else []
    if not isinstance(records, list):
        raise ValueError("Image model response JSON did not contain an images list.")
    # Filenames are assigned by input position, never trusted from model output.
    # This prevents hallucinated names from silently dropping otherwise useful records.
    normalized = []
    for index, path in enumerate(batch):
        rel = path.relative_to(ROOT).as_posix()
        rec = records[index] if index < len(records) else None
        if isinstance(rec, dict):
            rec = dict(rec)
            rec["filename"] = rel
            normalized.append(rec)
        else:
            normalized.append({
                "filename": rel,
                "literal_visual_description": "Not successfully analyzed; inspect manually.",
                "mood": [],
                "likely_use_cases": [],
                "composition": "",
                "visible_text": "",
                "cautions": ["Model did not return a usable record for this image position."],
            })
    return normalized
