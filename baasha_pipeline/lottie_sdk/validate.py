"""G0 structural validation for Lottie SDK models and compiled JSON."""

from __future__ import annotations

from typing import Any, Dict, List, Set

from .model import CharacterRig, Scene, Timeline


class LottieValidationError(Exception):
    def __init__(self, errors: List[str]):
        self.errors = errors
        super().__init__("; ".join(errors) if errors else "invalid lottie")


def validate_rig(rig: CharacterRig) -> None:
    """Model-level checks beyond pydantic (part count / clip budget)."""
    errors: List[str] = []
    if not rig.parts:
        errors.append("rig has no parts")
    if len(rig.parts) > 16:
        errors.append(f"rig has {len(rig.parts)} parts (max 16)")
    for clip in rig.clips:
        if clip.duration > 600:
            errors.append(f"clip {clip.name!r} longer than 600 frames")
    # Root parts (no parent) live in comp space - catch fully off-canvas rigs
    # early (a rig placed outside the canvas renders blank frames).
    tol_x = 0.05 * rig.width
    tol_y = 0.05 * rig.height
    for p in rig.parts:
        if p.parent:
            continue
        x, y = p.position
        if not (-tol_x <= x <= rig.width + tol_x and -tol_y <= y <= rig.height + tol_y):
            errors.append(
                f"part {p.name!r} is outside the canvas at position "
                f"({x:.0f}, {y:.0f}) - canvas is {rig.width}x{rig.height}; "
                "root parts must sit inside the canvas (comp space)"
            )
    if errors:
        raise LottieValidationError(errors)


def validate_scene(scene: Scene) -> None:
    errors: List[str] = []
    if scene.duration <= 0:
        errors.append("scene duration must be > 0")
    if not scene.characters and not scene.props:
        errors.append("scene is empty (no characters or props)")
    for inst in scene.characters:
        try:
            validate_rig(inst.rig)
        except LottieValidationError as e:
            errors.extend(f"character {inst.rig.name}: {err}" for err in e.errors)

    w, h = float(scene.width), float(scene.height)

    # Layered background: a base sky/wall color is mandatory; a lone flat
    # color with nothing on top of it reads as placeholder art.
    if scene.background is None:
        errors.append(
            "background is missing - set background=(r,g,b,a) on the Scene to a "
            "sky/wall base color (part of a layered background, never left out)"
        )

    # Set dressing: ground plane + at least one story prop.
    if len(scene.props) < 2:
        errors.append(
            f"set dressing: only {len(scene.props)} prop(s) placed - need at least 2 "
            "via scene.add_prop(...): (a) a full-width ground/floor rect covering the "
            "bottom ~20% of the canvas (width >= ~0.6 * canvas width, e.g. "
            "width=1080, height=420, positioned so it spans the bottom edge) and "
            "(b) at least one story prop from the panel description (shed, soil hole, "
            "flower, packet, tool...). A flat single-color background is not a scene."
        )

    # Motion: at least one character must actually play a clip.
    if scene.characters and not any(inst.clip for inst in scene.characters):
        playable = [
            f"{inst.rig.name}: {[c.name for c in inst.rig.clips]}"
            for inst in scene.characters
            if inst.rig.clips
        ]
        if playable:
            errors.append(
                "no motion - the scene is static. Call inst.play(\"<clip>\") on at "
                "least one character instance before scene.place_character(inst). "
                f"Available clips: {'; '.join(playable)}"
            )

    # Placement / scale: characters must read at 35-75% of frame height and be
    # fully in frame (center-based placement, anchor = rig center).
    for inst in scene.characters:
        rig = inst.rig
        name = rig.name
        scale = abs(float(inst.scale)) or 100.0
        eff_h = rig.height * scale / 100.0
        eff_w = rig.width * scale / 100.0
        frac = eff_h / h if h else 0.0
        if frac < 0.35:
            target = int(round(0.5 * h / max(rig.height, 1) * 100))
            errors.append(
                f"character {name} too small: occupies {frac:.0%} of frame height "
                f"(needs 35-75%) - place at scale ~{target} (currently {inst.scale:.0f})"
            )
        elif frac > 1.15:
            target = int(round(0.6 * h / max(rig.height, 1) * 100))
            errors.append(
                f"character {name} too large: occupies {frac:.0%} of frame height "
                f"(needs 35-75%) - place at scale ~{target} (currently {inst.scale:.0f})"
            )
        left, right = inst.x - eff_w / 2.0, inst.x + eff_w / 2.0
        top, bottom = inst.y - eff_h / 2.0, inst.y + eff_h / 2.0
        if right < -0.03 * w or left > 1.03 * w:
            errors.append(
                f"character {name} is off-canvas horizontally (x={inst.x:.0f}; canvas "
                f"width {w:.0f}) - place it inside the frame"
            )
        elif left < -0.03 * w or right > 1.03 * w:
            errors.append(
                f"character {name} is cropped horizontally (spans {left:.0f}..{right:.0f} "
                f"of {w:.0f}) - recentre or reduce scale"
            )
        if top < -0.04 * h or bottom > 1.06 * h:
            errors.append(
                f"character {name} is cropped vertically (spans {top:.0f}..{bottom:.0f} "
                f"of {h:.0f}) - keep the whole body inside the canvas"
            )
        if bottom < 0.45 * h:
            errors.append(
                f"character {name} floats in the upper frame (feet at {bottom / h:.0%} "
                "of height) - ground it: move y down so the feet land in the lower half"
            )

    if errors:
        raise LottieValidationError(errors)


def validate_timeline(timeline: Timeline) -> None:
    errors: List[str] = []
    if not timeline.scenes:
        errors.append("timeline has no scenes")
    for at, scene in timeline.scenes:
        if at < 0:
            errors.append(f"scene start {at} is negative")
        try:
            validate_scene(scene)
        except LottieValidationError as e:
            errors.extend(f"scene@{at}: {err}" for err in e.errors)
    if errors:
        raise LottieValidationError(errors)


def _check_transform(prop: Any, path: str, errors: List[str]) -> None:
    if not isinstance(prop, dict) or "a" not in prop or "k" not in prop:
        errors.append(f"{path}: transform missing a/k")
        return
    if prop["a"] not in (0, 1):
        errors.append(f"{path}: animated flag must be 0 or 1")
    if prop["a"] == 1:
        if not isinstance(prop["k"], list) or not prop["k"]:
            errors.append(f"{path}: animated property needs keyframe list")
        else:
            prev_t = -1
            for i, kf in enumerate(prop["k"]):
                if not isinstance(kf, dict) or "t" not in kf or "s" not in kf:
                    errors.append(f"{path}: keyframe {i} missing t/s")
                    continue
                if kf["t"] < prev_t:
                    errors.append(f"{path}: keyframes not sorted at {i}")
                prev_t = kf["t"]


def _check_shapes(shapes: Any, path: str, errors: List[str]) -> None:
    if not isinstance(shapes, list) or not shapes:
        errors.append(f"{path}: shapes missing/empty")
        return
    for gi, g in enumerate(shapes):
        if not isinstance(g, dict) or g.get("ty") != "gr":
            errors.append(f"{path}: shapes[{gi}] is not a group")
            continue
        items = g.get("it")
        if not isinstance(items, list) or not items:
            errors.append(f"{path}: group {gi} has no items")
            continue
        kinds = [it.get("ty") for it in items if isinstance(it, dict)]
        if not any(k in ("el", "rc") for k in kinds):
            errors.append(f"{path}: group {gi} has no drawable shape")
        if "fl" not in kinds and "st" not in kinds:
            errors.append(f"{path}: group {gi} has no fill/stroke")


def validate_lottie(doc: Dict[str, Any]) -> List[str]:
    """Structural G0 checks on compiled Lottie JSON. Returns error list."""
    errors: List[str] = []
    if not isinstance(doc, dict):
        return ["document is not a dict"]

    for key in ("v", "fr", "ip", "op", "w", "h", "layers"):
        if key not in doc:
            errors.append(f"missing top-level key {key!r}")
    if errors:
        return errors

    if not isinstance(doc["layers"], list) or not doc["layers"]:
        errors.append("layers missing/empty")
        return errors

    fr = doc["fr"]
    if not isinstance(fr, (int, float)) or fr <= 0:
        errors.append("fr must be > 0")
    if doc["op"] <= doc["ip"]:
        errors.append("op must be > ip")
    if doc["w"] <= 0 or doc["h"] <= 0:
        errors.append("width/height must be positive")

    inds: Set[int] = set()
    ref_ids: Set[str] = {a.get("id") for a in doc.get("assets", []) if isinstance(a, dict)}

    for li, layer in enumerate(doc["layers"]):
        path = f"layers[{li}]"
        if not isinstance(layer, dict):
            errors.append(f"{path}: not a dict")
            continue
        ty = layer.get("ty")
        if ty not in (0, 1, 2, 3, 4):
            errors.append(f"{path}: unknown layer type {ty!r}")
        ind = layer.get("ind")
        if not isinstance(ind, int):
            errors.append(f"{path}: missing int ind")
        elif ind in inds:
            errors.append(f"{path}: duplicate ind {ind}")
        else:
            inds.add(ind)
        for k in ("ip", "op"):
            if k not in layer:
                errors.append(f"{path}: missing {k}")
        ks = layer.get("ks")
        if not isinstance(ks, dict):
            errors.append(f"{path}: missing ks")
        else:
            for ch in ("o", "r", "p", "a", "s"):
                if ch not in ks:
                    errors.append(f"{path}.ks: missing {ch}")
                else:
                    _check_transform(ks[ch], f"{path}.ks.{ch}", errors)
        if ty == 4:
            _check_shapes(layer.get("shapes"), path, errors)
        if ty == 0:
            ref = layer.get("refId")
            if not ref:
                errors.append(f"{path}: precomp missing refId")
            elif ref not in ref_ids:
                errors.append(f"{path}: refId {ref!r} not in assets")

    for layer in doc["layers"]:
        if isinstance(layer, dict) and "parent" in layer:
            if layer["parent"] not in inds:
                errors.append(f"layer {layer.get('nm')!r}: parent ind {layer['parent']} not found")

    for ai, asset in enumerate(doc.get("assets", [])):
        if not isinstance(asset, dict) or "id" not in asset:
            errors.append(f"assets[{ai}]: missing id")
            continue
        if "layers" in asset:
            sub = {
                "v": doc["v"],
                "fr": doc["fr"],
                "ip": 0,
                "op": doc["op"],
                "w": asset.get("w", doc["w"]),
                "h": asset.get("h", doc["h"]),
                "layers": asset["layers"],
                "assets": asset.get("assets", []),
            }
            sub_errors = validate_lottie(sub)
            errors.extend(f"asset {asset['id']!r}: {e}" for e in sub_errors)

    return errors


def assert_valid_lottie(doc: Dict[str, Any]) -> None:
    errors = validate_lottie(doc)
    if errors:
        raise LottieValidationError(errors)
