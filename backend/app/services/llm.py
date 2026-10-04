import httpx
import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted
from app.config import settings

genai.configure(api_key=settings.GEMINI_API_KEY)

# Providers are tried in order: Groq (if a key is set), then Gemini's main model, then Gemini's fallback.
# Free-tier quotas are small and per model, so one running out must not take the bot down.
_GEMINI_MODELS = [m for m in dict.fromkeys([settings.MODEL_NAME, settings.FALLBACK_MODEL]) if m]


def _groq(messages: list[dict], temperature: float, max_tokens: int, effort: str) -> str:
    body = {
        "model": settings.GROQ_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_completion_tokens": max_tokens,
    }
    if "gpt-oss" in settings.GROQ_MODEL:
        body["reasoning_effort"] = effort  # reasoning tokens count against the budget
    r = httpx.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {settings.GROQ_API_KEY}"},
        json=body,
        timeout=60,
    )
    r.raise_for_status()
    text = r.json()["choices"][0]["message"].get("content") or ""
    if not text.strip():
        raise RuntimeError("Groq returned an empty reply")
    return text


def _flatten(messages: list[dict]) -> str:
    """Gemini fallback: turn a chat into one transcript prompt."""
    parts = []
    for m in messages:
        if m["role"] == "system":
            parts.append(m["content"])
        else:
            parts.append(f"{'Friend' if m['role'] == 'user' else 'Me'}: {m['content']}")
    return "\n\n".join(parts) + "\n\nMe:"


def _gemini(name: str, prompt: str, temperature: float, max_tokens: int) -> str:
    config = genai.types.GenerationConfig(temperature=temperature, max_output_tokens=max_tokens)
    return genai.GenerativeModel(name).generate_content(prompt, generation_config=config).text


def generate_chat(messages: list[dict], temperature: float = 0.9, max_tokens: int = 2000, effort: str = "medium") -> str:
    """messages: [{"role": "system"|"user"|"assistant", "content": str}, ...]"""
    attempts = []
    if settings.GROQ_API_KEY:
        attempts.append(("groq/" + settings.GROQ_MODEL, lambda: _groq(messages, temperature, max_tokens, effort)))
    for name in (_GEMINI_MODELS if settings.GEMINI_API_KEY else []):
        attempts.append(("gemini/" + name, lambda n=name: _gemini(n, _flatten(messages), temperature, max_tokens)))
    last_error = None
    for label, fn in attempts:
        try:
            return fn()
        except (ResourceExhausted, httpx.HTTPError, RuntimeError, ValueError) as e:
            print(f"LLM {label} failed ({type(e).__name__}: {str(e)[:120]}), trying next")
            last_error = e
    raise last_error or RuntimeError("No LLM configured: set GROQ_API_KEY or GEMINI_API_KEY in .env")


def generate_reply(prompt: str, temperature: float = 1.0, max_tokens: int = 2000) -> str:
    """Single-prompt helper (used for the style profile)."""
    return generate_chat([{"role": "user", "content": prompt}], temperature, max_tokens, effort="low")
