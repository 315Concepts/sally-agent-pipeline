
from openai import OpenAI

from .config import BASE_URL, SITE_URL, SITE_NAME, API_KEY

client = OpenAI(
    api_key=API_KEY or "missing-key",
    base_url=BASE_URL,
    default_headers={
        **({"HTTP-Referer": SITE_URL} if SITE_URL else {}),
        "X-Title": SITE_NAME,
    },
    max_retries=0,
    timeout=180.0,
)