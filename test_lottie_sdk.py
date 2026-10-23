"""Unit tests for baasha_pipeline.lottie_sdk (no LLM, no browser)."""

import pytest
from pydantic import ValidationError

from baasha_pipeline.lottie_sdk import (
    CharacterInstance,
    CharacterRig,
    Clip,
    LottieValidationError,
    Part,
    Pose,
    Scene,
    Shape,
    ShapeKind,
    Timeline,
    assert_valid_lottie,
    compile_instance,
    compile_prop,
    compile_rig,
    compile_scene,
    compile_timeline,
    validate_lottie,
    validate_rig,
    validate_scene,
    validate_timeline,
)
from baasha_pipeline.lottie_sdk.example import build_example_rig, build_example_scene


class TestModels:
    def test_example_rig_valid(self):
        rig = build_example_rig()
        validate_rig(rig)
        assert len(rig.parts) == 7
        assert rig.get_clip("wave").duration == 24

    def test_unknown_parent_rejected(self):
        with pytest.raises(ValidationError):
            CharacterRig(
                name="bad",
                parts=[Part(name="a", shapes=[Shape()], parent="ghost")],
            )

    def test_parent_cycle_rejected(self):
        with pytest.raises(ValidationError):
            CharacterRig(
                name="cycle",
                parts=[
                    Part(name="a", shapes=[Shape()], parent="b"),
                    Part(name="b", shapes=[Shape()], parent="a"),
                ],
            )

    def test_pose_unknown_part_rejected(self):
        with pytest.raises(ValidationError):
            CharacterRig(
                name="bad_pose",
                parts=[Part(name="a", shapes=[Shape()])],
                poses=[Pose(name="p", joints={"nope": {"rotation": 10}})],
            )

    def test_clip_unsorted_rejected(self):
        with pytest.raises(ValidationError):
            Clip(name="c", keyframes=[(10, "neutral"), (5, "neutral")])

    def test_instance_unknown_pose_raises(self):
        rig = build_example_rig()
        inst = CharacterInstance(rig=rig)
        with pytest.raises(KeyError):
            inst.set_pose("does_not_exist")

    def test_api_summary(self):
        s = build_example_rig().api_summary()
        assert "right_arm" in s["parts"]
        assert "wave" in s["clips"]
        assert "wave_right" in s["poses"]


class TestCompiler:
    def test_compile_rig_valid_lottie(self):
        rig = build_example_rig()
        doc = compile_rig(rig, clip="wave")
        assert_valid_lottie(doc)
        assert doc["w"] == 512 and doc["h"] == 512
        assert doc["op"] == 24
        names = [l["nm"] for l in doc["layers"]]
        assert "torso" in names and "head" in names
        assert "__background" in names

    def test_compile_rest_pose_no_animation(self):
        rig = build_example_rig()
        doc = compile_rig(rig)
        for layer in doc["layers"]:
            for ch in ("r", "p", "s"):
                assert layer["ks"][ch]["a"] == 0, f"{layer['nm']}.{ch} should be static"

    def test_compile_clip_animates_pose_parts(self):
        rig = build_example_rig()
        doc = compile_rig(rig, clip="wave")
        arm = next(l for l in doc["layers"] if l["nm"] == "right_arm")
        assert arm["ks"]["r"]["a"] == 1
        kfs = arm["ks"]["r"]["k"]
        assert [k["t"] for k in kfs] == [0, 10, 24]
        assert kfs[1]["s"] == [-135.0]

    def test_compile_static_pose(self):
        rig = build_example_rig()
        doc = compile_rig(rig, pose="wave_right")
        arm = next(l for l in doc["layers"] if l["nm"] == "right_arm")
        assert arm["ks"]["r"]["a"] == 0
        assert arm["ks"]["r"]["k"] == -135.0

    @staticmethod
    def _assert_no_single_keyframes(doc):
        for layer in doc.get("layers", []):
            for ch, prop in (layer.get("ks") or {}).items():
                if isinstance(prop, dict) and prop.get("a") == 1:
                    kfs = prop.get("k")
                    assert isinstance(kfs, list) and len(kfs) >= 2, (
                        f"{layer.get('nm')}.{ch} has a single keyframe - "
                        "lottie-web crashes on it and renders the canvas blank"
                    )
                    assert all(isinstance(kf, dict) and "t" in kf for kf in kfs)

    def test_single_keyframe_clip_stays_static(self):
        # A pose-hold clip (one keyframe) must compile to static channels:
        # emitting a:1 with a lone {t, s} keyframe crashed lottie-web and
        # blanked whole scenes during gate G1.
        rig = build_example_rig()
        rig = rig.model_copy(deep=True)
        rig.clips.append(Clip(name="hold", keyframes=[(0, "wave_right")]))
        inst = CharacterInstance(rig=rig)
        inst.set_pose("wave_right")
        inst.play("hold")
        doc = compile_instance(inst, target_op=90)
        arm = next(l for l in doc["layers"] if l["nm"] == "right_arm")
        assert arm["ks"]["r"]["a"] == 0
        self._assert_no_single_keyframes(doc)

    def test_example_scene_has_no_single_keyframes(self):
        doc = compile_scene(build_example_scene())
        self._assert_no_single_keyframes(doc)

    def test_parent_refs(self):
        rig = build_example_rig()
        doc = compile_rig(rig)
        by_name = {l["nm"]: l for l in doc["layers"]}
        assert by_name["head"]["parent"] == by_name["torso"]["ind"]
        assert by_name["left_arm"]["parent"] == by_name["torso"]["ind"]
        assert "parent" not in by_name["torso"]

    def test_layer_order_background_bottom(self):
        rig = build_example_rig()
        doc = compile_rig(rig)
        assert doc["layers"][-1]["nm"] == "__background"

    def test_compile_scene_flattens_characters(self):
        scene = build_example_scene()
        validate_scene(scene)
        doc = compile_scene(scene)
        assert_valid_lottie(doc)
        # Characters are flattened into shape layers under a placement null —
        # nested precomps (scene -> char asset) break lottie-web rendering.
        assert doc["assets"] == []
        null = next(l for l in doc["layers"] if l["ty"] == 3)
        assert null["nm"].startswith("char:")
        assert null["ks"]["s"]["k"][0] == 160.0
        # Every character part layer is parented (root parts -> placement null).
        # Prop shape layers share ty=4, so select by the rig's part names
        # (example props use distinct names).
        rig_part_names = {p.name for p in scene.characters[0].rig.parts}
        parts = [
            l
            for l in doc["layers"]
            if l["ty"] == 4 and l["nm"] not in {"__background"} and l["nm"] in rig_part_names
        ]
        assert len(parts) == len(rig_part_names)
        assert all("parent" in l for l in parts)

    def test_compile_scene_duration_hold(self):
        scene = build_example_scene()
        doc = compile_scene(scene)
        for layer in doc["layers"]:
            assert layer["op"] >= scene.duration

    def test_compile_timeline_sequences(self):
        s1 = build_example_scene()
        s2 = build_example_scene()
        s2.duration = 30
        tl = Timeline(width=1080, height=1920, fps=30).add(s1, at=0).add(s2, at=s1.duration)
        assert tl.total_frames == s1.duration + 30
        validate_timeline(tl)
        doc = compile_timeline(tl)
        assert_valid_lottie(doc)
        assert len(doc["assets"]) == 2
        precomps = [l for l in doc["layers"] if l["ty"] == 0]
        assert len(precomps) == 2
        assert precomps[0]["ip"] == 0 and precomps[0]["op"] == s1.duration
        assert precomps[1]["ip"] == s1.duration
        assert doc["op"] == tl.total_frames

    def test_compile_prop(self):
        prop = build_example_rig().parts[0]
        from baasha_pipeline.lottie_sdk import Prop

        p = Prop(name="block", parts=[Part(name="body", shapes=[Shape(size=(40, 40))])])
        doc = compile_prop(p)
        assert_valid_lottie(doc)


class TestValidate:
    def test_validate_catches_missing_ref(self):
        s1 = build_example_scene()
        tl = Timeline(width=1080, height=1920, fps=30).add(s1, at=0)
        doc = compile_timeline(tl)
        pre = next(l for l in doc["layers"] if l["ty"] == 0)
        pre["refId"] = "missing_asset"
        errors = validate_lottie(doc)
        assert any("missing_asset" in e for e in errors)

    def test_validate_catches_bad_parent(self):
        doc = compile_rig(build_example_rig(), clip="wave")
        doc["layers"][1]["parent"] = 9999
        errors = validate_lottie(doc)
        assert any("parent" in e for e in errors)

    def test_validate_catches_unsorted_kf(self):
        doc = compile_rig(build_example_rig(), clip="wave")
        arm = next(l for l in doc["layers"] if l["nm"] == "right_arm")
        arm["ks"]["r"]["k"] = list(reversed(arm["ks"]["r"]["k"]))
        errors = validate_lottie(doc)
        assert any("sorted" in e for e in errors)

    def test_validate_empty_scene(self):
        with pytest.raises(LottieValidationError):
            validate_scene(Scene(duration=30))

    def test_validate_offcanvas_root_part(self):
        from baasha_pipeline.lottie_sdk.model import Part, Pose, Shape, ShapeKind

        rig = CharacterRig(
            name="ghost",
            parts=[
                Part(
                    name="body",
                    shapes=[Shape(kind=ShapeKind.RECT, size=(100, 100), position=(0, 0))],
                    fill=(0.5, 0.5, 0.5, 1.0),
                    position=(5000, 5000),
                ),
            ],
            poses=[Pose(name="neutral", at=0.0)],
        )
        with pytest.raises(LottieValidationError) as ei:
            validate_rig(rig)
        assert any("outside the canvas" in e for e in ei.value.errors)

    def test_validate_timeline_empty(self):
        with pytest.raises(LottieValidationError):
            validate_timeline(Timeline())


class TestPlaybook:
    """Anti-drift: every real gate/validator error must match the fix skill."""

    @staticmethod
    def _scene_errors(scene):
        with pytest.raises(LottieValidationError) as ei:
            validate_scene(scene)
        return ei.value.errors

    def test_real_scene_validator_errors_all_match(self):
        from baasha_pipeline.lottie_sdk.playbook import match_playbook

        rig = build_example_rig()

        bare = Scene(width=1080, height=1920, duration=90)
        bare.place_character(
            CharacterInstance(rig=rig).place(x=540, y=1400, scale=160)
        )  # no bg, no props, no play -> 3 structural errors

        tiny = Scene(width=1080, height=1920, duration=90, background=(0.5, 0.7, 0.9, 1.0))
        tiny.place_character(CharacterInstance(rig=rig).place(x=540, y=300, scale=50))

        huge = Scene(width=1080, height=1920, duration=90, background=(0.5, 0.7, 0.9, 1.0))
        huge.place_character(CharacterInstance(rig=rig).place(x=540, y=1400, scale=300))

        empty = Scene(width=1080, height=1920, duration=0)

        collected = []
        for sc in (bare, tiny, huge, empty):
            collected.extend(self._scene_errors(sc))
        assert collected, "expected validator errors from the violating scenes"
        for err in collected:
            block = match_playbook([err])
            assert block, f"playbook does not match live validator error: {err!r}"

    def test_real_rig_validator_errors_all_match(self):
        from baasha_pipeline.lottie_sdk.playbook import match_playbook

        bare = CharacterRig(name="bare", parts=[])
        with pytest.raises(LottieValidationError) as ei:
            validate_rig(bare)
        for err in ei.value.errors:
            assert match_playbook([err]), f"unmatched rig error: {err!r}"

    def test_gate_error_samples_all_match(self):
        from baasha_pipeline.lottie_sdk.playbook import match_playbook

        samples = [
            "blank frames: [0, 44, 89] - NOTHING is visible on the canvas.",
            "frame 44 is blank/near-blank",
            "character is cut off at the top edge of the canvas - content reaches within 1%.",
            "SyntaxError: '(' was never closed",
            "NameError: name 'Prop' is not defined",
            "render failed: TimeoutError",
            "layers[ind=2]: duplicate ind",
            "layer 'tee': parent ind 9 not found",
            "score=60\n- set Maya inst.scale to 188",
        ]
        for s in samples:
            assert match_playbook([s]), f"unmatched sample: {s!r}"

    def test_no_match_returns_empty(self):
        from baasha_pipeline.lottie_sdk.playbook import match_playbook

        assert match_playbook([]) == ""
        assert match_playbook(["totally novel reviewer complaint xyz"]) == ""

    def test_prompt_assembly_appends_guide_only_on_match(self):
        from baasha_pipeline.lottie_assets import _errors_block

        base = "character Maya too small: occupies 32% of frame height"
        out = _errors_block([base])
        assert out.startswith(base)
        assert "KNOWN ISSUES - APPLY THIS QUICK GUIDE" in out
        assert "MINIMAL EDIT RULE" in out
        plain = _errors_block(["totally novel reviewer complaint xyz"])
        assert plain == "totally novel reviewer complaint xyz"


class TestScaleConvention:
    def test_factor_scale_is_lifted_to_percent(self):
        from baasha_pipeline.lottie_sdk.compiler import _norm_scale_pct

        assert _norm_scale_pct([1.0, 1.0]) == [100.0, 100.0]
        assert _norm_scale_pct([1.5, 1.5]) == [150.0, 150.0]
        assert _norm_scale_pct([100.0, 100.0]) == [100.0, 100.0]
        assert _norm_scale_pct([150.0, 60.0]) == [150.0, 60.0]

    def test_compiled_rig_renders_factor_scale_rig(self):
        from baasha_pipeline.lottie_sdk.author import exec_rig_source, gate_rig_g0

        src = (
            "rig = CharacterRig(\n"
            "    name='boxy', width=512, height=512,\n"
            "    parts=[\n"
            "        Part(name='torso', shapes=[Shape(kind=ShapeKind.RECT, size=(120, 140), position=(0, 0))], fill=(0.8, 0.3, 0.2, 1.0), position=(256, 256), scale=(1.0, 1.0)),\n"
            "    ],\n"
            "    poses=[Pose(name='neutral', joints={})],\n"
            ")\n"
        )
        rig = exec_rig_source(src)
        doc = gate_rig_g0(rig)
        layer = next(l for l in doc["layers"] if l.get("nm") == "torso")
        assert layer["ks"]["s"]["k"] == [100.0, 100.0, 100.0]


class TestGroqModelRouting:
    def test_groq_hash_model_sets_qwen_reasoning(self):
        from baasha_pipeline.chatbot import ChatInterface
        from unittest.mock import patch

        import baasha_pipeline.chatbot as cb

        with patch.object(cb.groq, "get_client", return_value=object()):
            intf = ChatInterface("groq#qwen/qwen3.8-27b")
        assert intf.llm_name == "qwen/qwen3.8-27b"
        assert intf.groq_reasoning_effort == "medium"
        assert intf.rate_limiter["timeout"] == 50

    def test_groq_model_routing_plain_groq_keeps_gptoss(self):
        from baasha_pipeline.chatbot import ChatInterface
        from unittest.mock import patch

        import baasha_pipeline.chatbot as cb

        with patch.object(cb.groq, "get_client", return_value=object()):
            intf = ChatInterface("groq")
        assert intf.llm_name == "openai/gpt-oss-120b"
        assert intf.groq_reasoning_effort is None
