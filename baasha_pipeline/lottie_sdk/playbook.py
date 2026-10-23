"""Quick-reference fix skill for LLM repair loops (G0/G1/G2).

Every entry matches gate/validator error text we have actually observed and
returns a terse, deterministic remedy. Purely additive prompt guidance: the
gates stay the sole arbiter - a wrong remedy can only cost an iteration, and
an unmatched error simply adds nothing (prompt stays byte-identical).

Usage:  block = match_playbook(last_errors)
        ERRORS = base + ("\n" + block if block else "")
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class PlaybookEntry:
    id: str
    pattern: str
    fix: str


_MINIMAL_EDIT = (
    "MINIMAL EDIT RULE: change ONLY the values named above. Keep background, "
    "props, clip calls, part names, hierarchy and overall structure exactly "
    "as they are - do not redraw or redesign the scene. This rule describes "
    "WHAT to change, never how much to send: your reply must still be the "
    "COMPLETE file from the first line to the closing bracket, in ONE "
    "```python block - never a snippet, fragment, excerpt or diff."
)

FIX_PLAYBOOK: List[PlaybookEntry] = [
    PlaybookEntry(
        id="scale_too_small",
        pattern=r"too small: occupies",
        fix=(
            "SCALE: raise inst.scale into the 35-75% frame-height band - "
            "compute scale = round(0.5 * H / rig_height * 100) (e.g. H=1920, "
            "rig 512 -> 188) and set only that number. Do not move props."
        ),
    ),
    PlaybookEntry(
        id="scale_too_large",
        pattern=r"too large: occupies",
        fix=(
            "SCALE: lower inst.scale into the 35-75% band - "
            "scale = round(0.6 * H / rig_height * 100), set only that number."
        ),
    ),
    PlaybookEntry(
        id="crop_h",
        pattern=r"cropped horizontally|off-canvas horizontally",
        fix=(
            "FIT WIDTH: eff_w = rig_width * scale / 100 must be <= 0.92 * W. "
            "Reduce inst.scale by factor 0.92*W/eff_w (round), then set "
            "inst.x = clamp so the bbox fits: x in "
            "[eff_w/2 + 0.03*W, W - eff_w/2 - 0.03*W]."
        ),
    ),
    PlaybookEntry(
        id="crop_v",
        pattern=r"cropped vertically",
        fix=(
            "FIT HEIGHT: eff_h = rig_height * scale / 100 must be <= 0.96 * H. "
            "Reduce inst.scale by factor 0.96*H/eff_h, then set inst.y so the "
            "bbox fits: y in [eff_h/2, H - eff_h/2] (keep feet >= 0.45*H)."
        ),
    ),
    PlaybookEntry(
        id="floats_upper",
        pattern=r"floats in the upper frame",
        fix=(
            "GROUNDING: move inst.y down so feet (y + eff_h/2) land in "
            "[0.45*H, 0.98*H]; e.g. y = H - eff_h/2 - 0.05*H. Change y only."
        ),
    ),
    PlaybookEntry(
        id="missing_bg",
        pattern=r"background is missing",
        fix=(
            "BACKGROUND: set Scene(..., background=(r, g, b, 1.0)) - a sky/wall "
            "base tuple of floats 0..1 (NOT a hex string), e.g. "
            "(0.55, 0.80, 0.95, 1.0)."
        ),
    ),
    PlaybookEntry(
        id="set_dressing",
        pattern=r"set dressing: only \d+ prop",
        fix=(
            "PROPS: add via scene.add_prop - (1) a full-width ground rect: "
            "width=1080, height~420, x=W/2 (prop anchor is its CENTER, so "
            "x must be W/2 to span the frame), y near the bottom edge; "
            "(2) >=1 story prop from the panel (shed, packet, tool, flower). "
            "At least 2 props total."
        ),
    ),
    PlaybookEntry(
        id="no_motion",
        pattern=r"no motion - the scene is static",
        fix=(
            "MOTION: call inst.play(\"<clip>\") on at least one instance "
            "before scene.place_character(inst) - use a clip listed in the "
            "error; keep the existing placement values."
        ),
    ),
    PlaybookEntry(
        id="empty_scene",
        pattern=r"scene is empty \(no characters or props\)",
        fix=(
            "CONTENT: place at least one character (place_character) and the "
            "ground prop; keep everything else from the current source."
        ),
    ),
    PlaybookEntry(
        id="bad_duration",
        pattern=r"scene duration must be > 0",
        fix="DURATION: Scene(..., duration=90) at fps=30 (3 seconds).",
    ),
    PlaybookEntry(
        id="part_offcanvas",
        pattern=r"part '[^']*' is outside the canvas at position",
        fix=(
            "PART POSITION: the named root part's position=(x, y) must lie "
            "inside the rig canvas (e.g. 0..512 on both axes). Move only that "
            "part back inside; children follow their parent."
        ),
    ),
    PlaybookEntry(
        id="too_many_parts",
        pattern=r"rig has \d+ parts \(max 16\)|rig has no parts",
        fix=(
            "PART BUDGET: 1-16 Part objects; merge tiny details into existing "
            "parts (e.g. eyes into the head group) instead of adding layers."
        ),
    ),
    PlaybookEntry(
        id="blank_frames",
        pattern=r"blank frames:|is blank/near-blank",
        fix=(
            "BLANK CHECKLIST: (1) every root part position inside the rig "
            "canvas; (2) every fill has alpha > 0 (4-tuple ending in 1.0, not "
            "0.0); (3) shapes non-empty with a drawable rect/ellipse; "
            "(4) instance x,y on the scene canvas. Fix only these values."
        ),
    ),
    PlaybookEntry(
        id="rig_crop",
        pattern=r"cut off at the (?:\w+ )?edge|ink starts at|ink reaches",
        fix=(
            "RIG MARGIN: apply the measured pixel shift from the error to "
            "every top-level part's position (parts are placed relative to "
            "the root 'torso', shifting torso moves the whole rig), OR scale "
            "all part sizes and positions by a common factor. Keep proportions."
        ),
    ),
    PlaybookEntry(
        id="shape_kind",
        pattern=r"ShapeKind\.|AttributeError: [A-Z_]+$",
        fix=(
            "ShapeKind has ONLY two members: ShapeKind.ELLIPSE and "
            "ShapeKind.RECT. POLYGON/PATH/POS do not exist - replace any "
            "polygon or path shape with a single RECT (best-effort bounding "
            "box) or a small group of rects."
        ),
    ),
    PlaybookEntry(
        id="render_failed",
        pattern=r"render failed:",
        fix=(
            "RENDER: output a complete, syntactically valid source file - "
            "balanced brackets/quotes, no truncation, all names defined "
            "before use. Keep the previous structure."
        ),
    ),
    PlaybookEntry(
        id="exec_error",
        pattern=(
            r"SyntaxError|NameError|AttributeError|TypeError|KeyError|"
            r"is not defined|invalid syntax|was never closed|"
            r"indentation error|unexpected EOF"
        ),
        fix=(
            "EXEC ERROR: your last reply was truncated or malformed - emit the "
            "FULL corrected file, closing every bracket and quote, fixing "
            "indentation, defining every name you use (Shape, Part, Prop, "
            "Scene, CharacterInstance, CHARACTERS). NEVER reply with only the "
            "changed lines or a partial file; do not change the design."
        ),
    ),
    PlaybookEntry(
        id="structural",
        pattern=(
            r"missing top-level key|duplicate ind|parent ind .* not found|"
            r"keyframes not sorted|needs keyframe list|keyframe \d+ missing|"
            r"shapes missing/empty|no drawable shape|no fill/stroke|"
            r"refId .* not in assets|missing int ind|unknown layer type|"
            r"missing ks|missing ip|missing op|fr must be|op must be|"
            r"width/height must be|transform missing|animated flag|"
            r"missing id|precomp missing refId|longer than 600 frames|"
            r"clip .* unknown pose"
        ),
        fix=(
            "STRUCTURAL: fix exactly the field named in the error (ind/parent/"
            "ip/op/ks/shapes/keyframe order) and leave every other value "
            "untouched; re-check parent ind references after renumbering."
        ),
    ),
    PlaybookEntry(
        id="vision_directives",
        pattern=r"^score=",
        fix=(
            "VISION FEEDBACK: treat each directive above as a specific edit "
            "request - apply only those edits, one per named element, keeping "
            "everything else byte-identical."
        ),
    ),
]


def match_playbook(errors: List[str]) -> str:
    """Return a 'KNOWN ISSUE -> FIX' quick-guide block for matching errors."""
    if not errors:
        return ""
    text = "\n".join(str(e) for e in errors)
    hits: List[PlaybookEntry] = []
    for entry in FIX_PLAYBOOK:
        try:
            if re.search(entry.pattern, text, re.IGNORECASE | re.MULTILINE):
                if entry not in hits:
                    hits.append(entry)
        except re.error:
            continue
    if not hits:
        return ""
    lines = ["", "KNOWN ISSUES - APPLY THIS QUICK GUIDE:"]
    seen = set()
    for e in hits:
        if e.id in seen:
            continue
        seen.add(e.id)
        lines.append(f"- [{e.id}] {e.fix}")
    lines.append(_MINIMAL_EDIT)
    return "\n".join(lines)
