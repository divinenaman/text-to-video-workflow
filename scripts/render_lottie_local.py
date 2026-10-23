#!/usr/bin/env python3
"""Render a Lottie-engine draft to MP4 locally (replaces the pataka-remotion Lambda).

Pipeline:
  1. Read draft.video_data (DB or --video-data JSON) for the timeline URL + audios.
  2. Fetch the timeline JSON; scenes live in meta.scenes[] (the timeline itself
     only carries schedule + placeholders).
  3. Render each scene frame-by-frame with Playwright + lottie-web (canvas).
  4. Assemble output frames using per-shot windows (audio sentence durations
     when they align with scenes, otherwise scene-natural lengths).
  5. Slice the single full-story TTS file per sentence, pad/trim to each window,
     concat, and mux with ffmpeg.

Usage:
  ./venv/bin/python scripts/render_lottie_local.py --idea <idea_id> [--version 1]
  ./venv/bin/python scripts/render_lottie_local.py --timeline URL --audios audios.json
"""

from __future__ import annotations

import argparse
import base64
import configparser
import hashlib
import json
import os
import subprocess
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RENDER_PAGE = os.path.join(ROOT, "static", "lottie_render.html")

FPS_FALLBACK = 30


# --------------------------------------------------------------------------- IO


def fetch_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r)


def load_video_data_from_db(idea_id: str, version: str) -> dict:
    cfg = configparser.ConfigParser()
    cfg.read(os.path.join(ROOT, "config.ini"))
    db = cfg["DATABASE-DEV"]
    import psycopg2

    conn = psycopg2.connect(
        host=db["HOST"],
        port=db["PORT"],
        user=db["USER"],
        password=db["PASSWD"],
        dbname=db["DATABASE"],
    )
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT video_data FROM drafts WHERE idea_id=%s AND version=%s",
            (idea_id, version),
        )
        row = cur.fetchone()
    finally:
        conn.close()
    if not row or not row[0]:
        sys.exit(f"draft {idea_id}.{version} has no video_data (run the draft first)")
    return json.loads(row[0])


def download(url: str, dest: str) -> str:
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return dest
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with urllib.request.urlopen(url, timeout=120) as r, open(dest, "wb") as f:
        f.write(r.read())
    return dest


# ------------------------------------------------------------------ scene frames


def render_scene_frames(scene_docs: list, scenes_out: str, fps: int) -> list:
    """Render frames 0..min(window, op)-1 for each scene. Returns per-scene frame counts."""
    from playwright.sync_api import sync_playwright

    os.makedirs(scenes_out, exist_ok=True)
    counts: list = []
    with sync_playwright() as p:
        browser = p.firefox.launch()
        page = browser.new_page(viewport={"width": 400, "height": 400})
        page.goto("file://" + RENDER_PAGE)
        page.wait_for_function("window.__ready === true", timeout=30000)

        for i, doc in enumerate(scene_docs):
            info = page.evaluate("(d) => window.__loadScene(d)", doc)
            total = int(info["total"])
            # frames we may ever need for this scene (window-aware cap applied later;
            # render the full natural op once, cheap enough at <=105 frames/scene)
            n = total
            got = 0
            for f in range(n):
                data_url = page.evaluate("(f) => window.__seek(f)", f)
                if not data_url:
                    raise RuntimeError(f"scene {i} frame {f}: no canvas")
                png = base64.b64decode(data_url.split(",", 1)[1])
                path = os.path.join(scenes_out, f"s{i:02d}_f{f:04d}.png")
                with open(path, "wb") as fh:
                    fh.write(png)
                got += 1
            counts.append(got)
            print(f"  scene {i}: {got} frames rendered (op={total})", flush=True)
        browser.close()
    return counts


def assemble_frames(
    scenes_out: str, out_frames: str, window_frames: list, scene_frames: list, fps: int
) -> int:
    """Copy scene frames into the final sequence honoring per-shot windows."""
    os.makedirs(out_frames, exist_ok=True)
    out_i = 0
    for i, n_out in enumerate(window_frames):
        n_src = scene_frames[i]
        for j in range(n_out):
            src = min(j, n_src - 1)
            src_path = os.path.join(scenes_out, f"s{i:02d}_f{src:04d}.png")
            dst_path = os.path.join(out_frames, f"{out_i:05d}.png")
            os.link(src_path, dst_path)
            out_i += 1
    return out_i


# ------------------------------------------------------------------------- audio


def build_audio_track(
    audios: list, window_secs: list, workdir: str, fps: int
) -> str | None:
    """Fit TTS audio to each shot window, concat.

    Supports two layouts:
      - one full narration file: audios == [[url, total_dur]] -> slice by
        accumulated sentence durations (legacy behavior);
      - per-panel files: audios[i] == [url | "-1", dur] -> each panel's own
        clip padded/trimmed to its window, silence sentinels become gaps.
    """
    if not audios:
        return None

    seg_dir = os.path.join(workdir, "audio_segs")
    os.makedirs(seg_dir, exist_ok=True)
    seg_paths: list = []

    full_path = None
    if len(audios) == 1:
        full_url = str(audios[0][0])
        if full_url.startswith("http"):
            try:
                full_path = download(
                    full_url, os.path.join(seg_dir, "full_tts" + ext_of(full_url))
                )
            except Exception as e:
                print(f"warning: full TTS download failed ({e}); using silence", flush=True)

    if full_path is not None:
        cursor = 0.0  # position inside the full TTS file
        for i, w in enumerate(window_secs):
            dur = 0.0
            try:
                dur = float(audios[i][1]) if i < len(audios) else 0.0
            except (TypeError, ValueError):
                dur = 0.0
            seg = os.path.join(seg_dir, f"seg{i:02d}.wav")
            if dur >= 0.2:
                _run(
                    [
                        "ffmpeg", "-y", "-loglevel", "error",
                        "-ss", f"{cursor:.3f}", "-t", f"{max(dur, w):.3f}", "-i", full_path,
                        "-af", "apad", "-t", f"{w:.3f}",
                        "-ar", "44100", "-ac", "2", seg,
                    ]
                )
            else:
                _run(silence_cmd(w, seg))
            seg_paths.append(seg)
            cursor += dur
    else:
        for i, w in enumerate(window_secs):
            url = str(audios[i][0]) if i < len(audios) else ""
            seg = os.path.join(seg_dir, f"seg{i:02d}.wav")
            if url.startswith("http"):
                key = hashlib.md5(url.encode()).hexdigest()[:10]
                try:
                    src = download(url, os.path.join(seg_dir, f"src{i:02d}_{key}" + ext_of(url)))
                except Exception as e:
                    print(f"warning: panel TTS download failed ({e}); silence", flush=True)
                else:
                    _run(
                        [
                            "ffmpeg", "-y", "-loglevel", "error",
                            "-t", f"{w:.3f}", "-i", src,
                            "-af", "apad", "-t", f"{w:.3f}",
                            "-ar", "44100", "-ac", "2", seg,
                        ]
                    )
                    seg_paths.append(seg)
                    continue
            _run(silence_cmd(w, seg))
            seg_paths.append(seg)

    lst = os.path.join(seg_dir, "list.txt")
    with open(lst, "w") as fh:
        for s in seg_paths:
            fh.write(f"file '{s}'\n")
    track = os.path.join(workdir, "audio_full.wav")
    _run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", lst,
            "-ar", "44100", "-ac", "2", track,
        ]
    )
    return track


def silence_cmd(window: float, seg: str) -> list:
    return [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
        "-t", f"{window:.3f}", seg,
    ]


def ext_of(url: str) -> str:
    path = url.split("?", 1)[0]
    ext = os.path.splitext(path)[1].lower()
    return ext if ext in (".mp3", ".wav", ".m4a", ".ogg", ".aac") else ".mp3"


def _run(cmd: list) -> None:
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"cmd failed: {' '.join(cmd[:6])}...\n{res.stderr[-2000:]}")


# -------------------------------------------------------------------------- main


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--idea")
    ap.add_argument("--version", default="1")
    ap.add_argument("--video-data", help="path to dumped video_data JSON (skip DB)")
    ap.add_argument("--timeline", help="timeline JSON URL (skip video_data lookup)")
    ap.add_argument("--audios", help="JSON list [[url,dur],...] (with --timeline)")
    ap.add_argument("--out")
    ap.add_argument("--keep-frames", action="store_true")
    args = ap.parse_args()

    timeline_url = args.timeline
    audios: list = []

    if args.video_data:
        video_data = json.load(open(args.video_data))
    elif args.idea and not timeline_url:
        video_data = load_video_data_from_db(args.idea, args.version)
    else:
        video_data = {}

    if not timeline_url:
        lottie = video_data.get("lottie") or {}
        timeline_url = lottie.get("timeline_url")
        if not timeline_url:
            sys.exit("no lottie timeline in video_data (did the draft reach stage 5?)")
    if args.audios:
        audios = json.load(open(args.audios))
    else:
        audios = video_data.get("audios") or []

    outdir = args.out or os.path.join(
        ROOT, "lottie", f"{args.idea or 'timeline'}.{args.version}", "render"
    )
    os.makedirs(outdir, exist_ok=True)

    timeline = fetch_json(timeline_url)
    fps = int(timeline.get("fr") or FPS_FALLBACK)
    meta = timeline.get("meta") or {}
    scene_metas = meta.get("scenes") or []
    if not scene_metas:
        sys.exit("timeline has no meta.scenes - nothing to render")

    # scene URLs: prefer meta (has start offsets), fall back to lottie_scenes
    scene_urls = [s["url"] for s in scene_metas]
    starts = [int(s.get("start", 0)) for s in scene_metas]
    op = int(timeline.get("op") or 0)
    natural_frames = []
    for i, st in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else op
        natural_frames.append(max(end - st, 1))

    print(f"timeline: {len(scene_metas)} scenes, {op} frames @ {fps}fps", flush=True)
    scene_docs = [fetch_json(u) for u in scene_urls]
    for i, d in enumerate(scene_docs):
        # prefer the scene's own op for animation length
        natural_frames[i] = min(natural_frames[i], int(d.get("op") or natural_frames[i]))
        print(f"  scene {i}: {d.get('w')}x{d.get('h')} op={d.get('op')}", flush=True)

    # ---- windows (seconds per shot)
    window_secs: list = []
    aligned = bool(audios) and len(audios) == len(scene_docs)
    for i, d in enumerate(scene_docs):
        nat = natural_frames[i] / fps
        if aligned:
            try:
                dur = float(audios[i][1])
            except (TypeError, ValueError):
                dur = 0.0
            window_secs.append(dur if dur >= 0.5 else nat)
        else:
            window_secs.append(nat)
    if not aligned and audios:
        print(
            f"warning: audios ({len(audios)}) != scenes ({len(scene_docs)}); "
            "using scene-natural windows",
            flush=True,
        )

    # ---- render scene frames
    print("rendering scene frames via Playwright/firefox...", flush=True)
    scene_counts = render_scene_frames(scene_docs, os.path.join(outdir, "scenes"), fps)

    # ---- assemble output frame sequence
    window_frames = [max(int(round(w * fps)), 1) for w in window_secs]
    total = sum(window_frames)
    out_frames = os.path.join(outdir, "frames")
    n = assemble_frames(os.path.join(outdir, "scenes"), out_frames, window_frames, scene_counts, fps)
    print(f"assembled {n} output frames ({total/fps:.2f}s)", flush=True)

    # ---- audio
    track = build_audio_track(audios, window_secs, outdir, fps)

    # ---- encode
    mp4 = args.out if args.out and args.out.endswith(".mp4") else os.path.join(
        ROOT, "lottie", f"{args.idea or 'timeline'}.{args.version}", "render.mp4"
    )
    os.makedirs(os.path.dirname(mp4), exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-framerate", str(fps), "-i", os.path.join(out_frames, "%05d.png"),
    ]
    if track:
        cmd += ["-i", track, "-c:a", "aac", "-b:a", "192k", "-shortest"]
    cmd += [
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", mp4,
    ]
    _run(cmd)
    print(f"done: {mp4}", flush=True)

    if not args.keep_frames:
        for sub in ("scenes", "frames", "audio_segs"):
            d = os.path.join(outdir, sub)
            if os.path.isdir(d):
                subprocess.run(["rm", "-rf", d])


if __name__ == "__main__":
    main()
