"""Lottie SDK: typed authoring models + deterministic compiler + render harness.

LLMs author Python against ``model.py``; ``compiler.py`` emits Lottie JSON;
``render.py`` produces contact sheets for the G1/G2 judge gates.
"""

from .model import (
    CharacterInstance,
    CharacterRig,
    Clip,
    Part,
    PlacedProp,
    Pose,
    Prop,
    Scene,
    Shape,
    ShapeKind,
    Timeline,
    slugify,
)
from .compiler import (
    compile_instance,
    compile_prop,
    compile_rig,
    compile_scene,
    compile_timeline,
)
from .validate import (
    LottieValidationError,
    assert_valid_lottie,
    validate_lottie,
    validate_rig,
    validate_scene,
    validate_timeline,
)
from .render import (
    LottieBrowserManager,
    frame_is_nonblank,
    render_contact_sheet,
    render_frame,
    render_keyframes,
)
from .author import (
    AuthorExecError,
    exec_rig_source,
    exec_scene_source,
    gate_rig_g0,
    gate_rig_g1,
    gate_scene_g0,
    turnaround_frames,
)
from .example import build_example_rig, build_example_scene

__all__ = [
    "CharacterInstance",
    "CharacterRig",
    "Clip",
    "Part",
    "PlacedProp",
    "Pose",
    "Prop",
    "Scene",
    "Shape",
    "ShapeKind",
    "Timeline",
    "slugify",
    "compile_instance",
    "compile_prop",
    "compile_rig",
    "compile_scene",
    "compile_timeline",
    "LottieValidationError",
    "assert_valid_lottie",
    "validate_lottie",
    "validate_rig",
    "validate_scene",
    "validate_timeline",
    "LottieBrowserManager",
    "frame_is_nonblank",
    "render_contact_sheet",
    "render_frame",
    "render_keyframes",
    "AuthorExecError",
    "exec_rig_source",
    "exec_scene_source",
    "gate_rig_g0",
    "gate_rig_g1",
    "gate_scene_g0",
    "turnaround_frames",
    "build_example_rig",
    "build_example_scene",
]
