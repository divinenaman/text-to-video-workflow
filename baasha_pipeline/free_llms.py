"""Free (no credit card) OpenAI-style LLM providers.

Providers here only need a free API key:

  - OpenRouter ``:free`` models  -> https://openrouter.ai/keys
  - Cloudflare Workers AI        -> https://dash.cloudflare.com/api-tokens
"""

import base64
from typing import List, Optional

import requests

from .configs import app_config

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Verified working (Oct 2026) on the free tier, best-first.
#   - `openrouter/free` is NOT used: it routes to random models, including
#     nvidia/nemotron-3.5-content-safety which ignores the prompt entirely.
#   - `thinkingmachines/inkling*:free` is 403 (agentic-harness only).
#   - `nvidia/nemotron-3-nano-omni*:free` is 502 (upstream exhausted).
OPENROUTER_DEFAULT_MODEL = "dots-studio/dots-3-note-preview:free"
OPENROUTER_MODEL_FALLBACKS = [
    "dots-studio/dots-3-note-preview:free",
    "google/gemma-4-26b-a4b-it:free",
    "google/gemma-4-31b-it:free",
]

CLOUDFLARE_RUN_URL = (
    "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}"
)
CLOUDFLARE_DEFAULT_MODEL = "@cf/meta/llama-4-scout-17b-16e-instruct"
CLOUDFLARE_MAX_TOKENS = 4096

REQUEST_TIMEOUT = 180


def get_key(name: str) -> Optional[str]:
    val = app_config.get().get("auth", {}).get(name)
    if isinstance(val, list):
        val = val[0] if val else None
    val = (val or "").strip()
    return val or None


def _data_url(img) -> str:
    if isinstance(img, str):
        return img
    if isinstance(img, (bytes, bytearray)):
        return "data:image/png;base64," + base64.b64encode(bytes(img)).decode("utf-8")
    raise Exception(f"free_llms: unsupported image payload - {type(img)}")


def build_messages(
    ctx: Optional[list],
    text: Optional[str],
    imgs: Optional[List] = None,
    system: Optional[str] = None,
) -> list:
    """Build an OpenAI-style ``messages`` array.

    ``ctx`` entries may be ``{"role", "content"}`` dicts or legacy
    ``(role, text)`` tuples (the Groq ctx format).
    """
    messages: list = []

    if system:
        messages.append({"role": "system", "content": system})

    for c in ctx or []:
        if isinstance(c, dict):
            messages.append(
                {
                    "role": c.get("role", "user"),
                    "content": c.get("content", ""),
                }
            )
        elif isinstance(c, (list, tuple)) and len(c) >= 2:
            messages.append({"role": c[0], "content": c[1]})

    imgs = imgs or []
    if imgs:
        content: list = [
            {"type": "text", "text": text or "Describe the attached image(s)."}
        ]
        for im in imgs:
            content.append({"type": "image_url", "image_url": {"url": _data_url(im)}})
        messages.append({"role": "user", "content": content})
    elif text is not None:
        messages.append({"role": "user", "content": text})

    return messages


def _extract_content(data: dict) -> str:
    choices = data.get("choices") or []
    if not choices:
        raise Exception(f"empty choices - {str(data)[:500]}")

    content = (choices[0].get("message") or {}).get("content")
    if content is None:
        content = choices[0].get("text")

    if isinstance(content, list):
        content = "".join(p.get("text", "") for p in content if isinstance(p, dict))

    if content is None:
        raise Exception(f"no content in response - {str(data)[:500]}")

    return content


def openrouter_fetch_text(
    key: str,
    ctx: Optional[list],
    text: Optional[str],
    imgs: Optional[List] = None,
    system: Optional[str] = None,
    model: Optional[str] = None,
    model_fallbacks: Optional[List[str]] = None,
) -> str:
    messages = build_messages(ctx, text, imgs, system)

    candidates = list(
        dict.fromkeys(model_fallbacks or [model or OPENROUTER_DEFAULT_MODEL])
    )
    last_err = None

    for cand in candidates:
        try:
            resp = requests.post(
                f"{OPENROUTER_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                    "X-Title": "Baasha",
                },
                json={"model": cand, "messages": messages},
                timeout=REQUEST_TIMEOUT,
            )
        except Exception as e:
            last_err = f"{cand}: {e}"
            continue

        if resp.status_code != 200:
            last_err = f"{cand}: HTTP {resp.status_code} - {resp.text[:300]}"
            continue

        try:
            return _extract_content(resp.json())
        except Exception as e:
            last_err = f"{cand}: {e}"

    raise Exception(f"openrouter exhausted all models - {last_err}")


def cloudflare_fetch_text(
    key: str,
    account_id: str,
    ctx: Optional[list],
    text: Optional[str],
    imgs: Optional[List] = None,
    system: Optional[str] = None,
    model: Optional[str] = None,
) -> str:
    if not account_id:
        raise Exception("CLOUDFLARE_ACCOUNT_ID is not configured")

    model = model or CLOUDFLARE_DEFAULT_MODEL
    url = CLOUDFLARE_RUN_URL.format(account_id=account_id, model=model)

    payload = {
        "messages": build_messages(ctx, text, imgs, system),
        "stream": False,
        "max_tokens": CLOUDFLARE_MAX_TOKENS,
    }

    resp = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )

    if resp.status_code != 200:
        raise Exception(f"HTTP {resp.status_code} - {resp.text[:500]}")

    data = resp.json()

    if data.get("success") is False:
        raise Exception(f"cloudflare error - {str(data.get('errors'))[:500]}")

    result = data.get("result")
    if isinstance(result, dict) and result.get("response") is not None:
        out = result.get("response")
        if isinstance(out, list):
            return "".join(str(p) for p in out)
        return str(out)

    if data.get("choices"):
        return _extract_content(data)

    raise Exception(f"unrecognised response - {str(data)[:500]}")


def describe() -> dict:
    """Diagnostic helper - which free providers are actually configured."""
    return {
        "openrouter": bool(get_key("openrouter_key")),
        "cloudflare": bool(get_key("cloudflare_token"))
        and bool(get_key("cloudflare_account_id")),
    }
