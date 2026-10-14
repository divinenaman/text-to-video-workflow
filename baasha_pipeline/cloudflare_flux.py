"""Cloudflare Workers AI image generation (free tier, no credit card).

Uses the 10,000 Neurons/day free allocation on the Workers Free plan.
FLUX.1 [schnell] bills **172.8 Neurons per image** on this account, so the
daily pool covers ~57 generations (resets 00:00 UTC).

The live endpoint only accepts ``prompt`` + ``steps`` - it always returns a
1024x1024 JPEG and rejects ``width`` / ``height`` / ``image_size`` /
``num_images`` / ``seed`` with HTTP 400. Aspect ratio is therefore applied
here by center-cropping the square.

Requires ``[SECRETS] CLOUDFLARE_ACCOUNT_ID`` and ``CLOUDFLARE_API_TOKEN``
in config.secrets.ini (both free to create).
"""

import base64
import time
from io import BytesIO
from typing import List, Optional, Tuple
from uuid import uuid4

import requests
from PIL import Image

from . import object_storage
from .configs import app_config
from .logger import logging

MODEL = "@cf/black-forest-labs/flux-1-schnell"
BASE_URL = "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/" + MODEL

SOURCE_SIZE = 1024
STEPS = 4

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

REQUEST_TIMEOUT = 180


def get_account_id() -> Optional[str]:
    val = app_config.get().get("auth", {}).get("cloudflare_account_id")
    return (val or "").strip() or None


def get_token() -> Optional[str]:
    val = app_config.get().get("auth", {}).get("cloudflare_token")
    return (val or "").strip() or None


def resolve_size(
    width: Optional[int] = None,
    height: Optional[int] = None,
    aspect_ratio: str = "9:16",
    image_resolution: str = "1K",
) -> Tuple[int, int]:
    """Target output size *after* the center-crop."""
    if width and height:
        return int(width), int(height)

    num, den = DEFAULT_RATIO.get(aspect_ratio, (9, 16))
    long_side = LONG_SIDE.get(image_resolution, 1024)

    w: float
    h: float
    if num >= den:
        w = float(long_side)
        h = float(long_side) * den / float(num)
    else:
        h = float(long_side)
        w = float(long_side) * num / float(den)

    return int(w), int(h)


def _crop_to_aspect(image_bytes: bytes, out_w: int, out_h: int) -> bytes:
    """Center-crop the 1024x1024 square to ``out_w`` x ``out_h``."""
    src = Image.open(BytesIO(image_bytes)).convert("RGB")

    target = out_w / float(out_h)
    src_w, src_h = src.size

    if src_w / float(src_h) > target:
        crop_h = src_h
        crop_w = int(round(src_h * target))
    else:
        crop_w = src_w
        crop_h = int(round(src_w / target))

    left = (src_w - crop_w) // 2
    top = (src_h - crop_h) // 2
    cropped = src.crop((left, top, left + crop_w, top + crop_h))

    if (out_w, out_h) != (crop_w, crop_h):
        cropped = cropped.resize((out_w, out_h), Image.LANCZOS)

    buf = BytesIO()
    cropped.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def generate_image(
    prompt: str,
    width: Optional[int] = None,
    height: Optional[int] = None,
    aspect_ratio: str = "9:16",
    image_resolution: str = "1K",
    ref: Optional[str] = None,
    retry: int = 2,
) -> Tuple[Optional[str], Optional[str]]:
    """Returns ``(public_url, error)``."""
    token = get_token()
    account_id = get_account_id()

    if not token or not account_id:
        return None, "cloudflare credentials not configured"

    if ref:
        logging.info(
            "cloudflare_flux: flux-1-schnell is text-to-image only, ref dropped"
        )

    out_w, out_h = resolve_size(width, height, aspect_ratio, image_resolution)
    url = BASE_URL.format(account_id=account_id)
    body = {"prompt": prompt, "steps": STEPS}

    last_err = None
    for attempt in range(retry + 1):
        try:
            resp = requests.post(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=body,
                timeout=REQUEST_TIMEOUT,
            )
        except Exception as e:
            last_err = str(e)
            time.sleep(2 * (attempt + 1))
            continue

        if resp.status_code in (429, 500, 502, 503):
            last_err = f"HTTP {resp.status_code}"
            time.sleep(5 * (attempt + 1))
            continue

        if resp.status_code != 200:
            last_err = f"HTTP {resp.status_code} - {resp.text[:400]}"
            break

        try:
            data = resp.json()
        except Exception as e:
            last_err = f"bad json - {e}"
            break

        if data.get("success") is False:
            last_err = str(data.get("errors"))[:400]
            break

        result = data.get("result") or {}
        b64 = result.get("image")
        if not b64:
            last_err = f"no image in response - {str(data)[:400]}"
            break

        neurons = (result.get("usage") or {}).get("neurons")
        if neurons:
            logging.info(f"cloudflare_flux: used {neurons} Neurons")

        try:
            image_bytes = _crop_to_aspect(base64.b64decode(b64), out_w, out_h)
            public_url = object_storage.upload_data(
                object_storage.ASSETS_IMG_BUCKET,
                image_bytes,
                f"{uuid4()}_cf_flux.jpg",
                object_storage.ACL_PUBLIC,
            )
            return public_url, None
        except Exception as e:
            return None, f"upload failed - {e}"

    return None, last_err or "cloudflare image generation failed"


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
        logging.info(f"cloudflare_flux: generating image - {p[:120]}")
        url, err = generate_image(
            p,
            width=width,
            height=height,
            aspect_ratio=aspect_ratio,
            image_resolution=image_resolution,
        )
        if err:
            logging.error(f"cloudflare_flux: {err}")
        results.append(url)
        errors.append(err)
        time.sleep(1)

    return results, errors
