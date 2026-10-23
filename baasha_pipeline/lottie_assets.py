"""Lottie leaf functions: LLM authoring loop (G0-G2) + artifact uploads.

Pipeline leaves that substitute diffusion image generation. Source of truth
is Python (S3 ``source.py``); compiled Lottie JSON and preview PNGs are
artifacts. Preview PNG keeps ``character_ref.url`` compatible with the
existing grid judge and UI.
"""

from __future__ import annotations

import io
import json
import os
import traceback
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from .logger import logging
from . import errors, object_storage
from .configs import app_config
from .chatbot import Img, ChatInterface
from .lottie_sdk import (
    CharacterRig,
    LottieBrowserManager,
    Scene,
    render_contact_sheet,
    render_keyframes,
    slugify,
)
from .lottie_sdk.author import (
    AuthorExecError,
    exec_rig_source,
    exec_scene_source,
    gate_rig_g0,
    gate_scene_g0,
)
from .lottie_sdk.validate import LottieValidationError
from .lottie_sdk.playbook import match_playbook
from .prompts.splitters import markdown_parse

PASS_SCORE = 85
RIG_PASS_SCORE = 75
MAX_GATE_ITERS = 4


def _errors_block(errors: List[str]) -> str:
    """Gate errors + the playbook quick-guide block (empty when no match)."""
    base = "\n".join(str(e) for e in errors)
    guide = match_playbook(list(errors))
    return f"{base}\n{guide}" if guide else base

# Image-generation directives leaked into character bible descriptions; they
# confuse rig authoring and make the vision judge penalize the 3-frame contact
# sheet ("SINGLE FRAME ONLY").
_DNA_BOILERPLATE = (
    "SINGLE FRAME ONLY.",
    "NO GRIDS.",
    "CRITICAL: Extract the EXACT physical face/identity from the Character Reference.",
    "COMPLETELY IGNORE the faces/identities of any characters in the Style Reference.",
    "Use the Style Reference ONLY for lighting, color grading, and texture.",
    "NEVER replicate the grid layout of the Style Reference.",
)


def _clean_visual_dna(text: str) -> str:
    if not text:
        return text or ""
    out = text
    for b in _DNA_BOILERPLATE:
        out = out.replace(b, " ")
    return " ".join(out.split())


def _ask(chatbot, payload, attempts: int = 3, text_degrade: bool = True) -> str:
    """chatbot.fetch_text with retries. Never raises - returns '' on total
    failure so an LLM outage degrades the gate loop instead of killing the draft.

    When an image payload keeps failing (vision providers dead), the remaining
    attempts retry with the fix TEXT only - it still carries the ERRORS block,
    so blank-frame / placement fixes keep working on text-only providers.
    Judges pass text_degrade=False: a text-only audit would hallucinate a score.
    """
    import time as _time

    def _text_only(p):
        if isinstance(p, list):
            return "\n\n".join(
                x.text if isinstance(x, Img) else str(x) for x in p
            )
        if isinstance(p, Img):
            return p.text
        return p

    last: object = None
    degraded = False
    for i in range(attempts):
        try:
            out = chatbot.fetch_text(payload)
            if out and str(out).strip():
                # attribution aid: which shape did the provider actually return
                logging.info(
                    f"lottie ask ok attempt {i+1} chars={len(str(out))} "
                    f"tail={str(out)[-70:]!r}"
                )
                return out
            last = "empty response"
        except Exception as e:
            last = e
        if text_degrade and not degraded:
            conv = _text_only(payload)
            if conv != payload:
                payload = conv
                degraded = True
                logging.warning(
                    f"lottie ask degrading image payload to text-only ({last})"
                )
        if i < attempts - 1:
            delay = 4 * (i + 1)
            logging.warning(
                f"lottie ask attempt {i+1}/{attempts} failed ({last!r}); retrying in {delay}s"
            )
            _time.sleep(delay)
    logging.error(f"lottie ask failed after {attempts} attempts: {last!r}")
    return ""


def _load_prompt(name: str) -> str:
    path = os.path.join(os.path.dirname(__file__), "..", "prompts.json")
    with open(path) as f:
        lib = json.load(f)
    entry = lib.get(name)
    if not entry:
        raise errors.BaashaError(f"missing prompt: {name}")
    return entry["text"]


def _fetch_json(url: str) -> dict:
    import requests

    res = requests.get(url, timeout=60)
    res.raise_for_status()
    return res.json()


def _fetch_text(url: str) -> str:
    import requests

    res = requests.get(url, timeout=60)
    res.raise_for_status()
    return res.text


def _upload_triple(
    outdir_rel: str, slug: str, source: str, lottie_doc: dict, preview_bytes: Optional[bytes]
) -> Dict[str, str]:
    """Upload source.py + animation.json + preview.png; return public URLs."""
    base = f"{outdir_rel}/{slug}"
    source_url = object_storage.upload_data(
        object_storage.ASSETS_VIDEO_CONFIG,
        source,
        f"{base}/source.py",
        object_storage.ACL_PUBLIC,
    )
    lottie_url = object_storage.upload_data(
        object_storage.ASSETS_VIDEO_CONFIG,
        json.dumps(lottie_doc),
        f"{base}/animation.json",
        object_storage.ACL_PUBLIC,
    )
    preview_url = None
    if preview_bytes:
        preview_url = object_storage.upload_file(
            object_storage.ASSETS_VIDEO_CONFIG,
            _tmp_write(preview_bytes, "png"),
            f"{base}/preview.png",
            object_storage.ACL_PUBLIC,
        )
    return {
        "source_url": source_url,
        "lottie_url": lottie_url,
        "preview_url": preview_url,
    }


def _tmp_write(data: bytes, ext: str) -> str:
    path = f"/tmp/{uuid4()}.{ext}"
    with open(path, "wb") as f:
        f.write(data)
    return path


def _judge_chatbot(chatbot):
    """Route vision judging to the dedicated judge chain (config:
    chatbot_judge), falling back to the caller's chatbot."""
    cfg = app_config.get().get("chatbot_judge")
    if not cfg or not str(cfg).strip():
        return chatbot
    if not hasattr(_judge_chatbot, "_cache"):
        try:
            _judge_chatbot._cache = ChatInterface(str(cfg).strip())
        except Exception as e:
            logging.warning(f"lottie: judge chain unavailable ({e}); using primary")
            _judge_chatbot._cache = chatbot
    return _judge_chatbot._cache


def _vision_judge(
    chatbot,
    contact_sheet_bytes: bytes,
    spec_text: str,
    character_list_json: str = "[]",
    prompt_key: str = "lottie-judge",
) -> Optional[dict]:
    prompt = _load_prompt(prompt_key).format(
        SPEC=spec_text, CHARACTER_LIST=character_list_json
    )
    chatbot = _judge_chatbot(chatbot)
    try:
        out = _ask(chatbot, Img(_bytes=contact_sheet_bytes, text=prompt), text_degrade=False)
        if not out:
            return None
        raw = markdown_parse(out, lang="json")
        if not raw or not raw.strip():
            raw = out.strip()
        report = json.loads(raw)
        return report
    except Exception as e:
        logging.error(f"lottie vision judge failed: {e}")
        return None


def _sheet_bytes(contact_sheet) -> bytes:
    buf = io.BytesIO()
    contact_sheet.save(buf, format="PNG")
    return buf.getvalue()


def author_character_rig(
    chatbot,
    char_name: str,
    description: str,
    style_context: str = "",
    complexity: str = "L1",
    outdir: str = "lottie/tmp",
    use_vision_judge: bool = True,
    max_iters: int = MAX_GATE_ITERS,
) -> Optional[Dict[str, Any]]:
    """Author, gate, and upload a character rig. Returns character_ref entry."""
    description = _clean_visual_dna(description) or "A clear, distinctive character."
    rig_prompt = _load_prompt("lottie-character-rig").format(
        NAME=char_name,
        DESCRIPTION=description,
        STYLE=style_context or "none",
        COMPLEXITY=complexity,
    )
    fix_prompt_tpl = _load_prompt("lottie-character-fix")

    source = _ask(chatbot, rig_prompt)
    if not source:
        logging.error(f"character rig initial generation empty: {char_name}")
        return {
            "name": char_name,
            "description": description,
            "url": None,
            "lottie_url": None,
            "lottie_source_url": None,
            "complexity": complexity,
            "image_engine": "lottie",
            "lottie_error": {
                "gate": "ask",
                "errors": ["LLM unavailable - initial rig generation returned no content"],
            },
        }
    last_errors: List[str] = []
    last_gate = "author"
    last_sheet: Optional[bytes] = None
    last_report: Optional[dict] = None
    unchanged = "palette, part names, overall silhouette"

    for it in range(max_iters):
        try:
            rig = exec_rig_source(source)
            doc = gate_rig_g0(rig)
            last_gate = "G1"
        except (AuthorExecError, LottieValidationError) as e:
            last_errors = [str(e)]
            logging.warning(f"character {char_name} G0 fail iter {it}: {e}")
            source = _ask(chatbot, 
                fix_prompt_tpl.format(
                    NAME=char_name,
                    DESCRIPTION=description,
                    SOURCE=source,
                    GATE="G0-static",
                    ERRORS=_errors_block(last_errors),
                    SCREENSHOTS_NOTE="",
                    UNCHANGED=unchanged,
                )
            )
            continue

        try:
            with LottieBrowserManager() as bm:
                frames = render_keyframes(doc, n=3, browser=bm)
                blanks = [f for f, png in frames if not _frame_ok(png)]
                sheet = render_contact_sheet(
                    doc, frames=[f for f, _ in frames], browser=bm
                )
                sheet_png = _sheet_bytes(sheet)
        except Exception as e:
            last_errors = [f"render failed: {e}"]
            last_gate = "G1"
            source = _ask(chatbot, 
                fix_prompt_tpl.format(
                    NAME=char_name,
                    DESCRIPTION=description,
                    SOURCE=source,
                    GATE="G1-render",
                    ERRORS=_errors_block(last_errors),
                    SCREENSHOTS_NOTE="",
                    UNCHANGED=unchanged,
                )
            )
            continue

        if blanks:
            last_errors = [
                f"blank frames: {blanks} - NOTHING is visible on the canvas. "
                "Every part is likely outside the canvas or fully transparent: "
                "check root part position=(x,y) values are inside the canvas "
                "and fill alpha > 0."
            ]
            last_gate = "G1"
            last_sheet = sheet_png
            source = _ask(chatbot, 
                [
                    Img(
                        _bytes=sheet_png,
                        text=fix_prompt_tpl.format(
                            NAME=char_name,
                            DESCRIPTION=description,
                            SOURCE=source,
                            GATE="G1-render",
                            ERRORS=_errors_block(last_errors),
                            SCREENSHOTS_NOTE="Attached: contact sheet of rendered frames. One or more frames are blank.",
                            UNCHANGED=unchanged,
                        ),
                    )
                ]
            )
            continue

        cropped = next(
            (e for _, png in frames if (e := _frame_cropped(png))), None
        )
        if cropped:
            last_errors = [
                "character is cut off at the edge of the canvas - "
                f"measured offender(s): {cropped}. Apply exactly the listed "
                "shift to every top-level part position (or scale all parts "
                "down) so the whole character sits inside with ~10% margin."
            ]
            last_gate = "G1-crop"
            last_sheet = sheet_png
            source = _ask(chatbot, 
                [
                    Img(
                        _bytes=sheet_png,
                        text=fix_prompt_tpl.format(
                            NAME=char_name,
                            DESCRIPTION=description,
                            SOURCE=source,
                            GATE="G1-render",
                            ERRORS=_errors_block(last_errors),
                            SCREENSHOTS_NOTE=f"Attached: contact sheet of rendered frames. The {cropped} edge crops the character.",
                            UNCHANGED=unchanged,
                        ),
                    )
                ]
            )
            continue

        last_sheet = sheet_png
        if use_vision_judge:
            report = _vision_judge(
                chatbot,
                sheet_png,
                f"Character '{char_name}': {description}",
                prompt_key="lottie-rig-judge",
            )
            last_report = report
            if report and not report.get("pass", False) and (
                int(report.get("consistency_score", 0)) < RIG_PASS_SCORE
                or any(
                    i.get("severity") == "critical" for i in report.get("issues", [])
                )
            ):
                last_gate = "G2-vision"
                issues = report.get("issues", [])
                last_errors = [i.get("issue", "") for i in issues] or ["below threshold"]
                directives = "\n".join(
                    f"- {i.get('fix_directive', i.get('issue', ''))}" for i in issues
                )
                source = _ask(chatbot, 
                    [
                        Img(
                            _bytes=sheet_png,
                            text=fix_prompt_tpl.format(
                                NAME=char_name,
                                DESCRIPTION=description,
                                SOURCE=source,
                                GATE="G2-vision",
                                ERRORS=_errors_block([f"score={report.get('consistency_score')}", directives]),
                                SCREENSHOTS_NOTE="Attached: current contact sheet.",
                                UNCHANGED=unchanged,
                            ),
                        )
                    ]
                )
                continue

        urls = _upload_triple(outdir, slugify(char_name), source, doc, sheet_png)
        entry = {
            "name": char_name,
            "description": description,
            "url": urls["preview_url"],
            "lottie_url": urls["lottie_url"],
            "lottie_source_url": urls["source_url"],
            "complexity": complexity,
            "image_engine": "lottie",
            "api_summary": rig.api_summary(),
        }
        if last_report:
            entry["lottie_score"] = last_report.get("consistency_score")
        logging.info(f"character rig accepted: {char_name} iter={it} urls={urls}")
        return entry

    logging.error(
        f"character rig failed all gates: {char_name} gate={last_gate} errors={last_errors}"
    )
    # Archive the last attempted (failed) authoring so blank-frame/truncation
    # failures can be diagnosed offline - source.py holds the fallback after this.
    try:
        object_storage.upload_data(
            object_storage.ASSETS_VIDEO_CONFIG,
            source,
            f"{outdir}/{slugify(char_name)}/authored_failed.py",
            object_storage.ACL_PUBLIC,
        )
    except Exception as e:
        logging.warning(f"could not archive failed rig source for {char_name}: {e}")
    # Graceful degradation: substitute a known-good template rig (renamed to
    # this character) so scenes can still instantiate the character instead of
    # silently dropping them from the video.
    try:
        from .lottie_sdk import build_example_rig

        base = build_example_rig().model_dump(mode="json")
        # Differentiate template palettes so fallback characters are not clones.
        desc_l = (description or "").lower()
        if any(
            w in desc_l
            for w in ("robot", "android", "mecha", "machine", "chassis", "metal")
        ):
            palette = {
                "torso": (0.34, 0.40, 0.47, 1.0),
                "left_arm": (0.34, 0.40, 0.47, 1.0),
                "right_arm": (0.34, 0.40, 0.47, 1.0),
                "left_leg": (0.24, 0.27, 0.30, 1.0),
                "right_leg": (0.24, 0.27, 0.30, 1.0),
                "head": (0.68, 0.72, 0.76, 1.0),
                "hair": (0.12, 0.14, 0.16, 1.0),
            }
            for p in base.get("parts", []):
                if p.get("name") in palette:
                    p["fill"] = list(palette[p["name"]])
        # Bake the real character name in so rehydration/api_summary match the
        # CHARACTERS dict key used by scene composition.
        base["name"] = char_name
        source = (
            "# baasha fallback template rig (LLM authoring failed; substituted)\n"
            "rig = CharacterRig(**" + repr(base) + ")\n"
        )
        rig = exec_rig_source(source)
        doc = gate_rig_g0(rig)
        with LottieBrowserManager() as bm:
            frames = render_keyframes(doc, n=3, browser=bm)
            sheet = render_contact_sheet(
                doc, frames=[f for f, _ in frames], browser=bm
            )
            sheet_png = _sheet_bytes(sheet)
        urls = _upload_triple(outdir, slugify(char_name), source, doc, sheet_png)
        logging.warning(
            f"character rig fallback template used for {char_name} "
            f"(original gate={last_gate}) urls={urls}"
        )
        return {
            "name": char_name,
            "description": description,
            "url": urls["preview_url"],
            "lottie_url": urls["lottie_url"],
            "lottie_source_url": urls["source_url"],
            "complexity": complexity,
            "image_engine": "lottie",
            "lottie_fallback": True,
            "lottie_error": {"gate": last_gate, "errors": last_errors},
        }
    except Exception as fb_e:
        logging.error(f"fallback rig failed for {char_name}: {fb_e}")

    return {
        "name": char_name,
        "description": description,
        "url": None,
        "lottie_url": None,
        "lottie_source_url": None,
        "complexity": complexity,
        "image_engine": "lottie",
        "lottie_error": {"gate": last_gate, "errors": last_errors},
        "lottie_source_last": source[-12000:] if source else None,
    }


def _frame_ok(png: bytes) -> bool:
    from .lottie_sdk.render import frame_is_nonblank

    return frame_is_nonblank(png)


def _frame_cropped(png: bytes) -> Optional[str]:
    """Detect content touching a frame edge (head/limbs cropped out).

    Rig frames render on a flat background, so any non-background pixel within
    1% of an edge means the character is cut off. Returns a description with
    the offending edge(s), measured ink position and a pixel correction the
    model can apply directly, e.g. ``left (ink x=2px; shift right by 51px)``.
    """
    import io as _io

    from PIL import Image

    try:
        im = Image.open(_io.BytesIO(png)).convert("RGB")
    except Exception:
        return None
    w, h = im.size
    mx = max(2, w // 100)
    my = max(2, h // 100)
    px = im.load()
    bg = px[0, 0]

    def differs(c) -> bool:
        return abs(c[0] - bg[0]) + abs(c[1] - bg[1]) + abs(c[2] - bg[2]) > 30

    step_x = max(1, w // 200)
    step_y = max(1, h // 200)
    minx = maxx = miny = maxy = None
    for y in range(0, h, step_y):
        for x in range(0, w, step_x):
            if differs(px[x, y]):
                if minx is None or x < minx:
                    minx = x
                if maxx is None or x > maxx:
                    maxx = x
                if miny is None or y < miny:
                    miny = y
                if maxy is None or y > maxy:
                    maxy = y
    if minx is None:
        return None
    margin_pad = min(w, h) // 20  # extra 5% breathing room in the suggestion
    details = []
    if minx <= mx:
        details.append(
            f"left: ink starts at x={minx}px - shift all part x by +{mx - minx + margin_pad}px (or scale down)"
        )
    if maxx >= w - mx:
        details.append(
            f"right: ink reaches x={maxx}px (canvas w={w}) - shift all part x by -{maxx - (w - mx) + margin_pad}px (or scale down)"
        )
    if miny <= my:
        details.append(
            f"top: ink starts at y={miny}px - shift all part y by +{my - miny + margin_pad}px (or scale down)"
        )
    if maxy >= h - my:
        details.append(
            f"bottom: ink reaches y={maxy}px (canvas h={h}) - shift all part y by -{maxy - (h - my) + margin_pad}px (or scale down)"
        )
    if not details:
        return None
    return " | ".join(details)


def compose_scene_lottie(
    chatbot,
    panel_descriptions: List[str],
    character_list: List[dict],
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
    duration: int = 90,
    complexity: str = "L1",
    outdir: str = "lottie/tmp",
    use_vision_judge: bool = True,
    max_iters: int = MAX_GATE_ITERS,
) -> List[Optional[Dict[str, Any]]]:
    """Compose one scene Lottie per panel description. Returns per-panel entries.

    Each entry: {preview_url, lottie_url, source_url, grid-compatible keys}.
    Previews montage into a grid PNG for the existing judge when desired.
    """
    rigs: Dict[str, CharacterRig] = {}
    api_lines: List[str] = []
    for c in character_list:
        if not c.get("lottie_source_url"):
            if c.get("lottie_url"):
                logging.error(
                    f"character {c.get('name')} has lottie_url but no source; cannot instantiate"
                )
            continue
        try:
            src = _fetch_text(c["lottie_source_url"])
            rig = exec_rig_source(src)
            # Keep api_summary name identical to the CHARACTERS key so the
            # model never confuses the display name with the dict key.
            if rig.name != c.get("name"):
                rig = CharacterRig(**{**rig.model_dump(), "name": c.get("name") or rig.name})
        except Exception as e:
            logging.error(f"failed to rehydrate rig {c.get('name')}: {e}")
            continue
        rigs[c["name"]] = rig
        api_lines.append(json.dumps(rig.api_summary(), indent=2))

    compose_tpl = _load_prompt("lottie-scene-compose")
    fix_tpl = _load_prompt("lottie-scene-fix")
    char_api_text = "\n\n".join(api_lines) if api_lines else "[]"

    results: List[Optional[Dict[str, Any]]] = []
    for idx, panel in enumerate(panel_descriptions):
        source = _ask(chatbot, 
            compose_tpl.format(
                PANEL_DESCRIPTIONS=panel,
                WIDTH=width,
                HEIGHT=height,
                DURATION=duration,
                FPS=fps,
                CHARACTER_API=char_api_text,
            )
        )
        if not source:
            logging.error(f"scene {idx} initial generation empty; skipping panel")
            results.append(
                {
                    "name": f"panel_{idx}",
                    "url": None,
                    "lottie_url": None,
                    "source_url": None,
                    "lottie_error": {
                        "gate": "ask",
                        "errors": ["LLM unavailable - scene generation returned no content"],
                    },
                }
            )
            continue
        entry = None
        last_gate = "compose"
        last_errors: List[str] = []
        for it in range(max_iters):
            try:
                scene = exec_scene_source(source, rigs)
                doc = gate_scene_g0(scene)
            except (AuthorExecError, LottieValidationError) as e:
                last_errors = [str(e)]
                last_gate = "G0-static"
                source = _ask(chatbot, 
                    fix_tpl.format(
                        PANEL_DESCRIPTIONS=panel,
                        CHARACTER_API=char_api_text,
                        SOURCE=source,
                        GATE="G0-static",
                        ERRORS=_errors_block(last_errors),
                        SCREENSHOTS_NOTE="",
                    )
                )
                continue

            try:
                with LottieBrowserManager() as bm:
                    frames = render_keyframes(doc, n=3, browser=bm)
                    blanks = [f for f, png in frames if not _frame_ok(png)]
                    sheet = render_contact_sheet(
                        doc, frames=[f for f, _ in frames], browser=bm
                    )
                    sheet_png = _sheet_bytes(sheet)
            except Exception as e:
                last_errors = [f"render failed: {e}"]
                last_gate = "G1"
                source = _ask(chatbot, 
                    fix_tpl.format(
                        PANEL_DESCRIPTIONS=panel,
                        CHARACTER_API=char_api_text,
                        SOURCE=source,
                        GATE="G1-render",
                        ERRORS=_errors_block(last_errors),
                        SCREENSHOTS_NOTE="",
                    )
                )
                continue

            if blanks:
                last_errors = [
                f"blank frames: {blanks} - NOTHING is visible on the canvas. "
                "Every part is likely outside the canvas or fully transparent: "
                "check root part position=(x,y) values are inside the canvas "
                "and fill alpha > 0."
            ]
                last_gate = "G1"
                source = _ask(chatbot, 
                    [
                        Img(
                            _bytes=sheet_png,
                            text=fix_tpl.format(
                                PANEL_DESCRIPTIONS=panel,
                                CHARACTER_API=char_api_text,
                                SOURCE=source,
                                GATE="G1-render",
                                ERRORS=_errors_block(last_errors),
                                SCREENSHOTS_NOTE="Attached contact sheet; some frames blank.",
                            ),
                        )
                    ]
                )
                continue

            char_meta = json.dumps(
                [
                    {"name": c.get("name"), "url": c.get("url")}
                    for c in character_list
                    if c.get("lottie_url")
                ]
            )
            report = None
            if use_vision_judge:
                report = _vision_judge(chatbot, sheet_png, panel, char_meta)
                if report and not report.get("pass", False) and (
                    int(report.get("consistency_score", 0)) < PASS_SCORE
                    or any(
                        i.get("severity") == "critical" for i in report.get("issues", [])
                    )
                ):
                    last_gate = "G2-vision"
                    issues = report.get("issues", [])
                    directives = "\n".join(
                        f"- {i.get('fix_directive', i.get('issue', ''))}" for i in issues
                    )
                    source = _ask(chatbot, 
                        [
                            Img(
                                _bytes=sheet_png,
                                text=fix_tpl.format(
                                    PANEL_DESCRIPTIONS=panel,
                                    CHARACTER_API=char_api_text,
                                    SOURCE=source,
                                    GATE="G2-vision",
                                    ERRORS=_errors_block([f"score={report.get('consistency_score')}", directives]),
                                    SCREENSHOTS_NOTE="Attached contact sheet.",
                                ),
                            )
                        ]
                    )
                    continue

            urls = _upload_triple(outdir, f"scene_{idx}", source, doc, sheet_png)
            entry = {
                "panel_index": idx,
                "url": urls["preview_url"],
                "lottie_url": urls["lottie_url"],
                "lottie_source_url": urls["source_url"],
                "image_engine": "lottie",
            }
            if report:
                entry["lottie_score"] = report.get("consistency_score")
            break

        if entry is None:
            logging.error(f"scene {idx} failed all gates: {last_gate} {last_errors}")
            # Archive the last attempted source for offline diagnosis.
            try:
                object_storage.upload_data(
                    object_storage.ASSETS_VIDEO_CONFIG,
                    source,
                    f"{outdir}/scene_{idx}/authored_failed.py",
                    object_storage.ACL_PUBLIC,
                )
            except Exception as e:
                logging.warning(f"could not archive failed scene source {idx}: {e}")
            # Try to build a clean fallback scene using available rigs or example scene
            try:
                from .lottie_sdk import build_example_scene, CharacterInstance
                fb_scene = build_example_scene()
                if rigs:
                    # Place the first available character
                    first_name, first_rig = next(iter(rigs.items()))
                    inst = CharacterInstance(rig=first_rig).place(width // 2, int(height * 0.65), scale=180.0)
                    clip_name = first_rig.clips[0].name if first_rig.clips else None
                    if clip_name:
                        inst.play(clip_name)
                    fb_scene.characters = [inst]
                fb_source = "# fallback scene\n"
                doc = gate_scene_g0(fb_scene)
                with LottieBrowserManager() as bm:
                    frames = render_keyframes(doc, n=3, browser=bm)
                    sheet = render_contact_sheet(
                        doc, frames=[f for f, _ in frames], browser=bm
                    )
                    sheet_png = _sheet_bytes(sheet)
                urls = _upload_triple(outdir, f"scene_{idx}", fb_source, doc, sheet_png)
                entry = {
                    "panel_index": idx,
                    "url": urls["preview_url"],
                    "lottie_url": urls["lottie_url"],
                    "lottie_source_url": urls["source_url"],
                    "image_engine": "lottie",
                    "lottie_fallback": True,
                    "lottie_error": {"gate": last_gate, "errors": last_errors},
                }
                logging.warning(f"scene {idx} fallback used: {urls}")
            except Exception as fb_err:
                logging.error(f"scene {idx} fallback failed: {fb_err}")
                entry = {
                    "panel_index": idx,
                    "url": None,
                    "lottie_url": None,
                    "lottie_source_url": None,
                    "image_engine": "lottie",
                    "lottie_error": {"gate": last_gate, "errors": last_errors},
                }
        results.append(entry)

    return results


def create_lottie_timeline(
    scene_entries: List[dict],
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
    scene_duration: int = 90,
    audio_url: Optional[str] = None,
    outdir: str = "lottie/tmp",
) -> Optional[Dict[str, str]]:
    """Sequence accepted scene Lotties into one timeline + player page."""
    scenes: List[Tuple[int, Scene]] = []
    at = 0
    for e in scene_entries:
        if not e or not e.get("lottie_url"):
            continue
        try:
            doc = _fetch_json(e["lottie_url"])
        except Exception as ex:
            logging.error(f"timeline skip scene: {ex}")
            continue
        scene = Scene(
            width=int(doc.get("w", width)),
            height=int(doc.get("h", height)),
            fps=int(doc.get("fr", fps)),
            duration=int(doc.get("op", scene_duration)),
        )
        scenes.append((at, scene))
        at += scene.duration

    if not scenes:
        return None

    # Timeline compile needs real scene comps; rebuild from fetched docs via assets.
    # For the player path we emit a lightweight timeline JSON referencing scene URLs.
    timeline_doc = {
        "v": "5.7.4",
        "fr": fps,
        "ip": 0,
        "op": at,
        "w": width,
        "h": height,
        "nm": "baasha_timeline",
        "ddd": 0,
        "assets": [],
        "layers": [],
        "meta": {
            "audio_url": audio_url,
            "scenes": [
                {"start": s_at, "url": e["lottie_url"], "preview": e.get("url")}
                for (s_at, _), e in zip(
                    scenes, [x for x in scene_entries if x and x.get("lottie_url")]
                )
            ],
        },
    }
    for i, (s_at, sc) in enumerate(scenes):
        timeline_doc["layers"].append(
            {
                "ddd": 0,
                "ind": i + 1,
                "ty": 0,
                "nm": f"scene_{i}",
                "sr": 1,
                "refId": f"scene_{i}",
                "w": sc.width,
                "h": sc.height,
                "ks": {
                    "o": {"a": 0, "k": 100},
                    "r": {"a": 0, "k": 0},
                    "p": {"a": 0, "k": [width / 2, height / 2, 0]},
                    "a": {"a": 0, "k": [sc.width / 2, sc.height / 2, 0]},
                    "s": {
                        "a": 0,
                        "k": [
                            100
                            * min(width / sc.width, height / sc.height),
                            100
                            * min(width / sc.width, height / sc.height),
                            100,
                        ],
                    },
                },
                "ao": 0,
                "ip": s_at,
                "op": s_at + sc.duration,
                "st": 0,
                "bm": 0,
            }
        )
        timeline_doc["assets"].append(
            {
                "id": f"scene_{i}",
                "layers": _minimal_placeholder_layers(sc),
                "w": sc.width,
                "h": sc.height,
            }
        )

    timeline_url = object_storage.upload_data(
        object_storage.ASSETS_VIDEO_CONFIG,
        json.dumps(timeline_doc),
        f"{outdir}/timeline/animation_{uuid4().hex[:8]}.json",
        object_storage.ACL_PUBLIC,
    )

    scene_urls = [e["lottie_url"] for e in scene_entries if e and e.get("lottie_url")]
    player_html = _render_player_html(scene_urls, audio_url, width, height)
    player_url = object_storage.upload_data(
        object_storage.ASSETS_VIDEO_CONFIG,
        player_html,
        f"{outdir}/timeline/player_{uuid4().hex[:8]}.html",
        object_storage.ACL_PUBLIC,
    )

    return {
        "timeline_url": timeline_url,
        "player_url": player_url,
        "scene_urls": json.dumps(scene_urls),
    }


def _minimal_placeholder_layers(scene: Scene) -> list:
    return [
        {
            "ddd": 0,
            "ind": 1,
            "ty": 4,
            "nm": "placeholder",
            "sr": 1,
            "ks": {
                "o": {"a": 0, "k": 100},
                "r": {"a": 0, "k": 0},
                "p": {"a": 0, "k": [scene.width / 2, scene.height / 2, 0]},
                "a": {"a": 0, "k": [0, 0, 0]},
                "s": {"a": 0, "k": [100, 100, 100]},
            },
            "ao": 0,
            "shapes": [
                {
                    "ty": "gr",
                    "it": [
                        {
                            "ty": "rc",
                            "p": {"a": 0, "k": [0, 0]},
                            "s": {"a": 0, "k": [scene.width, scene.height]},
                            "r": {"a": 0, "k": 0},
                        },
                        {
                            "ty": "fl",
                            "c": {"a": 0, "k": [0.9, 0.9, 0.9, 1]},
                            "o": {"a": 0, "k": 100},
                        },
                        {
                            "ty": "tr",
                            "p": {"a": 0, "k": [0, 0]},
                            "a": {"a": 0, "k": [0, 0]},
                            "s": {"a": 0, "k": [100, 100]},
                            "r": {"a": 0, "k": 0},
                            "o": {"a": 0, "k": 100},
                        },
                    ],
                }
            ],
            "ip": 0,
            "op": scene.duration,
            "st": 0,
            "bm": 0,
        }
    ]


def _render_player_html(
    scene_urls: List[str], audio_url: Optional[str], width: int, height: int
) -> str:
    import html as html_mod

    urls_js = json.dumps(scene_urls)
    audio_attr = html_mod.escape(audio_url or "", quote=True)
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Baasha Lottie Timeline</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/lottie-web/5.13.0/lottie.min.js"></script>
<style>
  body{{margin:0;background:#111;color:#eee;font-family:system-ui,sans-serif;display:flex;flex-direction:column;align-items:center;min-height:100vh}}
  #player{{width:{min(width, 405)}px;height:{min(height, 720)}px;background:#000;margin:16px}}
  .bar{{display:flex;gap:8px;align-items:center;margin:8px}}
  button{{padding:8px 16px;font-size:14px}}
</style></head>
<body>
<div id="player"></div>
<div class="bar">
  <button id="play">Play</button>
  <button id="pause">Pause</button>
  <input id="scrub" type="range" min="0" max="100" value="0" style="width:240px">
  <span id="label">scene 1</span>
</div>
<audio id="bg" src="{audio_attr}" preload="auto"></audio>
<script>
const sceneUrls = {urls_js};
let idx = 0, anim = null;
async function loadScene(i) {{
  idx = i;
  const res = await fetch(sceneUrls[i]);
  const data = await res.json();
  if (anim) anim.destroy();
  anim = lottie.loadAnimation({{
    container: document.getElementById('player'),
    renderer: 'svg', loop: false, autoplay: false, animationData: data
  }});
  document.getElementById('label').textContent = 'scene ' + (i+1) + '/' + sceneUrls.length;
  anim.addEventListener('complete', () => {{
    if (idx + 1 < sceneUrls.length) loadScene(idx + 1);
  }});
  window.__anim = anim;
}}
document.getElementById('play').onclick = () => {{
  if (anim) anim.play();
  const a = document.getElementById('bg');
  if (a.src) a.play();
}};
document.getElementById('pause').onclick = () => {{
  if (anim) anim.pause();
  const a = document.getElementById('bg');
  if (a.src) a.pause();
}};
loadScene(0);
</script>
</body></html>"""
