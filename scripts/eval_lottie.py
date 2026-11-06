"""Evaluate Lottie character-rig authoring across complexity levels.

Runs N author attempts per level with a real chatbot (or --mock) and reports
per-gate pass rates, iterations-to-accept, and wall time. Answers the spec's
question: how do LLMs perform as rig complexity rises?

Usage:
  python scripts/eval_lottie.py --n 3 --levels L1 L2
  python scripts/eval_lottie.py --mock --n 2
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from baasha_pipeline import lottie_assets  # noqa: E402
from baasha_pipeline.chatbot import ChatInterface  # noqa: E402

SAMPLE_CHARACTERS = [
    {
        "name": "Maya",
        "description": "A 28-year-old mechanical engineer with cropped black hair, wire-frame glasses, a faded olive field jacket over a mustard henley, cargo pants, and scuffed boots. Confident stance, slight smirk.",
    },
    {
        "name": "Old Tom",
        "description": "A weathered fisherman in his 60s with a full grey beard, navy beanie, heavy wool coat with brass buttons, and rubber boots. Holds a imaginary pipe. Warm tired eyes.",
    },
    {
        "name": "Nova",
        "description": "A teenage courier with bright violet undercut hair, oversized headphones around the neck, reflective silver bomber jacket, black leggings, and high-top sneakers. Energetic posture.",
    },
]


class MockChatbot:
    """Offline baseline: emits the golden example rig for any prompt."""

    def __init__(self):
        from baasha_pipeline.lottie_sdk.example import build_example_rig

        src_lines = ["rig = CharacterRig("]
        r = build_example_rig()
        src_lines.append(f"    name={r.name!r},")
        src_lines.append("    parts=[")
        for p in r.parts:
            shapes = ", ".join(
                f"Shape(kind=ShapeKind.{s.kind.value.upper()}, size={tuple(s.size)}, position={tuple(s.position)}, corner_radius={s.corner_radius})"
                for s in p.shapes
            )
            src_lines.append(
                f"        Part(name={p.name!r}, shapes=[{shapes}], fill={tuple(p.fill)}, "
                f"position={tuple(p.position)}, rotation={p.rotation}, scale={tuple(p.scale)}, parent={p.parent!r}),"
            )
        src_lines.append("    ],")
        src_lines.append("    poses=[")
        for pose in r.poses:
            src_lines.append(f"        Pose(name={pose.name!r}, joints={pose.joints!r}),")
        src_lines.append("    ],")
        src_lines.append("    clips=[")
        for c in r.clips:
            src_lines.append(f"        Clip(name={c.name!r}, keyframes={c.keyframes!r}),")
        src_lines.append("    ],")
        src_lines.append(")")
        self._src = "\n".join(src_lines)

    def fetch_text(self, p, **kw):
        return f"```python\n{self._src}\n```"

    def new_conversation(self):
        return "mock"

    def delete_conversation(self):
        return None


def run_eval(levels, n, mock=False, use_vision=True, outdir="lottie/eval"):
    if mock:
        # Stub S3 so the eval can run offline; still exercises real render + gates.
        def _fake_triple(outdir, slug, source, doc, preview_bytes):
            from baasha_pipeline.lottie_sdk import validate as v

            v.assert_valid_lottie(doc)
            base = f"{outdir}/{slug}"
            return {
                "source_url": f"file:///{base}/source.py",
                "lottie_url": f"file:///{base}/animation.json",
                "preview_url": f"file:///{base}/preview.png",
            }

        lottie_assets._upload_triple = _fake_triple

    results = []
    for level in levels:
        for i in range(n):
            char = SAMPLE_CHARACTERS[i % len(SAMPLE_CHARACTERS)]
            chatbot = MockChatbot() if mock else ChatInterface()
            if not mock:
                try:
                    chatbot.new_conversation()
                except Exception:
                    pass
            t0 = time.time()
            try:
                entry = lottie_assets.author_character_rig(
                    chatbot,
                    char["name"],
                    char["description"],
                    complexity=level,
                    outdir=f"{outdir}/{level}",
                    use_vision_judge=use_vision,
                    max_iters=3,
                )
            except Exception as e:
                entry = {"name": char["name"], "lottie_error": {"gate": "exception", "errors": [str(e)]}}
            dt = time.time() - t0
            ok = bool(entry and entry.get("lottie_url"))
            results.append(
                {
                    "level": level,
                    "character": char["name"],
                    "accepted": ok,
                    "score": entry.get("lottie_score") if entry else None,
                    "seconds": round(dt, 2),
                    "error": entry.get("lottie_error") if entry else None,
                }
            )
            status = "PASS" if ok else "FAIL"
            print(f"[{level}] {char['name']}: {status} ({dt:.1f}s) score={entry.get('lottie_score') if entry else None}")
            if not mock:
                try:
                    chatbot.delete_conversation()
                except Exception:
                    pass

    summary = {}
    for level in levels:
        rows = [r for r in results if r["level"] == level]
        accepted = [r for r in rows if r["accepted"]]
        scores = [r["score"] for r in accepted if isinstance(r.get("score"), (int, float))]
        summary[level] = {
            "n": len(rows),
            "pass_rate": round(len(accepted) / len(rows), 3) if rows else 0,
            "avg_seconds": round(sum(r["seconds"] for r in rows) / len(rows), 2) if rows else 0,
            "avg_score": round(sum(scores) / len(scores), 2) if scores else None,
        }
    print("\n=== SUMMARY ===")
    print(json.dumps(summary, indent=2))
    return {"results": results, "summary": summary}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--levels", nargs="+", default=["L1"])
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--no-vision", action="store_true")
    ap.add_argument("--outdir", default="lottie/eval")
    args = ap.parse_args()
    use_vision = (not args.no_vision) and (not args.mock)
    run_eval(args.levels, args.n, mock=args.mock, use_vision=use_vision, outdir=args.outdir)


if __name__ == "__main__":
    main()
