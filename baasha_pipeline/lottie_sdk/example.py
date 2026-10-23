"""Hand-authored L1 paper-doll rig used by tests and as a few-shot example.

A simple standing figure: head, torso, two arms, two legs. One static pose
library and a short ``wave`` clip. This is the quality floor the LLM must
meet or beat — golden tests compile this rig.
"""

from __future__ import annotations

from .model import CharacterRig, Clip, Part, Pose, Scene, Shape, ShapeKind

SKIN = (0.94, 0.76, 0.62, 1.0)
SHIRT = (0.22, 0.42, 0.72, 1.0)
PANTS = (0.28, 0.28, 0.34, 1.0)
HAIR = (0.18, 0.12, 0.08, 1.0)


def build_example_rig() -> CharacterRig:
    parts = [
        Part(
            name="left_leg",
            shapes=[Shape(kind=ShapeKind.RECT, size=(28, 110), position=(0, 55), corner_radius=12)],
            fill=PANTS,
            anchor=(0, 0),
            position=(-18, 150),
            parent="torso",
        ),
        Part(
            name="right_leg",
            shapes=[Shape(kind=ShapeKind.RECT, size=(28, 110), position=(0, 55), corner_radius=12)],
            fill=PANTS,
            anchor=(0, 0),
            position=(18, 150),
            parent="torso",
        ),
        Part(
            name="torso",
            shapes=[Shape(kind=ShapeKind.RECT, size=(72, 120), position=(0, 60), corner_radius=16)],
            fill=SHIRT,
            anchor=(0, 0),
            position=(256, 200),
        ),
        Part(
            name="left_arm",
            shapes=[Shape(kind=ShapeKind.RECT, size=(22, 95), position=(0, 48), corner_radius=10)],
            fill=SHIRT,
            anchor=(0, 0),
            position=(-46, 20),
            parent="torso",
        ),
        Part(
            name="right_arm",
            shapes=[Shape(kind=ShapeKind.RECT, size=(22, 95), position=(0, 48), corner_radius=10)],
            fill=SHIRT,
            anchor=(0, 0),
            position=(46, 20),
            parent="torso",
        ),
        Part(
            name="head",
            shapes=[Shape(kind=ShapeKind.ELLIPSE, size=(64, 70), position=(0, -38))],
            fill=SKIN,
            anchor=(0, 0),
            position=(0, 0),
            parent="torso",
        ),
        Part(
            name="hair",
            shapes=[Shape(kind=ShapeKind.ELLIPSE, size=(68, 36), position=(0, -62))],
            fill=HAIR,
            anchor=(0, 0),
            position=(0, 0),
            parent="head",
        ),
    ]

    poses = [
        Pose(name="neutral"),
        Pose(
            name="wave_right",
            joints={"right_arm": {"rotation": -135.0}},
        ),
        Pose(
            name="point_left",
            joints={
                "left_arm": {"rotation": 90.0},
                "head": {"rotation": -8.0},
            },
        ),
    ]

    clips = [
        Clip(name="wave", keyframes=[(0, "neutral"), (10, "wave_right"), (24, "neutral")]),
        Clip(name="point", keyframes=[(0, "neutral"), (8, "point_left"), (20, "point_left")]),
    ]

    return CharacterRig(
        name="example_hero",
        width=512,
        height=512,
        fps=30,
        background=(0.86, 0.90, 0.94, 1.0),
        parts=parts,
        poses=poses,
        clips=clips,
    )


def build_example_scene() -> Scene:
    from .model import CharacterInstance, Prop

    rig = build_example_rig()
    hero = CharacterInstance(rig=rig).place(540, 1180, scale=160.0)
    hero.play("wave")
    scene = Scene(width=1080, height=1920, fps=30, duration=60, background=(0.87, 0.92, 0.96, 1.0))
    ground = Prop(
        name="ground",
        parts=[
            Part(
                name="ground_band",
                shapes=[Shape(kind=ShapeKind.RECT, size=(1080, 420), position=(0, 0))],
                fill=(0.55, 0.68, 0.45, 1.0),
                position=(0, 0),
            )
        ],
        width=1080,
        height=420,
    )
    scene.add_prop(ground, x=540, y=1710)
    tree = Prop(
        name="tree",
        parts=[
            Part(
                name="tree_trunk",
                shapes=[Shape(kind=ShapeKind.RECT, size=(40, 160), position=(0, 0))],
                fill=(0.45, 0.3, 0.18, 1.0),
                position=(0, 0),
            ),
            Part(
                name="tree_crown",
                shapes=[Shape(kind=ShapeKind.ELLIPSE, size=(150, 150), position=(0, 0))],
                fill=(0.3, 0.55, 0.3, 1.0),
                position=(0, -110),
                parent="tree_trunk",
            ),
        ],
        width=150,
        height=320,
    )
    scene.add_prop(tree, x=160, y=1300)
    scene.place_character(hero)
    return scene
