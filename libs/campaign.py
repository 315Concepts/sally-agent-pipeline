import hashlib
import json
import sys

from libs.config import CAMPAIGN_GEN_MODEL_TEMP, IMAGE_CONTEXT_LIMIT, OUTPUT_DIR, PRODUCT_BRIEF_INFERENCE_CACHE, PRODUCT_BRIEF_MAX_TOKENS, CAMPAIGN_GEN_MAX_TOKENS, PRODUCT_BRIEF_MODEL_TEMP, WRITING_MODEL
from libs.model import call_model
from libs.product import MAX_SYNTH_CHARS
from libs.utils import clamp, read_cached_inference

# Merges per-source notes into one brief. Placeholder: {notes}
PRODUCT_BRIEF_INSTRUCTIONS = """
You are preparing a product brief for a social media campaign planner.

Below are research notes extracted from several source documents (blog posts, product listings). 

Merge them into ONE product brief in Markdown. Use ONLY the notes; do not add outside knowledge.

Rules:
- Merge duplicates, and call out any contradictions explicitly.
- Keep ALL limitations. Never drop them.

Use these sections: Overview, Products, Key facts, Pricing and availability, Limitations (always state these), Audience and problems addressed, Story angles, Open questions / gaps (what the sources do not cover).

===== NOTES =====
{notes}
"""

def build_product_brief_inference_cache(research: list[tuple[str, str, str]]) -> str:
    """Merge all per-source notes into output/product_brief.md (regenerated only when inputs change)."""
    if not research:
        return ""
    target_cache = PRODUCT_BRIEF_INFERENCE_CACHE
    inputs_digest = hashlib.sha256("".join(sorted(d for _, _, d in research)).encode()).hexdigest()[:16]
    cached = read_cached_inference(target_cache, "inputs", inputs_digest)
    if cached is not None:
        # Return cached inference
        return cached.strip()
    # Generate a new inference cache entry
    per_source = max(2000, MAX_SYNTH_CHARS // len(research))
    notes = "\n\n".join(f"===== SOURCE: {label} =====\n{clamp(text, per_source, f'research notes for {label}')}" for label, text, _ in research)
    print(f"Synthesizing product brief from {len(research)} source(s)...")
    try:
        product_brief_cache_entry = call_model(
            WRITING_MODEL, 
            [{"role": "user", "content": PRODUCT_BRIEF_INSTRUCTIONS.replace("{notes}", notes)}],
            max_tokens=PRODUCT_BRIEF_MAX_TOKENS, temperature=PRODUCT_BRIEF_MODEL_TEMP
        ).strip()
    except Exception as exc:
        print(f"Product brief synthesis failed ({exc}); falling back to the concatenated per-source notes.", file=sys.stderr)
        return "# Product research (unmerged per-source notes)\n\n" + notes
    target_cache.write_text(f"<!-- inputs: {inputs_digest} -->\n{product_brief_cache_entry}\n", encoding="utf-8")
    return product_brief_cache_entry


CAMPAIGN_INSTRUCTIONS = """
You are the social-media manager persona described in the included section below.
Follow those instructions unless they conflict with the output requirements below.

Create exactly two distinct brand-awareness campaigns across the following sites: Reddit, Instagram

Avoid making unsupported claims about the brand. Treat the photo inventory as observations, not facts beyond the visible evidence.
Do not pretend to have posted anything. Do not invent engagement metrics, community rules, or product claims.

For Reddit, focus on community-native, transparent posts; avoid spam, fake personal anecdotes, vote manipulation, or disguised advertising.

For LinkedIn, focus on professional but human posts in the company's voice, led by a specific engineering insight, build lesson, or product decision rather than a generic announcement; keep it concise and scannable, disclose that the post comes from the company, and avoid hype, engagement bait, and recruiter-style or buzzword language.

Choose actual image filenames from the inventory and reuse each image only when there is a good creative reason.

Make campaigns meaningfully different in angle, voice, and content format. For each campaign provide:
- title and one-paragraph strategic rationale
- target audience and awareness objective
- visual identity / creative direction
- 5-7 post ideas with platform, format, selected image filename(s), caption/post copy, CTA, and hashtags where appropriate
- recommended cadence over 2 weeks
- risks, assumptions, and a short measurement plan focused on awareness
- 3 alternate hooks

Return a readable Markdown report as the final response, with each document section starting with an h2 and the campaign number (## Campaign 1, ## Campaign 2, etc).

Keep copy practical, distinct, and ready for human review.
""".strip()

# Creates a campaign from product research
# Keep the additional context shimming to a minimum to prevent context creep
def campaign_prompt(image_cache: list, research_brief: str, personality: str) -> str:
    return f"""
===== SOCIAL MEDIA CAMPAIGN PACKAGE =====

This document is the ONLY source of product facts.
        
{CAMPAIGN_INSTRUCTIONS}

===== AGENT CONTEXT =====
{personality}

===== PHOTO INVENTORY =====
{clamp(json.dumps(image_cache, ensure_ascii=False), IMAGE_CONTEXT_LIMIT, "photo inventory")}

===== PRODUCT INFORMATION =====
{research_brief or "None supplied. Do not make any product claims beyond what the photos show."}
""".strip()

def generate_campaign(image_cache, research_brief, personality):
    prompt = campaign_prompt(image_cache, research_brief, personality)
    print(f"Generating campaigns with {WRITING_MODEL}...")
    result = call_model(
        WRITING_MODEL,
        [{"role": "user", "content": prompt}],
        max_tokens=CAMPAIGN_GEN_MAX_TOKENS,
        temperature=CAMPAIGN_GEN_MODEL_TEMP,
    )
    # Push the model output right into a file
    raw_path = OUTPUT_DIR / "campaigns_raw.md"
    raw_path.write_text(result, encoding="utf-8")