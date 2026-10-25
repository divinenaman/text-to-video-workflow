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
    "MINIMAL EDIT RULE: fix the specific reported issue while preserving "
    "unrelated design choices. This rule describes WHAT to change, never how "
    "much to send: your reply must still be the "
    "COMPLETE file from the first line to the closing bracket, in ONE "
    "```python block - never a snippet, fragment, excerpt or diff."
)

FIX_PLAYBOOK: List[PlaybookEntry] = [
    PlaybookEntry(
        id="empty_scene",
        pattern=r"scene is empty \(no characters or props\)",
        fix=(
            "CONTENT: add the scene element(s) required by the panel using "
            "place_character and/or add_prop. Preserve its intended art direction."
        ),
    ),
    PlaybookEntry(
        id="bad_duration",
        pattern=r"scene duration must be > 0",
        fix="DURATION: Scene(..., duration=90) at fps=30 (3 seconds).",
    ),
    PlaybookEntry(
        id="bad_scene_dimensions",
        pattern=r"scene width and height must be > 0",
        fix="DIMENSIONS: set positive width and height matching the requested canvas.",
    ),
    PlaybookEntry(
        id="bad_scene_fps",
        pattern=r"scene fps must be > 0",
        fix="FRAME RATE: set a positive fps value on the Scene.",
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
            "0.0); (3) shapes non-empty with valid drawable geometry, including "
            "matching path vertices and tangent arrays; "
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
            "Use only supported members ShapeKind.ELLIPSE, ShapeKind.RECT, "
            "and ShapeKind.PATH. Check the reported member name and replace "
            "unsupported geometry with the closest supported shape."
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
        id="character_api",
        pattern=(
            r"CharacterInstance.*(?:animate|play_clip)|"
            r"set_pose\(\).*unexpected keyword|unknown clip:"
        ),
        fix=(
            "CHARACTER API: the only animation methods are "
            "`instance.set_pose(pose_name)` and `instance.play(clip_name)`. "
            "Use the exact pose or clip names listed for that character in "
            "CHARACTER_API; never use `animate`, `play_clip`, or keyword "
            "`name=`. If the desired action has no listed clip, use the closest "
            "listed pose or leave the character static."
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
