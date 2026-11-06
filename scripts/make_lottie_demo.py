"""Generate a real end-to-end Lottie demo chain and render frames for the walkthrough page.

Produces static/lottie_demo/ with:
  rig_source.py, rig.json, rig_sheet.png, rig_frames/f{N}.png
  scene_source.py, scene.json, scene_sheet.png, scene_frames/f{N}.png
  timeline.json, timeline_sheet.png, timeline_frames/f{N}.png
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, ".")

from baasha_pipeline.lottie_sdk import (
    CharacterInstance,
    Scene,
    Timeline,
    compile_rig,
    compile_scene,
    compile_timeline,
    assert_valid_lottie,
    validate_rig,
    validate_scene,
    render_contact_sheet,
    render_frame,
    build_example_rig,
    build_example_scene,
    gate_rig_g0,
    gate_rig_g1,
    gate_scene_g0,
)

OUT = Path("static/lottie_demo")
OUT.mkdir(parents=True, exist_ok=True)


def save_frames(doc, frames, subdir, prefix="f"):
    d = OUT / subdir
    d.mkdir(exist_ok=True)
    names = []
    for f in frames:
        png = render_frame(doc, int(f))
        p = d / f"{prefix}{int(f):03d}.png"
        p.write_bytes(png)
        names.append(p.name)
        print("frame", p)
    return names


def main():
    # --- Rig ---
    rig = build_example_rig()
    rig_doc = compile_rig(rig)
    assert_valid_lottie(rig_doc)
    (OUT / "rig.json").write_text(json.dumps(rig_doc, indent=2))

    rig_frames = save_frames(rig_doc, [0, 8, 15, 23], "rig_frames")
    sheet = render_contact_sheet(rig_doc, frames=[0, 8, 15, 23], cols=4)
    (OUT / "rig_sheet.png").write_bytes(
        __import__("io").BytesIO().getvalue()
        if False
        else (lambda: (__import__("io").BytesIO(), sheet.save(__import__("io").BytesIO()))[0].getvalue())()
    )
    # proper save
    import io as _io

    buf = _io.BytesIO()
    sheet.save(buf, format="PNG")
    (OUT / "rig_sheet.png").write_bytes(buf.getvalue())

    # --- Scene ---
    scene = build_example_scene()
    scene_doc = compile_scene(scene)
    assert_valid_lottie(scene_doc)
    (OUT / "scene.json").write_text(json.dumps(scene_doc, indent=2))

    scene_frames = save_frames(scene_doc, [0, 8, 16, 24, 32, 40], "scene_frames")
    sheet = render_contact_sheet(scene_doc, frames=[0, 10, 20, 30, 40, 50], cols=3)
    buf = _io.BytesIO()
    sheet.save(buf, format="PNG")
    (OUT / "scene_sheet.png").write_bytes(buf.getvalue())

    # --- Timeline ---
    scene2 = Scene(width=1080, height=1920, fps=30, duration=45, background=(0.92, 0.94, 0.97, 1.0))
    rig2 = build_example_rig()
    hero2 = CharacterInstance(rig=rig2).place(540, 1000, scale=140.0)
    hero2.play("point")
    scene2.place_character(hero2)

    tl = Timeline(width=1080, height=1920, fps=30)
    tl.add_clip(scene, start_frame=0)
    tl.add_clip(scene2, start_frame=60)
    tl_doc = compile_timeline(tl)
    assert_valid_lottie(tl_doc)
    (OUT / "timeline.json").write_text(json.dumps(tl_doc, indent=2))

    timeline_frames = save_frames(tl_doc, [0, 20, 40, 60, 80, 100], "timeline_frames")
    sheet = render_contact_sheet(tl_doc, frames=[0, 20, 40, 60, 80, 100], cols=3)
    buf = _io.BytesIO()
    sheet.save(buf, format="PNG")
    (OUT / "timeline_sheet.png").write_bytes(buf.getvalue())

    # --- Reports ---
    report = {
        "rig_validate": validate_rig(rig),
        "scene_validate": validate_scene(scene),
        "gate_g0": gate_rig_g0(rig),
        "gate_g1": gate_rig_g1(rig_doc),
        "rig_frames": rig_frames,
        "scene_frames": scene_frames,
        "timeline_frames": timeline_frames,
        "rig_layers": len(rig_doc.get("layers", [])),
        "scene_layers": len(scene_doc.get("layers", [])),
        "timeline_layers": len(tl_doc.get("layers", [])),
        "rig_assets": len(rig_doc.get("assets", [])),
        "scene_assets": len(scene_doc.get("assets", [])),
        "timeline_assets": len(tl_doc.get("assets", [])),
    }
    (OUT / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    print("DONE")


if __name__ == "__main__":
    main()
