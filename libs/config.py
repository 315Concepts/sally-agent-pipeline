
import os
from dotenv import load_dotenv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IMAGES_DIR = ROOT / "images"
OUTPUT_DIR = ROOT / "output"
SOURCES_DIR = ROOT / "sources"
LOGS_DIR = ROOT / "logs"
PERSONA_MARKDOWNS = [ROOT / "agent" / f for f in ["AGENT.md", "IDENTITY.md", "SOUL.md", "USER.md"]]
SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
load_dotenv(ROOT / ".env")

API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").strip()
SITE_URL = os.getenv("OPENROUTER_SITE_URL", "").strip()
SITE_NAME = os.getenv("OPENROUTER_SITE_NAME", "Social Campaign Agent").strip()

VISION_MODEL = os.getenv("VISION_MODEL", "nvidia/nemotron-3-nano-omni:free").strip()
WRITING_MODEL = os.getenv("WRITING_MODEL", "nvidia/nemotron-3.5-lightning:free").strip()
BATCH_SIZE = max(1, int(os.getenv("IMAGE_BATCH_SIZE", "4")))
MAX_IMAGE_EDGE = max(512, int(os.getenv("MAX_IMAGE_EDGE", "1280")))
MAX_RETRIES = max(1, int(os.getenv("MAX_RETRIES", "4")))
SLEEP_BETWEEN_CALLS = max(0.0, float(os.getenv("SLEEP_BETWEEN_CALLS", "1.5")))
# Reasoning models count thinking tokens against max_tokens; "" leaves the provider default.
REASONING_EFFORT = os.getenv("REASONING_EFFORT", "low").strip().lower()
FORCE_REINVENTORY = os.getenv("FORCE_REINVENTORY", "0").lower() in {"1", "true", "yes"}

def image_files() -> list[Path]:
    if not IMAGES_DIR.exists():
        raise SystemExit(f"Image directory not found: {IMAGES_DIR}\nCreate images/ and put your photos in it.")
    return sorted(p for p in IMAGES_DIR.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS)

# Output cache
IMAGE_INFERENCE_CACHE = OUTPUT_DIR / "image_inventory.json"
RESEARCH_INFERENCE_CACHE = OUTPUT_DIR / "research"
PRODUCT_BRIEF_INFERENCE_CACHE = OUTPUT_DIR / "product_brief.md"

# Context clamping
PERSONA_CONTEXT_LIMIT = 30000
IMAGE_CONTEXT_LIMIT = 42000

# Model temperatures
PRODUCT_RESEARCH_MODEL_TEMP = 0.2
PRODUCT_BRIEF_MODEL_TEMP = 0.2
CAMPAIGN_GEN_MODEL_TEMP = 0.7

# Token limits
PRODUCT_RESEARCH_MAX_TOKENS = 15000
PRODUCT_BRIEF_MAX_TOKENS = 15000
CAMPAIGN_GEN_MAX_TOKENS = 20000