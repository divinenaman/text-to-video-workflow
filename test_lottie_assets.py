"""Mocked end-to-end test of author_character_rig / compose_scene_lottie (no LLM, no S3)."""

import json

import pytest

from baasha_pipeline import lottie_assets
from baasha_pipeline.lottie_sdk.example import build_example_rig
from baasha_pipeline.chatbot import Img

GOOD_RIG_SRC = """
rig = CharacterRig(
    name="maya",
    width=512, height=512, fps=30,
    background=(0.9, 0.92, 0.95, 1.0),
    parts=[
        Part(name="torso", shapes=[Shape(kind=ShapeKind.RECT, size=(70, 120), position=(0, 60), corner_radius=14)], fill=(0.3, 0.5, 0.7, 1.0), position=(256, 200)),
        Part(name="head", shapes=[Shape(kind=ShapeKind.ELLIPSE, size=(60, 66), position=(0, -40))], fill=(0.95, 0.78, 0.62, 1.0), position=(0, 0), parent="torso"),
        Part(name="arm", shapes=[Shape(kind=ShapeKind.RECT, size=(20, 90), position=(0, 45), corner_radius=8)], fill=(0.3, 0.5, 0.7, 1.0), position=(44, 15), parent="torso"),
    ],
    poses=[Pose(name="neutral"), Pose(name="raise", joints={"arm": {"rotation": -120}})],
    clips=[Clip(name="wave", keyframes=[(0, "neutral"), (8, "raise"), (20, "neutral")])],
)
"""

GOOD_SCENE_SRC = """
scene = Scene(width=1080, height=1920, fps=30, duration=60, background=(0.95, 0.93, 0.9, 1.0))
ground = Prop(name="ground", parts=[Part(name="ground_band", shapes=[Shape(kind=ShapeKind.RECT, size=(1080, 420), position=(0, 0))], fill=(0.5, 0.66, 0.4, 1.0), position=(0, 0))], width=1080, height=420)
scene.add_prop(ground, x=540, y=1710)
bench = Prop(name="bench", parts=[Part(name="bench_top", shapes=[Shape(kind=ShapeKind.RECT, size=(240, 36), position=(0, 0))], fill=(0.55, 0.4, 0.26, 1.0), position=(0, 0))], width=240, height=36)
scene.add_prop(bench, x=250, y=1450)
inst = CharacterInstance(rig=CHARACTERS["maya"]).place(540, 950, scale=220.0)
inst.play("wave")
scene.place_character(inst)
"""

JUDGE_PASS = json.dumps(
    {
        "consistency_score": 92,
        "pass": True,
        "issues": [],
        "summary": "looks good",
    }
)


class MockChatbot:
    def __init__(self, rig_src=GOOD_RIG_SRC, scene_src=GOOD_SCENE_SRC, judge=JUDGE_PASS):
        self.calls = []
        self.rig_src = rig_src
        self.scene_src = scene_src
        self.judge = judge

    def fetch_text(self, p, **kw):
        if isinstance(p, list):
            text = " ".join(getattr(x, "text", str(x)) for x in p)
        elif isinstance(p, Img):
            text = p.text
        else:
            text = str(p)
        self.calls.append(text)
        if "Motion Continuity Auditor" in text or "consistency_score" in text and "Audit criteria" in text:
            return self.judge
        if "paper-doll character rig" in text or "Senior Motion Designer who authors character" in text:
            return f"```python\n{self.rig_src}\n```"
        # Scene prompts (compose + fix) before the generic gate-failure check -
        # both templates contain "failed a quality gate".
        if "composed Lottie scene failed" in text or "Compose a scene" in text or "INSTANTIATING prebuilt" in text:
            return f"```python\n{self.scene_src}\n```"
        if "previously authored" in text.lower() or "failed a quality gate" in text:
            return f"```python\n{self.rig_src}\n```"
        return f"```python\n{self.rig_src}\n```"


@pytest.fixture
def fake_storage(monkeypatch):
    uploads = {}

    def fake_upload_data(bucket, data, name, acl=None, client=None):
        uploads[name] = data if isinstance(data, str) else data.decode("utf-8", "replace")
        return f"http://test-baasha/{name}"

    def fake_upload_file(bucket, filepath, name, acl=None, client=None):
        with open(filepath, "rb") as f:
            uploads[name] = f.read()
        return f"http://test-baasha/{name}"

    monkeypatch.setattr(lottie_assets.object_storage, "upload_data", fake_upload_data)
    monkeypatch.setattr(lottie_assets.object_storage, "upload_file", fake_upload_file)
    return uploads


def test_author_character_rig_happy_path(fake_storage):
    chatbot = MockChatbot()
    entry = lottie_assets.author_character_rig(
        chatbot,
        "Maya",
        "A young engineer with a blue jacket and warm smile.",
        complexity="L1",
        outdir="lottie/test",
        use_vision_judge=True,
    )
    assert entry["name"] == "Maya"
    assert entry["url"] and entry["url"].endswith("preview.png")
    assert entry["lottie_url"] and entry["lottie_url"].endswith("animation.json")
    assert entry["lottie_source_url"].endswith("source.py")
    assert entry["image_engine"] == "lottie"
    assert entry["complexity"] == "L1"
    assert entry.get("lottie_score") == 92
    assert any(k.endswith("source.py") for k in fake_storage)
    assert any(k.endswith("animation.json") for k in fake_storage)


def test_author_character_rig_fix_loop(fake_storage):
    broken = "rig = CharacterRig(name='x', parts=[])  # will fail model? no - empty parts fails G0"
    # empty parts actually raises on validate_rig (no parts)
    chatbot = MockChatbot(rig_src=broken)
    # first call returns broken; fix prompt also returns broken -> should fail all iters
    entry = lottie_assets.author_character_rig(
        chatbot,
        "Broken",
        "desc",
        outdir="lottie/test",
        use_vision_judge=False,
        max_iters=2,
    )
    assert entry.get("lottie_error")
    assert entry.get("lottie_fallback") is True
    assert entry["url"] is not None
    assert entry["lottie_url"] is not None
    assert len([c for c in chatbot.calls if "failed a quality gate" in c]) >= 1


def test_author_recovers_from_bad_then_good(fake_storage):
    class RecoverChatbot(MockChatbot):
        def __init__(self):
            super().__init__()
            self.n_rig = 0

        def fetch_text(self, p, **kw):
            if isinstance(p, list):
                text = " ".join(getattr(x, "text", str(x)) for x in p)
            elif isinstance(p, Img):
                text = p.text
            else:
                text = str(p)
            self.calls.append(text)
            if "Motion Continuity Auditor" in text or "Audit criteria" in text:
                return self.judge
            if "authors character" in text or "failed a quality gate" in text:
                self.n_rig += 1
                if self.n_rig == 1:
                    return "```python\nrig = nope\n```"
                return f"```python\n{GOOD_RIG_SRC}\n```"
            return f"```python\n{GOOD_RIG_SRC}\n```"

    chatbot = RecoverChatbot()
    entry = lottie_assets.author_character_rig(
        chatbot, "Maya", "desc", outdir="lottie/test", use_vision_judge=True
    )
    assert entry["lottie_url"]
    assert chatbot.n_rig >= 2


def test_compose_scene_happy_path(fake_storage, monkeypatch):
    monkeypatch.setattr(lottie_assets, "_fetch_text", lambda url: GOOD_RIG_SRC)
    chatbot = MockChatbot()
    entries = lottie_assets.compose_scene_lottie(
        chatbot,
        ["Maya waves in a sunlit workshop."],
        [
            {
                "name": "maya",
                "url": "http://x/preview.png",
                "lottie_url": "http://x/animation.json",
                "lottie_source_url": "http://x/source.py",
            }
        ],
        outdir="lottie/test",
        use_vision_judge=True,
    )
    assert len(entries) == 1
    e = entries[0]
    assert e["panel_index"] == 0
    assert e["lottie_url"] and e["url"]


def test_create_lottie_timeline_player(fake_storage, monkeypatch):
    def fake_fetch(url):
        if url.endswith("animation.json"):
            return {"w": 1080, "h": 1920, "fr": 30, "op": 60, "layers": [], "assets": []}
        raise AssertionError(url)

    monkeypatch.setattr(lottie_assets, "_fetch_json", fake_fetch)
    out = lottie_assets.create_lottie_timeline(
        [
            {"lottie_url": "http://x/scene0/animation.json", "url": "http://x/scene0/preview.png"},
            {"lottie_url": "http://x/scene1/animation.json", "url": "http://x/scene1/preview.png"},
        ],
        audio_url="http://x/voice.mp3",
        outdir="lottie/test",
    )
    assert out["timeline_url"].endswith(".json")
    assert out["player_url"].endswith(".html")
    player = fake_storage[[k for k in fake_storage if k.endswith(".html")][-1]]
    assert "lottie-web" in player
    assert "scene0/animation.json" in player


def test_judge_prompts_format():
    for key in ("lottie-judge", "lottie-rig-judge"):
        tpl = lottie_assets._load_prompt(key)
        out = tpl.format(SPEC="spec", CHARACTER_LIST="[]")
        assert "consistency_score" in out
        assert "pass" in out


def test_scene_fix_prompt_mentions_playbook():
    tpl = lottie_assets._load_prompt("lottie-scene-fix")
    assert "QUICK GUIDE" in tpl
    assert "COMPLETE" in tpl
