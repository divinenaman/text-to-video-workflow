"""Lottie SDK data models.

The authoring surface the LLM writes against. Everything here is pure data +
lightweight behavior; compilation to Lottie JSON lives in ``compiler.py``.
"""

from __future__ import annotations

import ast
import re
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union

from pydantic import BaseModel, Field, field_validator, model_validator

RGBA = Tuple[float, float, float, float]
XY = Tuple[float, float]

_NAMED_COLORS: Dict[str, Tuple[float, float, float, float]] = {
    "white": (1.0, 1.0, 1.0, 1.0),
    "black": (0.0, 0.0, 0.0, 1.0),
    "red": (1.0, 0.0, 0.0, 1.0),
    "green": (0.0, 0.5, 0.0, 1.0),
    "blue": (0.0, 0.0, 1.0, 1.0),
    "yellow": (1.0, 0.9, 0.0, 1.0),
    "orange": (1.0, 0.5, 0.0, 1.0),
    "purple": (0.5, 0.0, 0.5, 1.0),
    "pink": (1.0, 0.4, 0.7, 1.0),
    "brown": (0.4, 0.26, 0.13, 1.0),
    "grey": (0.5, 0.5, 0.5, 1.0),
    "gray": (0.5, 0.5, 0.5, 1.0),
    "navy": (0.0, 0.0, 0.4, 1.0),
    "teal": (0.0, 0.5, 0.5, 1.0),
    "sky": (0.53, 0.81, 0.92, 1.0),
    "skyblue": (0.53, 0.81, 0.92, 1.0),
    "gold": (0.85, 0.68, 0.22, 1.0),
    "beige": (0.96, 0.94, 0.86, 1.0),
    "tan": (0.82, 0.7, 0.55, 1.0),
    "cream": (1.0, 0.97, 0.86, 1.0),
    "cyan": (0.0, 1.0, 1.0, 1.0),
    "magenta": (1.0, 0.0, 1.0, 1.0),
    "olive": (0.5, 0.5, 0.0, 1.0),
    "maroon": (0.5, 0.0, 0.0, 1.0),
    "lime": (0.5, 1.0, 0.0, 1.0),
}


def _normalize_channels(vals: List[float]) -> Tuple[float, float, float, float]:
    r, g, b = vals[0], vals[1], vals[2]
    a = vals[3] if len(vals) > 3 else 1.0
    if max(r, g, b) > 1.0:
        # author wrote 0-255 channels (e.g. (255, 255, 255))
        r, g, b = r / 255.0, g / 255.0, b / 255.0
        if a > 1.0:
            a = a / 255.0
    a = min(max(a, 0.0), 1.0)
    return (r, g, b, a)


def _coerce_rgba(v: Any) -> Optional[Tuple[float, float, float, float]]:
    """Coerce common LLM color slips: hex strings, named colors, RGB triples,
    0-255 ints, '(r,g,b,a)' stringified tuples."""
    if v is None:
        return None
    if isinstance(v, (list, tuple)):
        if len(v) == 3:
            return _normalize_channels([float(x) for x in v])
        if len(v) == 4:
            return _normalize_channels([float(x) for x in v])
        raise ValueError(
            f"color needs 3 or 4 numbers (r,g,b[,a]) in 0-1 or 0-255, got {v!r}"
        )
    if isinstance(v, str):
        s = v.strip()
        if s.startswith("#"):
            h = s[1:]
            if len(h) in (3, 4):
                h = "".join(ch * 2 for ch in h)
            if len(h) in (6, 8):
                r = int(h[0:2], 16) / 255.0
                g = int(h[2:4], 16) / 255.0
                b = int(h[4:6], 16) / 255.0
                a = int(h[6:8], 16) / 255.0 if len(h) == 8 else 1.0
                return (r, g, b, a)
        low = s.lower()
        if low in _NAMED_COLORS:
            return _NAMED_COLORS[low]
        try:
            parsed = ast.literal_eval(s if s[0] in "([" else f"({s})")
        except (ValueError, SyntaxError, IndexError):
            parsed = None
        if isinstance(parsed, (list, tuple)):
            return _coerce_rgba(parsed)
    raise ValueError(
        f"cannot parse color {v!r} - use RGBA floats (r,g,b,a) in [0,1] "
        "(e.g. (1.0, 0.5, 0.0, 1.0)) or '#rrggbb'"
    )


def _coerce_xy(v: Any) -> Tuple[float, float]:
    """Coerce position/size/anchor slips: '(256, 320)' strings, scalars, 3D."""
    if isinstance(v, (int, float)):
        return (float(v), float(v))
    if isinstance(v, (list, tuple)):
        if len(v) == 1:
            return (float(v[0]), float(v[0]))
        if len(v) >= 2:
            return (float(v[0]), float(v[1]))
        raise ValueError(f"expected 2 numbers, got {v!r}")
    if isinstance(v, str):
        try:
            parsed = ast.literal_eval(v.strip())
        except (ValueError, SyntaxError):
            parsed = None
        if isinstance(parsed, (int, float, list, tuple)):
            return _coerce_xy(parsed)
    raise ValueError(f"cannot parse coordinate {v!r} - use a (x, y) tuple of numbers")


def _coerce_scale_percent(value: Any) -> float:
    """Treat small positive instance scales as factors, matching rig scales."""
    scale = float(value)
    return scale * 100.0 if 0.0 < scale <= 8.0 else scale


def _coerce_shapes(v: Any) -> Any:
    """Accept shapes='rect', shapes={'kind': ...}, or ['rect', {...}]."""
    if isinstance(v, str):
        return [{"kind": v}]
    if isinstance(v, dict):
        return [v]
    if isinstance(v, list):
        return [{"kind": x} if isinstance(x, str) else x for x in v]
    return v


_KIND_SYNONYMS = {
    "circle": "ellipse",
    "round": "ellipse",
    "oval": "ellipse",
    "dot": "ellipse",
    "sphere": "ellipse",
    "ball": "ellipse",
    "square": "rect",
    "rectangle": "rect",
    "box": "rect",
    "bar": "rect",
}


def _coerce_kind(v: Any) -> Any:
    if isinstance(v, str):
        s = _KIND_SYNONYMS.get(v.strip().lower(), v.strip().lower())
        if s in ("ellipse", "rect", "path"):
            return s
        # Models sometimes put descriptors here ("short_messy" for hair).
        # An ellipse is the safe paper-doll rendering - never fail G0 on it.
        return "ellipse"
    return v


class ShapeKind(str, Enum):
    ELLIPSE = "ellipse"
    RECT = "rect"
    PATH = "path"


class Shape(BaseModel):
    kind: ShapeKind = ShapeKind.ELLIPSE
    size: XY = (100.0, 100.0)
    position: XY = (0.0, 0.0)
    corner_radius: float = 0.0
    vertices: List[XY] = Field(default_factory=list)
    in_tangents: List[XY] = Field(default_factory=list)
    out_tangents: List[XY] = Field(default_factory=list)
    closed: bool = True

    @field_validator("kind", mode="before")
    @classmethod
    def _kind_before(cls, v: Any) -> Any:
        return _coerce_kind(v)

    @field_validator("size", "position", mode="before")
    @classmethod
    def _xy_before(cls, v: Any) -> Any:
        if isinstance(v, str) or isinstance(v, (list, tuple)):
            return _coerce_xy(v)
        return v

    @field_validator("size")
    @classmethod
    def _positive_size(cls, v: XY) -> XY:
        if v[0] <= 0 or v[1] <= 0:
            raise ValueError("shape size must be positive")
        return v

    @field_validator("vertices", "in_tangents", "out_tangents", mode="before")
    @classmethod
    def _path_points_before(cls, v: Any) -> Any:
        if v is None:
            return []
        if not isinstance(v, (list, tuple)):
            raise ValueError("path points must be a list of (x, y) coordinates")
        return [_coerce_xy(point) for point in v]

    @model_validator(mode="after")
    def _valid_path(self) -> "Shape":
        if self.kind != ShapeKind.PATH:
            return self
        min_points = 3 if self.closed else 2
        if len(self.vertices) < min_points:
            raise ValueError(
                f"{'closed' if self.closed else 'open'} path needs at least "
                f"{min_points} vertices"
            )
        for label, tangents in (
            ("in_tangents", self.in_tangents),
            ("out_tangents", self.out_tangents),
        ):
            if tangents and len(tangents) != len(self.vertices):
                raise ValueError(
                    f"path {label} must have one coordinate per vertex"
                )
        return self


class Part(BaseModel):
    """A single drawable body part / prop piece.

    ``position``/``rotation`` are the rest transform of the part's anchor in
    parent space. Child parts parented to this part live in this space.
    """

    name: str
    shapes: List[Shape]
    fill: RGBA = (0.2, 0.2, 0.2, 1.0)
    stroke: Optional[RGBA] = None
    stroke_width: float = 0.0
    anchor: XY = (0.0, 0.0)
    position: XY = (0.0, 0.0)
    rotation: float = 0.0
    scale: XY = (100.0, 100.0)
    parent: Optional[str] = None
    opacity: float = 100.0

    @field_validator("name")
    @classmethod
    def _valid_name(cls, v: str) -> str:
        if not v or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", v):
            raise ValueError(f"invalid part name: {v!r}")
        return v

    @field_validator("shapes", mode="before")
    @classmethod
    def _shapes_before(cls, v: Any) -> Any:
        return _coerce_shapes(v)

    @field_validator("fill", mode="before")
    @classmethod
    def _fill_before(cls, v: Any) -> Any:
        return _coerce_rgba(v)

    @field_validator("stroke", mode="before")
    @classmethod
    def _stroke_before(cls, v: Any) -> Any:
        if v is None:
            return None
        return _coerce_rgba(v)

    @field_validator("anchor", "position", "scale", mode="before")
    @classmethod
    def _part_xy_before(cls, v: Any) -> Any:
        if isinstance(v, str) or isinstance(v, (list, tuple)):
            return _coerce_xy(v)
        return v


class Pose(BaseModel):
    """Named joint overrides applied on top of rest transforms.

    Keys of ``joints`` are part names; values may override any of:
    ``rotation`` (degrees), ``position`` (XY in parent space), ``scale`` (XY percent).
    """

    name: str
    joints: Dict[str, Dict[str, Union[float, List[float]]]] = Field(default_factory=dict)


class Clip(BaseModel):
    """Named animation: an ordered list of (frame, pose_name) keyframes."""

    name: str
    keyframes: List[Tuple[int, str]]

    @field_validator("keyframes")
    @classmethod
    def _valid_keyframes(cls, v: List[Tuple[int, str]]) -> List[Tuple[int, str]]:
        if not v:
            raise ValueError("clip must have at least one keyframe")
        frames = [kf[0] for kf in v]
        if frames != sorted(frames):
            raise ValueError("clip keyframes must be sorted by frame")
        if len(set(frames)) != len(frames):
            raise ValueError("clip keyframe frames must be unique")
        if frames[0] < 0:
            raise ValueError("clip keyframe frames must be >= 0")
        return v

    @property
    def duration(self) -> int:
        return self.keyframes[-1][0]


class CharacterRig(BaseModel):
    """A reusable character (or major prop) component.

    Compiled once per draft; scenes instantiate it rather than re-authoring.
    """

    name: str
    width: int = 512
    height: int = 512
    fps: int = 30
    parts: List[Part]
    poses: List[Pose] = Field(default_factory=list)
    clips: List[Clip] = Field(default_factory=list)
    background: Optional[RGBA] = None

    @field_validator("background", mode="before")
    @classmethod
    def _background_before(cls, v: Any) -> Any:
        return _coerce_rgba(v)

    @model_validator(mode="after")
    def _check_refs(self) -> "CharacterRig":
        names = [p.name for p in self.parts]
        if len(names) != len(set(names)):
            raise ValueError("part names must be unique")
        name_set = set(names)
        for p in self.parts:
            if p.parent is not None and p.parent not in name_set:
                raise ValueError(f"part {p.name!r} has unknown parent {p.parent!r}")
        self._check_no_cycles()
        pose_names = [p.name for p in self.poses]
        if len(pose_names) != len(set(pose_names)):
            raise ValueError("pose names must be unique")
        clip_names = [c.name for c in self.clips]
        if len(clip_names) != len(set(clip_names)):
            raise ValueError("clip names must be unique")
        for pose in self.poses:
            for jn in pose.joints:
                if jn not in name_set:
                    raise ValueError(f"pose {pose.name!r} references unknown part {jn!r}")
        for clip in self.clips:
            for _, pose_name in clip.keyframes:
                if pose_name not in pose_names:
                    raise ValueError(
                        f"clip {clip.name!r} references unknown pose {pose_name!r}"
                    )
        return self

    def _check_no_cycles(self) -> None:
        parent_of = {p.name: p.parent for p in self.parts}
        for start in parent_of:
            seen = set()
            cur = start
            while cur is not None:
                if cur in seen:
                    raise ValueError(f"parent cycle involving {start!r}")
                seen.add(cur)
                cur = parent_of.get(cur)

    def get_part(self, name: str) -> Part:
        for p in self.parts:
            if p.name == name:
                return p
        raise KeyError(f"unknown part: {name!r}")

    def get_pose(self, name: str) -> Pose:
        for p in self.poses:
            if p.name == name:
                return p
        raise KeyError(f"unknown pose: {name!r}")

    def get_clip(self, name: str) -> Clip:
        for c in self.clips:
            if c.name == name:
                return c
        raise KeyError(f"unknown clip: {name!r}")

    def api_summary(self) -> Dict[str, Any]:
        """Compact description of the control surface, for prompt embedding."""
        return {
            "name": self.name,
            "size": [self.width, self.height],
            "parts": [p.name for p in self.parts],
            "poses": {
                p.name: sorted(p.joints.keys()) for p in self.poses
            },
            "clips": {c.name: c.duration for c in self.clips},
        }


class CharacterInstance(BaseModel):
    """A live instantiation of a rig with placement + playback state."""

    rig: CharacterRig
    x: float = 0.0
    y: float = 0.0
    scale: float = 100.0
    rotation: float = 0.0
    pose: Optional[str] = None
    clip: Optional[str] = None

    @field_validator("scale", mode="before")
    @classmethod
    def _scale_as_percent(cls, value: Any) -> float:
        return _coerce_scale_percent(value)

    def place(self, x: float, y: float, scale: float = 100.0, rotation: float = 0.0):
        self.x = x
        self.y = y
        self.scale = _coerce_scale_percent(scale)
        self.rotation = rotation
        return self

    def set_pose(self, pose_name: str):
        if pose_name not in {p.name for p in self.rig.poses}:
            raise KeyError(f"unknown pose: {pose_name!r}")
        self.pose = pose_name
        return self

    def play(self, clip_name: str):
        if clip_name not in {c.name for c in self.rig.clips}:
            raise KeyError(f"unknown clip: {clip_name!r}")
        self.clip = clip_name
        return self

    def api_summary(self) -> Dict[str, Any]:
        s = self.rig.api_summary()
        s["placement"] = {"x": self.x, "y": self.y, "scale": self.scale, "rotation": self.rotation}
        s["pose"] = self.pose
        s["clip"] = self.clip
        return s


class Prop(BaseModel):
    """A simple scene prop: a standalone named shape cluster (not a full rig)."""

    name: str
    parts: List[Part]
    width: int = 256
    height: int = 256
    background: Optional[RGBA] = None

    @field_validator("parts")
    @classmethod
    def _unique_parts(cls, v: List[Part]) -> List[Part]:
        names = [p.name for p in v]
        if len(names) != len(set(names)):
            raise ValueError("prop part names must be unique")
        return v


class PlacedProp(BaseModel):
    prop: Prop
    x: float = 0.0
    y: float = 0.0
    scale: float = 100.0
    rotation: float = 0.0

    def place(self, x: float, y: float, scale: float = 100.0, rotation: float = 0.0):
        self.x = x
        self.y = y
        self.scale = scale
        self.rotation = rotation
        return self


class Scene(BaseModel):
    """A single staged shot: characters + props on a canvas for a duration."""

    width: int = 1080
    height: int = 1920
    fps: int = 30
    duration: int = 90
    background: Optional[RGBA] = None
    characters: List[CharacterInstance] = Field(default_factory=list)
    props: List[PlacedProp] = Field(default_factory=list)

    @field_validator("background", mode="before")
    @classmethod
    def _background_before(cls, v: Any) -> Any:
        return _coerce_rgba(v)

    def place_character(
        self,
        instance: CharacterInstance,
        x: Optional[float] = None,
        y: Optional[float] = None,
        scale: Optional[float] = None,
        rotation: Optional[float] = None,
        position: Optional[XY] = None,
    ) -> CharacterInstance:
        if position is not None:
            if x is not None or y is not None:
                raise ValueError("use either position or x/y, not both")
            x, y = position
        if (x is None) != (y is None):
            raise ValueError("character placement requires both x and y")
        if x is not None and y is not None:
            instance.place(
                x,
                y,
                scale=instance.scale if scale is None else scale,
                rotation=instance.rotation if rotation is None else rotation,
            )
        elif scale is not None or rotation is not None:
            raise ValueError("scale and rotation require x/y or position")
        self.characters.append(instance)
        return instance

    def add_prop(
        self,
        prop: Prop,
        x: float = 0.0,
        y: float = 0.0,
        scale: float = 100.0,
        rotation: float = 0.0,
    ) -> PlacedProp:
        pp = PlacedProp(prop=prop, x=x, y=y, scale=scale, rotation=rotation)
        self.props.append(pp)
        return pp

    def api_summary(self) -> Dict[str, Any]:
        return {
            "size": [self.width, self.height],
            "fps": self.fps,
            "duration": self.duration,
            "characters": [c.api_summary() for c in self.characters],
            "props": [p.prop.name for p in self.props],
        }


class Timeline(BaseModel):
    """The movie: ordered scenes over audio."""

    width: int = 1080
    height: int = 1920
    fps: int = 30
    audio_url: Optional[str] = None
    scenes: List[Tuple[int, Scene]] = Field(default_factory=list)

    def add(self, scene: Scene, at: int = 0) -> "Timeline":
        if at < 0:
            raise ValueError("scene start must be >= 0")
        self.scenes.append((at, scene))
        self.scenes.sort(key=lambda t: t[0])
        return self

    @property
    def total_frames(self) -> int:
        if not self.scenes:
            return 0
        return max(at + sc.duration for at, sc in self.scenes)


def slugify(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", name.strip()).strip("_").lower()
    return s or "asset"
