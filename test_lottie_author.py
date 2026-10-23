"""Tests for the Lottie authoring loop (sandbox exec + gates, mock LLM)."""

import json

import pytest

from baasha_pipeline.lottie_sdk import (
    CharacterRig,
    LottieValidationError,
    compile_rig,
    exec_rig_source,
    exec_scene_source,
    gate_rig_g0,
    gate_scene_g0,
    validate_lottie,
)
from baasha_pipeline.lottie_sdk.example import build_example_rig, build_example_scene
from baasha_pipeline.lottie_sdk.author import AuthorExecError

EXAMPLE_SOURCE = """
from baasha_pipeline.lottie_sdk import (
    CharacterRig, Part, Pose, Clip, Shape, ShapeKind
)

rig = CharacterRig(
    name="test_hero",
    width=512,
    height=512,
    fps=30,
    background=(0.9, 0.9, 0.9, 1.0),
    parts=[
        Part(name="body", shapes=[Shape(kind=ShapeKind.RECT, size=(80, 160), position=(0, 80), corner_radius=12)], fill=(0.2, 0.4, 0.8, 1.0), position=(256, 180)),
        Part(name="head", shapes=[Shape(kind=ShapeKind.ELLIPSE, size=(60, 60), position=(0, -50))], fill=(0.95, 0.8, 0.6, 1.0), position=(0, 0), parent="body"),
    ],
    poses=[Pose(name="neutral"), Pose(name="nod", joints={"head": {"rotation": 15}})],
    clips=[Clip(name="nod_clip", keyframes=[(0, "neutral"), (10, "nod")])],
)
"""

INJECTED_SOURCE = """
rig = CharacterRig(
    name="injected",
    parts=[
        Part(name="blob", shapes=[Shape(size=(100, 100))], fill=(1, 0, 0, 1), position=(256, 256)),
    ],
    poses=[Pose(name="neutral")],
)
"""


class TestSandboxExec:
    def test_exec_example_source(self):
        rig = exec_rig_source(EXAMPLE_SOURCE)
        assert isinstance(rig, CharacterRig)
        assert rig.name == "test_hero"
        assert rig.get_clip("nod_clip").duration == 10

    def test_sdk_names_preinjected(self):
        rig = exec_rig_source(INJECTED_SOURCE)
        assert rig.name == "injected"

    def test_syntax_error_line(self):
        with pytest.raises(AuthorExecError) as ei:
            exec_rig_source("rig = CharacterRig(  name='x'\n parts=[\n")
        assert ei.value.line is not None or "SyntaxError" in str(ei.value)

    def test_no_rig_defined(self):
        with pytest.raises(AuthorExecError, match="rig"):
            exec_rig_source("x = 1")

    def test_banned_import_rejected(self):
        with pytest.raises(AuthorExecError):
            exec_rig_source("import os\nrig = CharacterRig(name='x', parts=[])")

    def test_build_rig_function(self):
        src = (
            "def build_rig():\n"
            "    return CharacterRig(name='fn', parts=["
            "Part(name='a', shapes=[Shape(size=(10,10))], position=(0,0))],"
            " poses=[Pose(name='neutral')])\n"
        )
        rig = exec_rig_source(src)
        assert rig.name == "fn"


class TestGates:
    def test_g0_accepts_good_rig(self):
        rig = exec_rig_source(EXAMPLE_SOURCE)
        doc = gate_rig_g0(rig)
        assert validate_lottie(doc) == []

    def test_g0_rejects_bad_lottie(self):
        class Boom:
            name = "boom"

            def api_summary(self):
                return {}

        with pytest.raises((LottieValidationError, Exception)):
            gate_rig_g0(Boom())

    def test_g0_compiled_clip_animation(self):
        rig = exec_rig_source(EXAMPLE_SOURCE)
        doc = gate_rig_g0(rig)
        head = next(l for l in doc["layers"] if l["nm"] == "head")
        assert head["ks"]["r"]["a"] == 1


class TestSceneExec:
    def test_scene_with_character_registry(self):
        rig = exec_rig_source(EXAMPLE_SOURCE)
        src = """
scene = Scene(width=1080, height=1920, fps=30, duration=60, background=(1,1,1,1))
ground = Prop(name="ground", parts=[Part(name="floor", shapes=[Shape(kind=ShapeKind.RECT, size=(1080, 420), position=(0, 0))], fill=(0.4, 0.6, 0.4, 1.0), position=(0, 0))], width=1080, height=420)
scene.add_prop(ground, x=540, y=1710)
crate = Prop(name="crate", parts=[Part(name="crate_box", shapes=[Shape(kind=ShapeKind.RECT, size=(120, 120), position=(0, 0))], fill=(0.7, 0.55, 0.3, 1.0), position=(0, 0))], width=120, height=120)
scene.add_prop(crate, x=850, y=1600)
inst = CharacterInstance(rig=CHARACTERS["test_hero"]).place(540, 900, scale=200.0)
inst.play("nod_clip")
scene.place_character(inst)
"""
        scene = exec_scene_source(src, {"test_hero": rig})
        assert len(scene.characters) == 1
        assert scene.characters[0].clip == "nod_clip"
        doc = gate_scene_g0(scene)
        assert validate_lottie(doc) == []
        # Flattened: no nested assets, character parts present as shape layers
        assert doc["assets"] == []
        null = next(l for l in doc["layers"] if l["ty"] == 3)
        assert null["nm"] == "char:test_hero"

    def test_scene_unknown_character(self):
        rig = exec_rig_source(EXAMPLE_SOURCE)
        src = "scene = Scene(duration=10)\nscene.place_character(CharacterInstance(rig=CHARACTERS['ghost']))"
        with pytest.raises(AuthorExecError):
            exec_scene_source(src, {"test_hero": rig})


class TestExampleGolden:
    def test_example_scene_compiles(self):
        scene = build_example_scene()
        doc = gate_scene_g0(scene)
        assert doc["layers"]
        assert doc["assets"] == []
        assert validate_lottie(doc) == []

    def test_example_rig_roundtrip_via_model_dump(self):
        rig = build_example_rig()
        from baasha_pipeline.lottie_sdk.model import CharacterRig as CR

        rehydrated = CR.model_validate(rig.model_dump())
        assert rehydrated.name == rig.name
        assert len(rehydrated.parts) == len(rig.parts)
