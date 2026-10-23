"""Headless Lottie rendering via Playwright + lottie-web.

Generalizes ``motion_graphics_agent.test_lottie``: seeks deterministic frames
(``goToAndStop``) and returns a PIL contact sheet instead of a single autoplay
screenshot. Used by gates G1 (render sanity) and G2/G3 (vision judging).
"""

from __future__ import annotations

import io
import json
import threading
from typing import List, Optional, Sequence, Tuple

from ..logger import logging
from .. import errors

_LOTTIE_CDN = "https://cdnjs.cloudflare.com/ajax/libs/lottie-web/5.13.0/lottie.min.js"


class LottieBrowserManager:
    """Thread-safe lazy Playwright Firefox manager (mirrors motion_graphics_agent)."""

    def __init__(self, headless: bool = True):
        self.headless = headless
        self._playwright = None
        self._browser = None
        self._lock = threading.Lock()

    def start(self):
        with self._lock:
            if not self._browser:
                from playwright.sync_api import sync_playwright

                self._playwright = sync_playwright().start()
                self._browser = self._playwright.firefox.launch(headless=self.headless)
        return self

    def stop(self):
        with self._lock:
            if self._browser:
                self._browser.close()
                self._browser = None
            if self._playwright:
                self._playwright.stop()
                self._playwright = None

    def get_page(self):
        if not self._browser:
            self.start()
        return self._browser.new_page()

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()


def _seek_html(lottie_json: dict, frame: int) -> str:
    payload = json.dumps(lottie_json)
    return f"""
    <!DOCTYPE html>
    <html><head>
    <script src="{_LOTTIE_CDN}"></script>
    <style>html,body{{margin:0;padding:0;background:#fff;overflow:hidden}}
    #c{{width:{lottie_json.get('w', 512)}px;height:{lottie_json.get('h', 512)}px}}</style>
    </head><body>
    <div id="c"></div>
    <script>
      var anim = lottie.loadAnimation({{
        container: document.getElementById('c'),
        renderer: 'svg',
        loop: false,
        autoplay: false,
        animationData: {payload}
      }});
      anim.addEventListener('DOMLoaded', function() {{
        anim.goToAndStop({frame}, true);
      }});
    </script>
    </body></html>
    """


@errors.log_ctx_errors
def render_frame(
    lottie_json: dict,
    frame: int,
    browser: Optional[LottieBrowserManager] = None,
    timeout_ms: int = 45000,
) -> bytes:
    """Render a single frame of a Lottie doc to PNG bytes."""
    owns = browser is None
    bm = browser or LottieBrowserManager()
    page = None
    last_err: Optional[Exception] = None
    try:
        for attempt in range(2):
            try:
                if owns:
                    bm.start()
                if page is None:
                    page = bm.get_page()
                page.set_viewport_size(
                    {"width": int(lottie_json.get("w", 512)), "height": int(lottie_json.get("h", 512))}
                )
                page.set_content(_seek_html(lottie_json, frame))
                page.wait_for_function(
                    "window.anim && window.anim.isLoaded && document.querySelectorAll('#c svg *').length > 0",
                    timeout=timeout_ms,
                )
                page.evaluate("(f) => window.anim.goToAndStop(f, true)", frame)
                page.wait_for_timeout(250)
                png = page.screenshot(
                    type="png",
                    clip={"x": 0, "y": 0, "width": int(lottie_json.get("w", 512)), "height": int(lottie_json.get("h", 512))},
                )
                if png:
                    return png
                last_err = RuntimeError("empty screenshot")
            except Exception as e:  # CDN fetch / paint race / lottie load flake
                last_err = e
            finally:
                if page is not None:
                    try:
                        page.close()
                    except Exception:
                        pass
                    page = None
            logging.warning(f"render_frame attempt {attempt + 1}/2 failed for frame {frame}: {last_err}")
        raise last_err if last_err else RuntimeError("render_frame failed")
    finally:
        if owns:
            bm.stop()


def _contact_sheet(pils: Sequence, cols: Optional[int] = None, pad: int = 8):
    from PIL import Image

    n = len(pils)
    if n == 0:
        raise ValueError("no frames to montage")
    cols = cols or min(n, 4)
    rows = (n + cols - 1) // cols
    w = max(im.width for im in pils)
    h = max(im.height for im in pils)
    sheet = Image.new("RGB", (cols * w + pad * (cols + 1), rows * h + pad * (rows + 1)), "#e8e8e8")
    for i, im in enumerate(pils):
        r, c = divmod(i, cols)
        x = pad + c * (w + pad) + (w - im.width) // 2
        y = pad + r * (h + pad) + (h - im.height) // 2
        sheet.paste(im.convert("RGB"), (x, y))
    return sheet


@errors.log_ctx_errors
def render_contact_sheet(
    lottie_json: dict,
    frames: Sequence[int],
    browser: Optional[LottieBrowserManager] = None,
    cols: Optional[int] = None,
):
    """Render N frames and return a single PIL contact-sheet image."""
    from PIL import Image

    owns = browser is None
    bm = browser or LottieBrowserManager()
    pils = []
    try:
        if owns:
            bm.start()
        for f in frames:
            png = render_frame(lottie_json, int(f), browser=bm)
            pils.append(Image.open(io.BytesIO(png)))
        return _contact_sheet(pils, cols=cols)
    finally:
        if owns:
            bm.stop()


@errors.log_ctx_errors
def frame_is_nonblank(png_bytes: bytes, ink_threshold: float = 0.005) -> bool:
    """Cheap G1 check: fraction of non-background pixels above threshold."""
    import numpy as np
    from PIL import Image

    im = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    arr = np.asarray(im, dtype=np.int16)
    # background assumed near-white or near-uniform; count pixels differing from mode corner
    corner = arr[0, 0]
    diff = np.abs(arr - corner).sum(axis=2)
    ink = float((diff > 18).mean())
    return ink >= ink_threshold


@errors.log_ctx_errors
def render_keyframes(
    lottie_json: dict,
    n: int = 3,
    browser: Optional[LottieBrowserManager] = None,
) -> List[Tuple[int, bytes]]:
    """Render ``n`` evenly spaced frames (G1 default sampling)."""
    op = int(lottie_json.get("op", 1))
    ip = int(lottie_json.get("ip", 0))
    span = max(op - ip - 1, 0)
    if n <= 1:
        frames = [ip]
    else:
        frames = [ip + round(span * i / (n - 1)) for i in range(n)]
    owns = browser is None
    bm = browser or LottieBrowserManager()
    out: List[Tuple[int, bytes]] = []
    try:
        if owns:
            bm.start()
        for f in frames:
            out.append((f, render_frame(lottie_json, f, browser=bm)))
        return out
    finally:
        if owns:
            bm.stop()
