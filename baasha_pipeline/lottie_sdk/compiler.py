"""Compile Lottie SDK models to Lottie JSON.

Deterministic: same models in → same JSON out. LLMs never touch this module.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from .model import (
    CharacterInstance,
    CharacterRig,
    Clip,
    Part,
    PlacedProp,
    Pose,
    Prop,
    RGBA,
    Scene,
    Shape,
    ShapeKind,
    Timeline,
)

LOTTIE_VERSION = "5.7.4"
DEFAULT_EASE_IN = {"x": [0.333], "y": [0.0]}
DEFAULT_EASE_OUT = {"x": [0.667], "y": [1.0]}

Number = Union[int, float]
Vec = List[float]


def _static(value: Union[Number, Vec]) -> Dict[str, Any]:
    return {"a": 0, "k": value}


def _animated(
    keyframes: List[Tuple[int, Vec]],
    ease_in: Optional[Dict[str, Any]] = None,
    ease_out: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if not keyframes:
        raise ValueError("animated property needs at least one keyframe")
    if len(keyframes) == 1:
        # A single {t, s} keyframe has no next keyframe to interpolate toward
        # and no end value; lottie-web throws on it and the whole canvas
        # renders blank (this blanked entire scenes when a pose set a
        # property the clip never animated). One keyframe == static value.
        return _static(list(keyframes[0][1]))
    if all(v == keyframes[0][1] for _, v in keyframes[1:]):
        return _static(list(keyframes[0][1]))
    ei = ease_in or DEFAULT_EASE_IN
    eo = ease_out or DEFAULT_EASE_OUT
    out = []
    for i, (t, v) in enumerate(keyframes):
        kf: Dict[str, Any] = {"t": t, "s": v}
        if i < len(keyframes) - 1:
            kf["i"] = ei
            kf["o"] = eo
        out.append(kf)
    return {"a": 1, "k": out}


def _color(c: RGBA) -> Dict[str, Any]:
    return _static([float(c[0]), float(c[1]), float(c[2]), float(c[3])])


def _xy(v) -> List[float]:
    return [float(v[0]), float(v[1])]


def _xyz(v, z: float = 0.0) -> List[float]:
    return [float(v[0]), float(v[1]), float(z)]


def _compile_shape(shape: Shape) -> Dict[str, Any]:
    if shape.kind == ShapeKind.ELLIPSE:
        return {
            "ty": "el",
            "nm": "ellipse",
            "p": _static(_xy(shape.position)),
            "s": _static(_xy(shape.size)),
        }
    if shape.kind == ShapeKind.PATH:
        in_tangents = shape.in_tangents or [(0.0, 0.0)] * len(shape.vertices)
        out_tangents = shape.out_tangents or [(0.0, 0.0)] * len(shape.vertices)
        return {
            "ty": "sh",
            "nm": "path",
            "d": 1,
            "ks": {
                "a": 0,
                "k": {
                    "i": [_xy(point) for point in in_tangents],
                    "o": [_xy(point) for point in out_tangents],
                    "v": [
                        [
                            float(point[0]) + float(shape.position[0]),
                            float(point[1]) + float(shape.position[1]),
                        ]
                        for point in shape.vertices
                    ],
                    "c": shape.closed,
                },
            },
        }
    return {
        "ty": "rc",
        "nm": "rect",
        "p": _static(_xy(shape.position)),
        "s": _static(_xy(shape.size)),
        "r": _static(float(shape.corner_radius)),
    }


def _compile_part_group(part: Part) -> Dict[str, Any]:
    items: List[Dict[str, Any]] = [_compile_shape(s) for s in part.shapes]
    items.append(
        {
            "ty": "fl",
            "nm": "fill",
            "c": _color(part.fill),
            "o": _static(100.0),
            "r": 1,
        }
    )
    if part.stroke is not None and part.stroke_width > 0:
        items.append(
            {
                "ty": "st",
                "nm": "stroke",
                "c": _color(part.stroke),
                "o": _static(100.0),
                "w": _static(float(part.stroke_width)),
                "r": 1,
            }
        )
    items.append(
        {
            "ty": "tr",
            "p": _static([0.0, 0.0]),
            "a": _static([0.0, 0.0]),
            "s": _static([100.0, 100.0]),
            "r": _static(0.0),
            "o": _static(100.0),
        }
    )
    return {"ty": "gr", "nm": part.name, "it": items}


def _norm_scale_pct(s: Union[Number, Sequence[float]]) -> List[float]:
    """Normalize author scale values to Lottie percent (100 = unchanged).

    Authors mix conventions: some write percent (100.0 = identity), others
    write factors (1.0 = identity). Values <= 8 in both axes can only be a
    factor (an 8% scale would be an odd authoring choice), so lift them.
    """
    if isinstance(s, (int, float)):
        a = b = float(s)
    else:
        a, b = float(s[0]), float(s[1])
    if a <= 8.0 and b <= 8.0:
        a, b = a * 100.0, b * 100.0
    return [a, b]


def _resolve_part_transform(
    part: Part, pose: Optional[Pose]
) -> Tuple[List[float], float, List[float]]:
    """Return (position_xyz, rotation_deg, scale_xyz) for part under pose."""
    p = _xyz(part.position)
    r = float(part.rotation)
    s = _norm_scale_pct(part.scale) + [100.0]
    if pose is not None:
        j = pose.joints.get(part.name)
        if j:
            if "position" in j:
                pos = j["position"]
                p = [float(pos[0]), float(pos[1]), 0.0]
            if "rotation" in j:
                r = float(j["rotation"])
            if "scale" in j:
                sc = j["scale"]
                s = _norm_scale_pct(sc) + [100.0]
    return p, r, s


def _part_layer(
    part: Part,
    ind: int,
    pose: Optional[Pose],
    parent_ind: Optional[int],
    ip: int,
    op: int,
) -> Dict[str, Any]:
    p, r, s = _resolve_part_transform(part, pose)
    layer: Dict[str, Any] = {
        "ddd": 0,
        "ind": ind,
        "ty": 4,
        "nm": part.name,
        "sr": 1,
        "ks": {
            "o": _static(float(part.opacity)),
            "r": _static(r),
            "p": _static(p),
            "a": _static(_xyz(part.anchor)),
            "s": _static(s),
        },
        "ao": 0,
        "shapes": [_compile_part_group(part)],
        "ip": ip,
        "op": op,
        "st": 0,
        "bm": 0,
    }
    if parent_ind is not None:
        layer["parent"] = parent_ind
    return layer


def _animated_part_layer(
    part: Part,
    ind: int,
    clip: Clip,
    rig_poses: Dict[str, Pose],
    parent_ind: Optional[int],
    ip: int,
    op: int,
) -> Dict[str, Any]:
    """Part layer whose r/p/s are keyframed across the clip's poses."""
    times = [t for t, _ in clip.keyframes]
    pose_objs = [rig_poses[pn] for _, pn in clip.keyframes]

    def channel(channel: str, rest) -> Dict[str, Any]:
        keys: List[Tuple[int, Vec]] = []
        any_override = False
        for t, pose in zip(times, pose_objs):
            j = pose.joints.get(part.name)
            if j and channel in j:
                any_override = True
                val = j[channel]
                if channel == "rotation":
                    keys.append((t, [float(val)]))
                else:
                    keys.append(
                        (t, _norm_scale_pct(val) + [100.0] if channel == "scale"
                         else [float(val[0]), float(val[1])] + [0.0])
                    )
            else:
                if channel == "rotation":
                    keys.append((t, [float(rest[0])]))
                else:
                    keys.append((t, list(rest)))
        if not any_override:
            if channel == "rotation":
                return _static(float(rest[0]))
            return _static(list(rest))
        return _animated(keys)

    rest_p = _xyz(part.position)
    rest_r = [float(part.rotation)]
    rest_s = _norm_scale_pct(part.scale) + [100.0]

    layer: Dict[str, Any] = {
        "ddd": 0,
        "ind": ind,
        "ty": 4,
        "nm": part.name,
        "sr": 1,
        "ks": {
            "o": _static(float(part.opacity)),
            "r": channel("rotation", rest_r),
            "p": channel("position", rest_p),
            "a": _static(_xyz(part.anchor)),
            "s": channel("scale", rest_s),
        },
        "ao": 0,
        "shapes": [_compile_part_group(part)],
        "ip": ip,
        "op": op,
        "st": 0,
        "bm": 0,
    }
    if parent_ind is not None:
        layer["parent"] = parent_ind
    return layer


def _background_layer(width: int, height: int, color: RGBA, ip: int, op: int) -> Dict[str, Any]:
    return {
        "ddd": 0,
        "ind": 1,
        "ty": 4,
        "nm": "__background",
        "sr": 1,
        "ks": {
            "o": _static(100.0),
            "r": _static(0.0),
            "p": _static([width / 2.0, height / 2.0, 0.0]),
            "a": _static([0.0, 0.0, 0.0]),
            "s": _static([100.0, 100.0, 100.0]),
        },
        "ao": 0,
        "shapes": [
            {
                "ty": "gr",
                "nm": "bg",
                "it": [
                    _compile_shape(
                        Shape(kind=ShapeKind.RECT, size=(float(width), float(height)))
                    ),
                    {"ty": "fl", "nm": "fill", "c": _color(color), "o": _static(100.0), "r": 1},
                    {
                        "ty": "tr",
                        "p": _static([0.0, 0.0]),
                        "a": _static([0.0, 0.0]),
                        "s": _static([100.0, 100.0]),
                        "r": _static(0.0),
                        "o": _static(100.0),
                    },
                ],
            }
        ],
        "ip": ip,
        "op": op,
        "st": 0,
        "bm": 0,
    }


def _root_comp(
    name: str, w: int, h: int, fr: int, ip: int, op: int, layers: List[Dict[str, Any]]
) -> Dict[str, Any]:
    return {
        "v": LOTTIE_VERSION,
        "fr": fr,
        "ip": ip,
        "op": op,
        "w": w,
        "h": h,
        "nm": name,
        "ddd": 0,
        "assets": [],
        "layers": layers,
    }


def compile_rig(
    rig: CharacterRig,
    pose: Optional[str] = None,
    clip: Optional[str] = None,
    op: Optional[int] = None,
) -> Dict[str, Any]:
    """Compile a character rig to a standalone Lottie composition.

    ``pose`` applies a static named pose; ``clip`` keyframes the rig. If both
    are given, ``clip`` wins. ``op`` overrides the composition out-point
    (last pose is held to ``op`` when extending).
    """
    if pose is not None and clip is not None:
        clip_obj = rig.get_clip(clip)
    elif clip is not None:
        clip_obj = rig.get_clip(clip)
    elif pose is not None:
        rig.get_pose(pose)
        clip_obj = None
    else:
        clip_obj = None

    pose_obj = rig.get_pose(pose) if pose is not None and clip is None else None

    if clip_obj is not None:
        comp_op = op if op is not None else max(clip_obj.duration, 1)
        if comp_op < clip_obj.duration:
            comp_op = clip_obj.duration
    else:
        comp_op = op if op is not None else 1

    layers: List[Dict[str, Any]] = []
    if rig.background is not None:
        layers.append(_background_layer(rig.width, rig.height, rig.background, 0, comp_op))

    name_to_ind = {p.name: i + 2 for i, p in enumerate(rig.parts)}
    pose_map = {p.name: p for p in rig.poses}

    for i, part in enumerate(rig.parts):
        ind = name_to_ind[part.name]
        parent_ind = name_to_ind.get(part.parent) if part.parent else None
        if clip_obj is not None:
            layer = _animated_part_layer(
                part, ind, clip_obj, pose_map, parent_ind, 0, comp_op
            )
        else:
            layer = _part_layer(part, ind, pose_obj, parent_ind, 0, comp_op)
        layers.append(layer)

    # Lottie renders layers[0] topmost. Parts listed root-first should paint
# back-to-front, so reverse part order; background goes last (bottom).
    shape_layers = [l for l in layers if l.get("nm") != "__background"]
    bg_layers = [l for l in layers if l.get("nm") == "__background"]
    shape_layers.reverse()
    return _root_comp(rig.name, rig.width, rig.height, rig.fps, 0, comp_op, shape_layers + bg_layers)


def compile_instance(
    instance: CharacterInstance, target_op: Optional[int] = None
) -> Dict[str, Any]:
    """Compile a placed character instance (rest / pose / clip) to Lottie."""
    return compile_rig(
        instance.rig,
        pose=instance.pose,
        clip=instance.clip,
        op=target_op,
    )


def _placement_layer(
    name: str,
    ref_id: str,
    w: int,
    h: int,
    ind: int,
    x: float,
    y: float,
    scale: float,
    rotation: float,
    ip: int,
    op: int,
    st: int = 0,
) -> Dict[str, Any]:
    return {
        "ddd": 0,
        "ind": ind,
        "ty": 0,
        "nm": name,
        "sr": 1,
        "refId": ref_id,
        "w": w,
        "h": h,
        "ks": {
            "o": _static(100.0),
            "r": _static(float(rotation)),
            "p": _static([float(x), float(y), 0.0]),
            "a": _static([w / 2.0, h / 2.0, 0.0]),
            "s": _static([float(scale), float(scale), 100.0]),
        },
        "ao": 0,
        "ip": ip,
        "op": op,
        "st": st,
        "bm": 0,
    }


def _prop_layers(prop: Prop, placed: PlacedProp, base_ind: int, ip: int, op: int) -> List[Dict[str, Any]]:
    """Compile a prop as shape layers parented to a placement null."""
    null_ind = base_ind
    null = {
        "ddd": 0,
        "ind": null_ind,
        "ty": 3,
        "nm": f"prop:{prop.name}",
        "sr": 1,
        "ks": {
            "o": _static(100.0),
            "r": _static(float(placed.rotation)),
            "p": _static([float(placed.x), float(placed.y), 0.0]),
            "a": _static([0.0, 0.0, 0.0]),
            "s": _static([float(placed.scale), float(placed.scale), 100.0]),
        },
        "ao": 0,
        "ip": ip,
        "op": op,
        "st": 0,
        "bm": 0,
    }
    out = [null]
    for i, part in enumerate(prop.parts):
        ind = null_ind + 1 + i
        parent_ind = null_ind
        if part.parent:
            idx = {p.name: null_ind + 1 + j for j, p in enumerate(prop.parts)}
            parent_ind = idx.get(part.parent, null_ind)
        out.append(_part_layer(part, ind, None, parent_ind, ip, op))
    return out


def _flattened_instance_layers(
    instance: CharacterInstance,
    ip: int,
    op: int,
    x: float,
    y: float,
    scale: float,
    rotation: float,
) -> List[Dict[str, Any]]:
    """Bake a character instance into shape layers placed at (x,y,scale,rot).

    Avoids nested precomps (scene asset -> char asset), which lottie-web
    chokes on. Layer coordinates are rig-local, parented under a null that
    carries the placement transform.
    """
    inner = compile_instance(instance, target_op=max(op - ip, 1))
    # Map inner layer inds -> new inds (null=1, parts start at 2)
    inner_inds = [l["ind"] for l in inner.get("layers", []) if l.get("nm") != "__background"]
    old_to_new = {old: i + 2 for i, old in enumerate(inner_inds)}

    null = {
        "ddd": 0,
        "ind": 1,
        "ty": 3,
        "nm": f"char:{instance.rig.name}",
        "sr": 1,
        "ks": {
            "o": _static(100.0),
            "r": _static(float(rotation)),
            "p": _static([float(x), float(y), 0.0]),
            "a": _static([instance.rig.width / 2.0, instance.rig.height / 2.0, 0.0]),
            "s": _static([float(scale), float(scale), 100.0]),
        },
        "ao": 0,
        "ip": ip,
        "op": op,
        "st": 0,
        "bm": 0,
    }
    layers: List[Dict[str, Any]] = [null]
    for layer in inner.get("layers", []):
        if layer.get("nm") == "__background":
            continue
        cl = dict(layer)
        cl["ip"] = ip
        cl["op"] = op
        cl["ind"] = old_to_new[layer["ind"]]
        if layer.get("parent") is not None and layer["parent"] in old_to_new:
            cl["parent"] = old_to_new[layer["parent"]]
        else:
            # Root part with no parent -> attach to placement null
            cl["parent"] = 1
        layers.append(cl)
    return layers


def compile_scene(scene: Scene) -> Dict[str, Any]:
    """Compile a scene; characters are flattened into shape layers (no nested precomps)."""
    ip = 0
    op = max(scene.duration, 1)
    layers: List[Dict[str, Any]] = []
    next_ind = 2

    for inst in scene.characters:
        char_layers = _flattened_instance_layers(
            inst, ip, op, inst.x, inst.y, inst.scale, inst.rotation
        )
        # Renumber to unique global inds
        old_to_new = {}
        for cl in char_layers:
            old_to_new[cl["ind"]] = next_ind
            cl["ind"] = next_ind
            next_ind += 1
        for cl in char_layers:
            if cl.get("parent") is not None and cl["parent"] in old_to_new:
                cl["parent"] = old_to_new[cl["parent"]]
        layers.extend(char_layers)

    for placed in scene.props:
        prop_layers = _prop_layers(placed.prop, placed, next_ind, ip, op)
        layers.extend(prop_layers)
        next_ind += len(prop_layers)

    if scene.background is not None:
        layers.append(_background_layer(scene.width, scene.height, scene.background, ip, op))

    doc = _root_comp("scene", scene.width, scene.height, scene.fps, ip, op, layers)
    doc["assets"] = []
    return doc


def compile_timeline(timeline: Timeline) -> Dict[str, Any]:
    """Compile a timeline; scenes are embedded as precomp assets with ip/op windows."""
    total = max(timeline.total_frames, 1)
    layers: List[Dict[str, Any]] = []
    assets: List[Dict[str, Any]] = []

    for i, (at, scene) in enumerate(timeline.scenes):
        ref_id = f"scene_{i}"
        comp = compile_scene(scene)
        assets.append(
            {
                "id": ref_id,
                "layers": comp["layers"],
                "assets": comp.get("assets", []),
                "w": comp["w"],
                "h": comp["h"],
            }
        )
        start = int(at)
        end = start + max(scene.duration, 1)
        layers.append(
            _placement_layer(
                f"scene:{i}",
                ref_id,
                comp["w"],
                comp["h"],
                i + 1,
                timeline.width / 2.0,
                timeline.height / 2.0,
                100.0
                * min(timeline.width / comp["w"], timeline.height / comp["h"]),
                0.0,
                start,
                end,
                st=start,
            )
        )

    doc = _root_comp(
        "timeline", timeline.width, timeline.height, timeline.fps, 0, total, layers
    )
    doc["assets"] = assets
    if timeline.audio_url:
        doc["meta"] = {"audio_url": timeline.audio_url}
    return doc


def compile_prop(prop: Prop, op: Optional[int] = None) -> Dict[str, Any]:
    """Compile a standalone prop to its own Lottie composition."""
    placed = PlacedProp(prop=prop, x=prop.width / 2.0, y=prop.height / 2.0)
    comp_op = op if op is not None else 1
    layers = _prop_layers(prop, placed, 1, 0, comp_op)
    return _root_comp(prop.name, prop.width, prop.height, 30, 0, comp_op, layers)
