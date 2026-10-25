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
GEMINI_REST_TIMEOUT = 180
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


POLLINATIONS_BASE_URL = "https://text.pollinations.ai/openai"
POLLINATIONS_DEFAULT_MODEL = "openai"
POLLINATIONS_BUDGET_MARKERS = ("reached its budget", "raise the key budget")
POLLINATIONS_MIN_INTERVAL = 31.0
# The default output cap truncates code/JSON mid-token (unclosed-paren
# SyntaxError in rig sources, content=null reasoning-only envelopes).
POLLINATIONS_MAX_TOKENS = 8192
# gpt-oss defaults to heavy reasoning which eats the output budget and
# leaves content truncated/empty. 'low' verified to return complete code
# ('minimal' is rejected with HTTP 400 by the endpoint).
POLLINATIONS_REASONING_EFFORT = "low"
_POLLINATIONS_LOCK = __import__("threading").Lock()
_POLLINATIONS_LAST = [0.0]


def pollinations_fetch_text(
    ctx: Optional[list],
    text: Optional[str],
    imgs: Optional[List] = None,
    system: Optional[str] = None,
    model: Optional[str] = None,
    attempts: int = 3,
) -> str:
    """Keyless OpenAI-compatible endpoint (text.pollinations.ai).

    Used as the primary provider while CF/openrouter free tiers are
    exhausted; budget/throttle replies are retried, never returned as content.
    """
    import re
    import threading
    import time

    if imgs:
        # the anonymous text tier rejects image content; fail fast so the
        # provider chain can move on instead of burning retry windows
        raise Exception("pollinations: image input not supported by text tier")

    messages = build_messages(ctx, text, imgs, system)
    token_param = "max_tokens"
    effort_param = "reasoning_effort"
    payload = {
        "model": model or POLLINATIONS_DEFAULT_MODEL,
        "messages": messages,
        "stream": False,
        token_param: POLLINATIONS_MAX_TOKENS,
        effort_param: POLLINATIONS_REASONING_EFFORT,
    }
    last_err = None
    for i in range(max(1, attempts)):
        # Global per-IP spacing: the anonymous tier allows ~1 reply / 30s.
        # Serialize all pollinations calls process-wide so concurrent pipeline
        # threads do not burn the shared window on 402s.
        with _POLLINATIONS_LOCK:
            gap = POLLINATIONS_MIN_INTERVAL - (time.time() - _POLLINATIONS_LAST[0])
            if gap > 0:
                time.sleep(gap)
            try:
                resp = requests.post(
                    POLLINATIONS_BASE_URL, json=payload, timeout=REQUEST_TIMEOUT
                )
                _POLLINATIONS_LAST[0] = time.time()
            except Exception as e:
                _POLLINATIONS_LAST[0] = time.time()
                last_err = str(e)
                resp = None
            if resp is not None and resp.status_code != 200:
                last_err = f"HTTP {resp.status_code} - {resp.text[:300]}"
                rtxt = resp.text or ""
                if resp.status_code == 400 and effort_param and "reasoning_effort" in rtxt:
                    payload.pop(effort_param, None)
                    effort_param = None
                    continue
                if resp.status_code == 400 and token_param and (
                    "max_tokens" in rtxt or "max_completion_tokens" in rtxt
                ):
                    # adapt: try the modern param name, then give up on hints
                    if token_param == "max_tokens":
                        payload.pop("max_tokens", None)
                        token_param = "max_completion_tokens"
                        payload[token_param] = POLLINATIONS_MAX_TOKENS
                    else:
                        payload.pop("max_completion_tokens", None)
                        payload.pop("max_tokens", None)
                        token_param = None
                    continue
                m = re.search(r"Retry after (\d+)s", rtxt)
                wait = int(m.group(1)) + 3 if m else POLLINATIONS_MIN_INTERVAL + 3
                if i < attempts - 1:
                    time.sleep(wait)
                continue
            if resp is not None:
                data = None
                try:
                    data = resp.json()
                except Exception:
                    data = None
                t = None
                if isinstance(data, dict):
                    try:
                        t = _extract_content(data)
                    except Exception as e:
                        # content=null: token budget spent on reasoning only.
                        # NEVER return the raw API envelope as model output;
                        # give one clean retry, then salvage the reasoning text
                        # (downstream parsers slice JSON/code out of prose).
                        msg = (
                            ((data.get("choices") or [{}])[0] or {}).get("message")
                            or {}
                        )
                        reasoning = (
                            msg.get("reasoning") or msg.get("reasoning_content") or ""
                        )
                        if i >= 1 and isinstance(reasoning, str) and reasoning.strip():
                            t = reasoning.strip()
                        else:
                            last_err = (
                                "reasoning-only reply, no content - "
                                + str(e)[:160]
                            )
                            t = None
                else:
                    t = (resp.text or "").strip()
                low = (t or "").lower()
                if t and not any(m in low for m in POLLINATIONS_BUDGET_MARKERS):
                    return t
                last_err = f"bad reply - {str(t)[:200] if t else 'empty'}"
        if i < attempts - 1:
            time.sleep(4)
    raise Exception(f"pollinations failed after {attempts} attempts - {last_err}")


def describe() -> dict:
    """Diagnostic helper - which free providers are actually configured."""
    return {
        "openrouter": bool(get_key("openrouter_key")),
        "cloudflare": bool(get_key("cloudflare_token"))
        and bool(get_key("cloudflare_account_id")),
    }


def gemini_rest_fetch_text(
    key: str,
    ctx: Optional[list],
    text: Optional[str],
    imgs: Optional[List] = None,
    system: Optional[str] = None,
    model: Optional[str] = None,
) -> str:
    """Google Generative Language REST call with a hard client timeout.

    The legacy google-generativeai SDK (0.5.4) has no per-request deadline and
    can hang for tens of minutes on thinking models; REST + REQUEST_TIMEOUT
    keeps codegen calls bounded.
    """
    if not key:
        raise Exception("GOOGLE_GENAI_KEY is not configured")

    model = model or "gemini-3.8-flash"
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={key}"
    )

    parts: list = []
    if text:
        parts.append({"text": text})
    for img in imgs or []:
        if isinstance(img, bytes):
            parts.append(
                {"inline_data": {"mime_type": "image/png", "data": base64.b64encode(img).decode()}}
            )
    contents = [{"role": "user", "parts": parts}] if parts else []
    for c in reversed(ctx or []):
        if isinstance(c, dict):
            contents.insert(0, c)
        else:
            contents.insert(0, {"role": c[0], "parts": [{"text": c[1]}]})
    if system:
        contents.insert(
            0, {"role": "user", "parts": [{"text": system}]}
        )

    payload = {
        "contents": contents,
        "safetySettings": [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ],
        "generationConfig": {
            "maxOutputTokens": 65536,
            "temperature": 0.7,
            "thinkingConfig": {"thinkingBudget": 8192},
        },
    }

    resp = requests.post(url, json=payload, timeout=GEMINI_REST_TIMEOUT)
    if resp.status_code != 200:
        raise Exception(f"HTTP {resp.status_code} - {resp.text[:400]}")

    data = resp.json()
    if "error" in data:
        raise Exception(f"gemini error - {str(data['error'])[:400]}")
    cand = (data.get("candidates") or [{}])[0]
    out = ""
    for part in cand.get("content", {}).get("parts", []):
        out += part.get("text", "")
    if not out:
        raise Exception(
            f"gemini empty reply - finishReason={cand.get('finishReason')} "
            f"promptFeedback={str(data.get('promptFeedback'))[:150]}"
        )
    return out
