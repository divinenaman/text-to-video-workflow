#!/usr/bin/env python3
"""
Simplistic ffmpeg renderer — alternate to the Remotion (pataka-remotion Lambda) path.

Renders each shot as an oversampled canvas with a drifting crop window
(v4-style, scripts/make_directed_v4.py), so camera motion is smooth, and derives
the motion from the draft's contextual "focus direction" of each image
(processor.find_image_focus_direction — the same direction strings remotion v4
consumed as `focusPoint`).

Motion semantics by direction (generalized focusPoint):
  middle                  -> alternating zoom-in / zoom-out, centered
  left / right            -> horizontal pan revealing content
  top / bottom            -> vertical pan
  top-left .. bottom-right-> diagonal drift + slight zoom punch toward corner
When directions are missing, a deterministic alternating pattern keeps the
video alive anyway.

Data inputs from draft video_data (same structures remotion configs consume):
  images[idx]               [url, ...]
  image_to_videos           {"<idx+1>": url}
  search_images[idx]        [url, bg_color, lottie_url?]  (preferred primary)
  audios[idx]               [url_or_-1, duration_s]       (-1 = silent shot)
  image_focus_directions    ["top", "left", ...] optional

CLI (mirrors scripts/render_lottie_local.py):
  --idea / --version        load video_data from the dev DB
  --video-data file.json    bypass the DB entirely
  --out path.mp4            output (default tmp/<idea>.<version>.ffmpeg/render.mp4)
  --webhook URL             GET-called on success (server video_gen_webhook)
  --transition dissolve|cut
  --fps / --size WxH / --workdir

Engine switch lives in config.ini (loaded by server.py, see trigger_render):
  [RENDER] MODE = remotion | ffmpeg
"""

import argparse
import configparser
import hashlib
import json
import math
import os
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FPS = 25
DEFAULT_W, DEFAULT_H = 1080, 1920
ZOOM_F = 1.18   # oversampled canvas -> slack room for the crop window to travel
XFADE_D = 0.45  # crossfade seconds between shots
ANIMATION_BUFFER_SEC = 0.8

TEMPORAL_DIRS = ("top", "bottom")
SIDE_DIRS = ("left", "right")


# ----------------------------------------------------------------------- utils


def fetch_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r)


def load_video_data_from_db(idea_id: str, version: str) -> dict:
    cfg = configparser.ConfigParser()
    cfg.read(os.path.join(ROOT, "config.ini"))
    db = cfg["DATABASE-DEV"]
    import psycopg2

    conn = psycopg2.connect(
        host=db["HOST"], port=db["PORT"], user=db["USER"],
        password=db["PASSWD"], dbname=db["DATABASE"],
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


def resolve_asset(url, dest):
    """Support remote urls and plain local paths; returns a usable local path."""
    if os.path.exists(url):
        return url
    if not url or url == "-1":
        return None
    if url.startswith("file://"):
        return url[len("file://"):]
    return download(url, dest)


def cache_path(workdir, url, prefix, ext):
    h = hashlib.md5(url.encode()).hexdigest()[:10]
    return os.path.join(workdir, "assets", f"{prefix}_{h}.{ext}")


def asset_ext(url, default="png"):
    base = (url or "").split("?")[0].rsplit(".", 1)[-1].lower()
    if base in ("mp4", "webm"):
        return "mp4"
    if base in ("png", "jpg", "jpeg", "webp"):
        return "jpeg" if base == "jpg" else base
    return default


def ffprobe_duration(path):
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", path],
        capture_output=True, text=True,
    )
    try:
        return float(r.stdout.strip())
    except Exception:
        return 0.0


# ------------------------------------------------------------- direction logic


def direction_anchor(direction):
    """Direction string -> (fx, fy) anchor fractions in [0..1] of travel slack."""
    d = (direction or "middle").lower().strip()
    fx, fy = 0.5, 0.5
    if "left" in d:
        fx = 0.0
    elif "right" in d:
        fx = 1.0
    if d.startswith("top") or d == "top":
        fy = 0.0
    elif "bottom" in d:
        fy = 1.0
    return fx, fy


INTENSITY_TRAVEL = {
    "subtle": {"z": 0.10, "t": 0.50},
    "medium": {"z": 0.20, "t": 0.85},
    "strong": {"z": 0.32, "t": 1.00},
}


def mix(a, b, f):
    return a + (b - a) * f


def legacy_shot_motion(idx, direction):
    """Pre-camera_moves behaviour: 9-anchor mapping with alternating zoom."""
    a_in = idx % 2 == 0
    d = (direction or "middle").lower().strip()
    fx, fy = direction_anchor(d)

    if d == "middle":
        if a_in:
            return (1.0, 0.84, 0.5, 0.5, 0.5, 0.5)   # centered zoom in
        return (0.84, 1.0, 0.5, 0.5, 0.5, 0.5)       # centered zoom out

    if d in ("left", "right"):                       # horizontal pan
        if a_in:
            return (0.96, 0.96, 1.0, 0.5, 0.0, 0.5)
        return (0.96, 0.96, 0.0, 0.5, 1.0, 0.5)
    if d in ("top", "bottom"):                       # vertical pan
        if a_in:
            return (0.96, 0.96, 0.5, 1.0, 0.5, 0.0)
        return (0.96, 0.96, 0.5, 0.0, 0.5, 1.0)

    # diagonal: drift toward the corner with a slight zoom punch
    if a_in:
        return (1.0, 0.86, 1.0 - fx, 1.0 - fy, fx, fy)
    far = ((1 - fx) * 0.8 + 0.1, (1 - fy) * 0.8 + 0.1)
    return (0.88, 0.98, fx, fy, *far)


def shot_motion(idx, direction, cam=None):
    """Return (zoom_start, zoom_end, fx_start, fy_start, fx_end, fy_end).

    zoom = crop window as a fraction of the OUT size. With a `cam` dict from
    image_camera_moves the motion, direction and magnitude follow the vision
    LLM's per-shot plan; otherwise a deterministic legacy pattern applies.
    """
    if not isinstance(cam, dict) or not (cam.get("move") or cam.get("direction")):
        return legacy_shot_motion(idx, direction)

    move = (cam.get("move") or "drift-toward-focus").lower()
    inten = INTENSITY_TRAVEL.get(
        str(cam.get("intensity") or "medium").lower(), INTENSITY_TRAVEL["medium"]
    )
    fx1, fy1 = direction_anchor(cam.get("direction") or direction)

    if move == "static":
        # near-still frame with a barely-there telephoto breathe
        return (0.985, 0.945, 0.5, 0.5, 0.5, 0.5)

    if move in ("dolly-in", "dolly-out"):
        z1 = 1.0 - inten["z"]
        zf0, zf1 = (1.0, z1) if move == "dolly-in" else (z1, 1.0)
        # window centre progressively leans toward the POI as we approach it
        fx0, fx1a = mix(0.5, fx1, inten["t"] * 0.25), mix(0.5, fx1, inten["t"] * 0.75)
        fy0, fy1a = mix(0.5, fy1, inten["t"] * 0.25), mix(0.5, fy1, inten["t"] * 0.75)
        return (zf0, zf1, fx0, fy0, fx1a, fy1a)

    if move in ("pan-left", "pan-right"):
        fx1 = fx1 if fx1 != 0.5 else (0.0 if move == "pan-left" else 1.0)
        fx0 = mix(fx1, 1.0 - fx1, inten["t"])
        return (0.96, 0.96, fx0, fy1, fx1, fy1)

    if move in ("tilt-up", "tilt-down"):
        fy1 = fy1 if fy1 != 0.5 else (0.0 if move == "tilt-up" else 1.0)
        fy0 = mix(fy1, 1.0 - fy1, inten["t"])
        return (0.96, 0.96, fx1, fy0, fx1, fy1)

    # drift-toward-focus
    z1 = 1.0 - inten["z"] * 0.6
    fx0 = mix(fx1, 1.0 - fx1, inten["t"] * 0.8)
    fy0 = mix(fy1, 1.0 - fy1, inten["t"] * 0.8)
    return (1.0, z1, fx0, fy0, fx1, fy1)


def build_shot_filter(out_w, out_h, move, n_frames, counter="on"):
    """Ken-Burns shot: fit and center the asset on an oversampled canvas,
    then let zoompan animate a virtual camera over it.

    zoompan drives both zoom (window size) and pan (window position) per
    output frame — ffmpeg's `crop` only evaluates w/h at init, so a dynamic
    crop renders every frame identical. The camera window is aspect-locked
    to OUT; anchors fx/fy are fractions of the window's travel range
    (0 = hugging the left/top edge, 0.5 = centered, 1 = right/bottom edge).

    `counter` selects the frame-progress variable: "on" for still-image
    inputs (d = all frames from one image), "in" for video inputs (d = 1,
    one output per input frame).
    """
    nf = max(1, n_frames - 1)
    zs, ze, fxs, fys, fxe, fye = move

    canvas_w = round(out_w * ZOOM_F / 2) * 2
    canvas_h = round(out_h * ZOOM_F / 2) * 2
    p = f"min({nf},({counter}))/{nf}"

    def wt():
        return f"({round(out_w * zs)}+({round(out_w * ze)}-({round(out_w * zs)}))*{p})"

    def ht():
        return f"({round(out_h * zs)}+({round(out_h * ze)}-({round(out_h * zs)}))*{p})"

    def mid(fx, wt_expr, canvas):
        return f"({wt_expr}/2+{fx:.6f}*({canvas}-({wt_expr})))"

    def centre(f0, f1, wt_expr, canvas):
        m0, m1 = mid(f0, wt_expr, canvas), mid(f1, wt_expr, canvas)
        return f"({m0}+({m1}-{m0})*{p})"

    x_expr = f"max(0,min({canvas_w}-({wt()}),({centre(fxs, fxe, wt(), canvas_w)})-({wt()})/2))"
    y_expr = f"max(0,min({canvas_h}-({ht()}),({centre(fys, fye, ht(), canvas_h)})-({ht()})/2))"
    z_expr = f"{canvas_w}/({wt()})"

    d = n_frames if counter == "on" else 1
    zp = (
        f"zoompan=z='{z_expr}':x='{x_expr}':y='{y_expr}'"
        f":d={d}:fps={FPS}:s={out_w}x{out_h}"
    )
    scale_and_pad = (
        f"scale={canvas_w}:{canvas_h}:force_original_aspect_ratio=decrease,"
        f"pad={canvas_w}:{canvas_h}:(ow-iw)/2:(oh-ih)/2:color=black"
    )
    return f"{scale_and_pad},{zp},fps={FPS}"


# --------------------------------------------------------------------- manifest


def extract_manifest(data, animation_buffer_sec=ANIMATION_BUFFER_SEC):
    """Turn video_data into ordered shot dicts (mirrors remotion v5 semantics)."""
    audios = data.get("audios") or []
    images = data.get("images") or []
    i2v = data.get("image_to_videos") or {}
    s_images = data.get("search_images") or []
    directions = data.get("image_focus_directions") or []
    camera_moves = data.get("image_camera_moves") or []
    cinematic = data.get("cinematic") or []

    if not audios:
        # pre-audio drafts: fall back to image-driven shots with silent audio
        audios = [["-1", 5.0] for _ in images]
        if not s_images:
            s_images = list(images)

    def _entry_url(e):
        if isinstance(e, str):
            return e
        if isinstance(e, (list, tuple)) and e:
            return e[0] if isinstance(e[0], str) else None
        return None

    shots = []
    for idx, a in enumerate(audios):
        url = a if isinstance(a, str) else (a[0] if a else "-1")
        audio_dur = (
            float(a[1])
            if isinstance(a, (list, tuple)) and len(a) > 1 and a[1]
            else 0.0
        )
        scene = cinematic[idx] if idx < len(cinematic) else {}
        scene_dur = (
            float(scene["duration"])
            if isinstance(scene, dict) and scene.get("duration")
            else 0.0
        )
        base_dur = max(scene_dur, audio_dur, 5.0 if not scene_dur and not audio_dur else 0.0)
        dur = base_dur + animation_buffer_sec

        asset_url, kind = None, "img"
        s = s_images[idx] if len(s_images) > idx else None
        s_url = _entry_url(s)
        if s_url:
            asset_url = s_url
            if isinstance(s, (list, tuple)) and len(s) > 2 and s[2]:
                asset_url = s[2]  # lottie url preferred, classic remotion semantics
        else:
            base = i2v.get(str(idx + 1))
            cand = _entry_url(images[idx]) if idx < len(images) else None
            if cand and cand in i2v and not base:
                base = i2v[cand]
            base = base or cand
            if base:
                kind = "video" if asset_ext(base) == "mp4" else "img"
                asset_url = base
        if not asset_url:
            continue
        d = directions[idx] if len(directions) > idx else None
        cam = camera_moves[idx] if len(camera_moves) > idx else None
        shots.append(
            {"idx": idx, "kind": kind, "url": asset_url, "dur": dur,
             "audio": url,
             "audio_duration": audio_dur,
             "audio_offset": (
                 animation_buffer_sec if url and url != "-1" else 0.0
             ),
             "dir": d if isinstance(d, str) and d else "middle",
             "cam": cam if isinstance(cam, dict) else None}
        )
    return shots


# ---------------------------------------------------------------------- render


def render_shot(shot, src_path, out_path, out_w, out_h):
    dur = shot["dur"]
    n_frames = math.ceil(dur * FPS)
    move = shot_motion(shot["idx"], shot["dir"], shot.get("cam"))
    is_video = shot["kind"] == "video"
    counter = "in" if is_video else "on"
    vf = build_shot_filter(out_w, out_h, move, n_frames, counter=counter)

    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    if is_video:
        cmd += ["-i", src_path, "-an"]
    else:
        cmd += ["-i", src_path]  # single frame; zoompan expands it
    cmd += [
        "-vf", vf, "-frames:v", str(n_frames) if not is_video else "-1",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-pix_fmt", "yuv420p", out_path,
    ]
    if is_video:
        # video sources decide duration on their own timeline; cap instead
        del cmd[cmd.index("-frames:v") + 1]
        cmd[cmd.index("-frames:v")] = "-t"
        cmd.insert(cmd.index("-t") + 1, f"{dur:.3f}")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"shot {shot['idx']} render failed: {r.stderr[-500:]}")


def concat_shots(clip_paths, transition, out_path, workdir, total_dur):
    """Hard-cut concat, or a chained xfade dissolve graph ending in a fade-out."""
    if transition != "dissolve" or len(clip_paths) < 2:
        concat_list = os.path.join(workdir, "concat.txt")
        with open(concat_list, "w") as f:
            for c in clip_paths:
                f.write(f"file '{c}'\n")
        r = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
             "-i", concat_list, "-c:v", "libx264", "-preset", "fast",
             "-crf", "18", "-pix_fmt", "yuv420p", out_path],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            raise RuntimeError(f"concat failed: {r.stderr[-500:]}")
        return out_path

    cmds = ["ffmpeg", "-y", "-loglevel", "error"]
    inputs = []
    for c in clip_paths:
        cmds += ["-i", c]
        inputs.append(c)

    durs = [ffprobe_duration(p) for p in clip_paths]
    chains = []
    out_label, cursor = "[0:v]", durs[0]
    for i in range(1, len(clip_paths)):
        offset = round(cursor - XFADE_D, 3)
        result_label = "[vout]" if i == len(clip_paths) - 1 else f"[x{i}]"
        chains.append(
            f"{out_label}[{i}:v]xfade=transition=fade:"
            f"duration={XFADE_D}:offset={offset}{result_label}"
        )
        out_label = result_label
        cursor = offset + durs[i]
    chains.append(
        f"[vout]fade=t=out:st={max(0.0, total_dur - 0.8):.3f}:d=0.8[vf]"
    )

    cmd = cmds + ["-filter_complex", ";".join(chains), "-map", "[vf]",
                  "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                  "-pix_fmt", "yuv420p", out_path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"xfade chain failed: {r.stderr[-800:]}")
    return out_path


def shot_starts(durs, transition):
    """Start times of each shot on the final timeline (xfade compresses)."""
    starts, cursor = [0.0], durs[0]
    for i in range(1, len(durs)):
        if transition == "dissolve":
            cursor = max(0.0, cursor - XFADE_D)
        starts.append(round(cursor, 3))
        cursor += durs[i]
    return starts


def build_audio_track(shots, workdir, clip_durs, transition):
    """Place full audio events after their visual lead-ins on the final timeline.

    Unlike the old per-shot windows, audio is not trimmed at the next picture
    boundary; it may continue across a dissolve/cut. A silent base track pins
    the mix duration to the final video duration.
    """
    starts = shot_starts(clip_durs, transition)
    total = starts[-1] + clip_durs[-1]
    track = os.path.join(workdir, "audio_full.wav")
    inputs = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-t", f"{total:.3f}",
        "-i", "anullsrc=r=44100:cl=stereo",
    ]
    chains = ["[0:a]atrim=duration={:.3f},asetpts=PTS-STARTPTS[base]".format(total)]
    audio_labels = ["[base]"]

    for shot_position, sh in enumerate(shots):
        audio_url = sh.get("audio")
        if not audio_url or audio_url == "-1":
            continue

        local = cache_path(workdir, audio_url, "aud", asset_ext(audio_url, "mp3"))
        audio_path = resolve_asset(audio_url, local)
        inputs += ["-i", audio_path]
        input_idx = len(audio_labels)
        label = f"[a{input_idx}]"
        delay_ms = int(
            round(
                (starts[shot_position] + float(sh.get("audio_offset") or 0.0))
                * 1000
            )
        )
        chains.append(
            f"[{input_idx}:a]aformat=sample_rates=44100:channel_layouts=stereo,"
            f"adelay={delay_ms}|{delay_ms}{label}"
        )
        audio_labels.append(label)

    mix = "".join(audio_labels)
    chains.append(
        f"{mix}amix=inputs={len(audio_labels)}:duration=first:normalize=0,"
        f"atrim=duration={total:.3f},asetpts=PTS-STARTPTS[aout]"
    )
    r = subprocess.run(
        [*inputs, "-filter_complex", ";".join(chains),
         "-map", "[aout]", "-t", f"{total:.3f}",
         "-c:a", "pcm_s16le", track],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(f"audio mix failed: {r.stderr[-400:]}")
    return track


def final_mux(video, track, out_path, bgm_path=None, bgm_volume=0.30):
    """Mux narration (and optionally looping background music) under the video."""
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", video]
    if track and os.path.exists(track):
        if bgm_path and os.path.exists(bgm_path):
            # narration first so duration=first pins the mix to the timeline,
            # bgm loops underneath at whisper volume
            cmd += [
                "-i", track,
                "-stream_loop", "-1", "-i", bgm_path,
                "-filter_complex",
                f"[2:a]volume={bgm_volume}[bg];"
                f"[1:a][bg]amix=inputs=2:duration=first:dropout_transition=0,"
                f"apad,aresample=44100[aout]",
                "-map", "0:v", "-map", "[aout]",
                "-c:a", "aac", "-b:a", "192k", "-shortest",
            ]
        else:
            cmd += ["-i", track, "-c:a", "aac", "-b:a", "192k", "-shortest"]
    cmd += ["-c:v", "copy", "-movflags", "+faststart", out_path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"mux failed: {r.stderr[-500:]}")


def request_webhook(webhook, out_path):
    try:
        import requests

        requests.get(webhook, params={"path": out_path}, timeout=30)
        print(f"webhook notified: {webhook}")
    except Exception as e:
        print(f"webhook notify failed: {e}")


# ------------------------------------------------------------------------ main


def main():
    global FPS
    ap = argparse.ArgumentParser()
    ap.add_argument("--idea")
    ap.add_argument("--version")
    ap.add_argument("--video-data")
    ap.add_argument("--out", default=None)
    ap.add_argument("--webhook", default=None)
    ap.add_argument("--transition", default="dissolve", choices=["dissolve", "cut"])
    ap.add_argument("--size", default=None, help="WxH, default draft width/height")
    ap.add_argument("--fps", type=int, default=FPS)
    ap.add_argument("--workdir", default=None)
    ap.add_argument(
        "--animation-buffer", type=float, default=ANIMATION_BUFFER_SEC,
        help="seconds of image animation before each shot's audio begins",
    )
    args = ap.parse_args()

    FPS = args.fps
    if args.animation_buffer < 0:
        ap.error("--animation-buffer must be non-negative")

    if args.video_data:
        with open(args.video_data) as f:
            data = json.load(f)
        idea_id, version = "manifest", "1"
    else:
        idea_id, version = args.idea, args.version
        data = load_video_data_from_db(idea_id, version)

    out_w, out_h = DEFAULT_W, DEFAULT_H
    if args.size:
        out_w, out_h = map(int, args.size.lower().split("x"))
    else:
        pw = data.get("pixel_width") or data.get("width")
        ph = data.get("pixel_height") or data.get("height")
        if pw and ph:
            out_w, out_h = int(pw), int(ph)

    if not (data.get("images") or data.get("search_images")):
        sys.exit("no image assets in manifest")
    shots = extract_manifest(data, args.animation_buffer)
    if not shots:
        sys.exit("no shots extracted from manifest")

    workdir = args.workdir or os.path.join(ROOT, "tmp", f"{idea_id}.{version}.ffmpeg")
    # Keep old clips out of the cache: their crop and timing behavior differs.
    clips_dir = os.path.join(workdir, "clips_v2")
    os.makedirs(clips_dir, exist_ok=True)
    out_path = args.out or os.path.join(workdir, f"render-{time.time_ns()}.mp4")

    print(f"shooting {len(shots)} shots -> {workdir}")
    clip_paths = []
    for s in shots:
        clip = os.path.join(clips_dir, f"shot_{s['idx']:03d}.mp4")
        if not (os.path.exists(clip) and os.path.getsize(clip) > 2048):
            src = resolve_asset(s["url"], cache_path(workdir, s["url"], "img",
                                                asset_ext(s["url"])))
            render_shot(s, src, clip, out_w, out_h)
            cam_desc = (
                f"cam={s['cam'].get('move')}/{s['cam'].get('intensity')}"
                if isinstance(s.get("cam"), dict) and s["cam"].get("move")
                else f"dir={s['dir']}"
            )
            print(f"  shot {s['idx']:03d} {s['kind']:5s} {s['dur']:.1f}s "
                  f"{cam_desc}")
        else:
            print(f"  shot {s['idx']:03d} skipped (cached)")
        clip_paths.append(clip)

    total_dur = sum(s["dur"] for s in shots)
    clip_durs = [ffprobe_duration(c) for c in clip_paths]
    assembly = concat_shots(clip_paths, args.transition,
                            os.path.join(workdir, "video_only.mp4"), workdir,
                            total_dur)
    track = build_audio_track(shots, workdir, clip_durs, args.transition)
    bgm = (data.get("bgm") or [None])[0]
    bgm_path = None
    if bgm:
        try:
            bgm_path = resolve_asset(
                bgm, cache_path(workdir, bgm, "bgm", asset_ext(bgm, "mp3"))
            )
        except Exception as e:
            print(f"bgm download failed ({e}); skipping")
    final_mux(assembly, track, out_path, bgm_path=bgm_path)

    dur, size = "?", "?"
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration,size",
         "-of", "csv=p=0", out_path],
        capture_output=True, text=True,
    )
    if r.returncode == 0:
        dur, size = (r.stdout.strip().split(",") + ["?"])[:2]
    print(f"done: {out_path} | {float(dur or 0):.1f}s | {int(size or 0)/1e6:.1f}MB")

    if args.webhook:
        request_webhook(args.webhook, out_path)


if __name__ == "__main__":
    main()
