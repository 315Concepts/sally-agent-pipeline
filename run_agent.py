#!/usr/bin/env python3
"""
Minimal social campaign agent for:
  .env, AGENT.md, IDENTITY.md, SOUL.md, USER.md, images/

Uses OpenRouter's OpenAI-compatible chat completions API.
Creates a resumable context cache set, then drafts three campaigns for Instagram and Reddit.

Usage:
  python -m pip install -r requirements.txt
  cp .env.example .env       # add your OpenRouter API key
  python run_agent.py
"""
from __future__ import annotations

import sys

from libs.model import PERSONA_INSTRUCTIONS

from libs.image import build_image_inference_cache
from libs.product import build_product_research_inference_cache
from libs.campaign import build_product_brief_inference_cache, generate_campaign

from libs.config import IMAGES_DIR, API_KEY, SUPPORTED_EXTS, OUTPUT_DIR, image_files

def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if not API_KEY:
        print("Missing OPENROUTER_API_KEY. Put it in .env (see .env.example).", file=sys.stderr)
        return 2
    files = image_files()
    if not files:
        print(f"No supported photos found in {IMAGES_DIR}. Supported extensions: {', '.join(sorted(SUPPORTED_EXTS))}", file=sys.stderr)
        return 2
    print(f"Found {len(files)} images.")

    image_inference_cache = build_image_inference_cache(files, PERSONA_INSTRUCTIONS)
    research_inference_cache = build_product_research_inference_cache(refetch="--refetch" in sys.argv)
    product_brief_inference_cache = build_product_brief_inference_cache(research_inference_cache)
    return generate_campaign(image_inference_cache, product_brief_inference_cache, PERSONA_INSTRUCTIONS)

if __name__ == "__main__":
    raise SystemExit(main())
