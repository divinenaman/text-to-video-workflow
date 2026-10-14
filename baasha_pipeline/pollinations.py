"""Pollinations.ai image generation - keyless free tier.

Anonymous access needs no API key at all:
``GET https://image.pollinations.ai/prompt/{prompt}``

Anonymous tier is roughly one request every 15s and single-concurrent per
IP (HTTP 402 when you exceed it), so this module paces itself and retries
with backoff. Anonymous requests are downgraded to the ``sana`` model by the
server; add ``[SECRETS] POLLINATIONS_KEY`` (free signup at
https://enter.pollinations.ai) to get ``flux`` and raise the limits.
"""

import time
from typing import List, Optional, Tuple
from urllib.parse import quote
from uuid import uuid4

import requests

from . import object_storage
from .configs import app_config
from .logger import logging

BASE_URL = "https://image.pollinations.ai/prompt/{prompt}"

DEFAULT_MODEL = "flux"
REQUEST_TIMEOUT = 120
PACE_SECONDS = 12
MAX_ATTEMPTS = 4

DEFAULT_RATIO = {
    "1:1": (1, 1),
    "9:16": (9, 16),
    "16:9": (16, 9),
    "4:7": (4, 7),
    "7:4": (7, 4),
    "2:3": (2, 3),
    "3:2": (3, 2),
    "4:5": (4, 5),
    "5:4": (5, 4),
    "3:4": (3, 4),
    "4:3": (4, 3),
}

LONG_SIDE = {"0.5K": 768, "0.5k": 768, "1K": 1024, "1k": 1024, "2K": 1536, "2k": 1536}


def get_key() -> Optional[str]:
    val = app_config.get().get("auth", {}).get("pollinations_key")
    return (val or "").strip() or None


def resolve_size(
    width: Optional[int] = None,
    height: Optional[int] = None,
    aspect_ratio: str = "9:16",
    image_resolution: str = "1K",
) -> Tuple[int, int]:
    if width and height:
        return int(width), int(height)

    num, den = DEFAULT_RATIO.get(aspect_ratio, (9, 16))
    long_side = LONG_SIDE.get(image_resolution, 1024)

    if num >= den:
        w = long_side
        h = int(long_side * den / float(num))
    else:
        h = long_side
        w = int(long_side * num / float(den))

    return w, h


def generate_image(
    prompt: str,
    width: Optional[int] = None,
    height: Optional[int] = None,
    aspect_ratio: str = "9:16",
    image_resolution: str = "1K",
    model: str = DEFAULT_MODEL,
    ref: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """Returns ``(public_url, error)``."""
    if ref:
        logging.info("pollinations: reference images not supported, ref dropped")

    w, h = resolve_size(width, height, aspect_ratio, image_resolution)

    params: dict = {
        "width": w,
        "height": h,
        "model": model,
        "nologo": "true",
        "private": "true",
        "seed": int(time.time()) % 100000000,
    }
    key = get_key()
    if key:
        params["key"] = key

    url = BASE_URL.format(prompt=prompt.replace("/", "%2F").replace(" ", "%20"))
    last_err = None

    for attempt in range(MAX_ATTEMPTS):
        try:
            resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        except Exception as e:
            last_err = str(e)
            time.sleep(5 * (attempt + 1))
            continue

        if resp.status_code in (402, 429, 500, 502, 503):
            last_err = f"HTTP {resp.status_code}"
            time.sleep(PACE_SECONDS * (attempt + 1))
            continue

        if resp.status_code != 200:
            last_err = f"HTTP {resp.status_code} - {resp.text[:300]}"
            break

        content_type = (resp.headers.get("content-type") or "").lower()
        if not content_type.startswith("image") or len(resp.content) < 1024:
            last_err = (
                f"non-image response ({content_type}, {len(resp.content)} bytes) "
                f"- {resp.text[:300]}"
            )
            break

        try:
            public_url = object_storage.upload_data(
                object_storage.ASSETS_IMG_BUCKET,
                resp.content,
                f"{uuid4()}_pollinations.jpg",
                object_storage.ACL_PUBLIC,
            )
            return public_url, None
        except Exception as e:
            return None, f"upload failed - {e}"

    return None, last_err or "pollinations image generation failed"


def generate_images(
    prompts: List[str],
    refs: Optional[list] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    aspect_ratio: str = "9:16",
    image_resolution: str = "1K",
    negative_prompt: Optional[str] = None,
) -> Tuple[List[Optional[str]], List[Optional[str]]]:
    results: List[Optional[str]] = []
    errors: List[Optional[str]] = []

    for p in prompts:
        logging.info(f"pollinations: generating image - {p[:120]}")
        url, err = generate_image(
            p,
            width=width,
            height=height,
            aspect_ratio=aspect_ratio,
            image_resolution=image_resolution,
        )
        if err:
            logging.error(f"pollinations: {err}")
        results.append(url)
        errors.append(err)
        time.sleep(PACE_SECONDS)

    return results, errors
