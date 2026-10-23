# Lottie Pipeline Specification

## Overview
The Lottie Pipeline substitutes diffusion-image and video-asset generation with composable **Lottie components**, while keeping the core workflow (prompt → research → screenplay → characters → scenes → video) and its orchestration unchanged. Characters become reusable Python-authored rigs; scenes instantiate those rigs as higher-order components; a timeline sequences scenes over the existing TTS/audio stack. Final MP4 render stays on Remotion (`@remotion/lottie`) — added later; the first delivery target is a browser-playable Lottie timeline.

This supersedes the ad-hoc `baasha_pipeline/motion_graphics_agent.py` prototype (LLM writes raw Lottie JSON → single "not blank" check), which is retained only as the **L0 baseline** for evaluation.

---

## 1. Core Principle: Code is Truth, JSON is Artifact

| Layer | Format | Location | Rationale |
| :--- | :--- | :--- | :--- |
| **Source** | Python (SDK-authored) | local `outdir` during gen → S3 `lottie/{idea_id}.{version}/…/source.py` | LLMs author reliably against a typed API; source is diffable (PATCH-friendly) and reviewable. |
| **Compiled** | Lottie JSON | S3 `…/animation.json` | Deterministic compiler output; format correctness is guaranteed by us, not the LLM. Scenes embed character comps as precomps — **no JSON copy-paste**. |
| **Preview** | PNG contact sheet | S3 `…/preview.png`; stored as `url` in `character_ref` | Existing consumers (`judge_image_grid`, stages board, PATCH ref-passing) keep working untouched. |

Artifacts are never hand-edited JSON. Regeneration always starts from source.

### 1.1 S3 Layout
```
lottie/{idea_id}.{version}/
  characters/{slug}/source.py
  characters/{slug}/animation.json
  characters/{slug}/preview.png      # canonical turnaround: front neutral + action pose
  scenes/{panel_idx}/source.py
  scenes/{panel_idx}/animation.json
  scenes/{panel_idx}/preview.png
  timeline/source.py
  timeline/animation.json
  timeline/player.html               # quick-review page (static/lottie_player.html + asset URL)
```

### 1.2 Data Model (additive only)
`character_ref` entries remain `{name, url, ...}` compatible; new optional fields:
```json
{
  "name": "General Maximus",
  "url": "https://…/preview.png",
  "lottie_url": "https://…/animation.json",
  "lottie_source_url": "https://…/source.py",
  "complexity": "L1"
}
```
`Draft.video_data` gains an additive `"lottie"` block: `{"timeline_url": …, "scene_urls": [...]}`. Old drafts and image-engine flows are unaffected.

---

## 2. Component Model (Higher-Order Contract)

Three levels; each level **imports/instantiates** the level below and controls it only through its public API — this is the no-duplication / consistency guarantee.

### 2.1 Character Rig (`lottie_sdk/rig.py`)
- `CharacterRig`: named `BodyPart`s (shape primitives + fill/stroke + anchor + parent ref), `Palette`, `Proportions`, `Pose` library, `Clip` library (named keyframe sequences over poses).
- `rig.instantiate(outfit=None, expression="neutral")` → `CharacterInstance`.
- `CharacterInstance` control surface: `set_pose({...joints})`, `play(clip_name)`, `place(x, y, scale, rotation)`.
- L0 exception: raw Lottie JSON authored directly by the LLM (baseline only; no SDK guarantees).

### 2.2 Scene (`lottie_sdk/scene.py`)
- `Scene(size, background)`: `place(instance, …)`, `add_prop(Prop, …)`.
- Receives characters **only as compiled prebuilt rigs** (fetched from `lottie_url`); scene code may pass props/pose/clip overrides, never redraw parts.

### 2.3 Timeline (`lottie_sdk/timeline.py`)
- `Timeline(fps, audio)`: `add(scene, at, transition)` — mirrors existing Remotion DSL primitives (`transition`, `audio`, `subtitle_text`) so the later Remotion swap is mechanical.

### 2.4 Compiler (`lottie_sdk/compiler.py`)
- Rig → shape layers with null-parent hierarchy; clips → transform keyframes.
- Scene → composition; character comps embedded via Lottie `assets[]` precomps (single source of truth).
- Timeline → one root composition sequencing scene comps by in/out points.

---

## 3. Quality System (Why This Fixes Hit-or-Miss)

Every artifact passes sequential gates. Each failure produces a **targeted fix prompt** (source + structured errors + screenshots + judge report) — never a blind retry. Max 3 retries per gate; hard fail marks the artifact failed (mirrors `AssetGenStages.FAILED`); draft self-healing (`/cleanup`) is unchanged.

| Gate | Checks | Failure feed |
| :--- | :--- | :--- |
| **G0 Static/SDK** | Source parses against SDK (pydantic); compiler emits structurally valid Lottie (layer refs, keyframe shape, `ip < op`, sizes) | Exception with line/field context |
| **G1 Render sanity** | Playwright seeks N timestamps; each frame non-blank; expected parts visible (region check vs layer bboxes) | Contact sheet + failing regions |
| **G2 Semantic judge** | Vision LLM vs description/bible (identity, palette, staging, motion readability) — same pattern as `holistic-grid-judge`; threshold-gated | `consistency_score`, `fix_directive`, `unchanged_elements` |
| **G3 Continuity** (scenes only) | Instantiated characters vs canonical rig turnaround renders (the refs `judge_image_grid` already consumes) | Identity-drift directive — fixes scene source only, never the rig |

### 3.1 Render Harness (`lottie_sdk/render.py`)
Generalizes `BrowserManager`/`test_lottie`: load via lottie-web, `goToAndStop` at scripted timestamps, emit a PIL contact sheet. Deterministic; no wall-clock waits for animation playback.

---

## 4. Complexity Ladder (Evaluation Dimension)

| Level | Authoring surface | Purpose |
| :--- | :--- | :--- |
| **L0** | Raw Lottie JSON (existing `motion_graphics_agent`) | Control baseline |
| **L1** | Paper-doll rig: layered parts, parametric poses, 2–3 clips | **Default** |
| **L2** | L1 + custom shape flourishes + longer clip library | Ceiling probe |

Same story/bible input at every level; only generation prompt + SDK surface switch. Per-character `complexity` is stored in `character_ref`. Eval script (`scripts/eval_lottie.py`) reports per-gate pass rate, retries-to-pass, wall time, judge score by level.

---

## 5. Pipeline Integration (Leaf Swaps Only)

### 5.1 Leaf Functions (`baasha_pipeline/lottie_assets.py`)
- `generate_character_lottie(chatbot, char_desc, complexity, style_refs, outdir)` — bible entry → rig code → G0–G2 (turnaround renders) → upload triple → returns ref entry with additive lottie fields.
- `compose_scene_lottie(chatbot, panel_descs, character_list, outdir)` — panel prompts + character refs (JSON fetched for instantiation, preview PNGs for style grounding) → scene code → G0–G3 → uploads → preview montage compatible with the grid judge.
- `create_lottie_timeline(chatbot, scene_refs, video_data, outdir)` — sequence + player config; output is S3-hosted `player.html` + `animation.json`. Remotion swap comes later against the same timeline JSON.

### 5.2 Call-Site Branches (engine-gated; default engine unchanged)
1. `processor.generate_character_bible` (~line 1015): lottie leaf instead of `image_gen` batch.
2. `processor.create_image_grid` (~line 2460): `compose_scene_lottie` instead of `image_gen`; previews montaged into one grid PNG so `judge_image_grid` / bbox flow is reused for G2 judging.
3. `DraftResource.draft_processing_task` stage 5: `create_lottie_timeline` instead of `generate_remotion_video_config`; store under `video_data["lottie"]`.
4. New request param `visual_engine=lottie|image` (default `image`) in `parsers.py`; threaded through the same way `image_engine` is. MCP `start_draft_pipeline` passes it through; all other MCP tools/flows untouched.

PATCH flows inherit support automatically (they call the same processor leaves).

### 5.3 Unchanged
Stages 0–2 (prompt, research/screenplay), TTS/BGM/timepoints, draft versioning & PATCH orchestration, Valkey locks, storage helpers, webhooks, all existing image engines, `stages.html` board (renders preview PNGs as today).

---

## 6. Prompts (`prompts.json` new keys)

| Key | Role |
| :--- | :--- |
| `lottie-character-rig` (+ `-fix`) | Visual DNA / bible entry + SDK cheat-sheet (per complexity level) → Python source |
| `lottie-scene-compose` (+ `-fix`) | Panel descriptions + instance API summary (poses/clips available) + style terms → Python scene source |
| `lottie-judge` | G2 vision prompt — motion-aware ("does the wave read as a wave"), reuses judge-report JSON shape (`consistency_score`, `fix_directive`) |

Stage-2 image-descriptor prompts (`entity-to-image`, `story-split-and-styling`, …) are **not modified** — visual descriptions remain the shared blueprint for both engines.

---

## 7. Quick Review Surface
- `static/lottie_player.html?url=<s3-animation.json>` — play/pause/scrub; served via existing Flask static routes.
- Timeline stage completion links to the hosted player page (same shape as today's preview links).
- No new heavy dependencies: playwright + lottie-web (CDN) + PIL already in stack.

---

## 8. Implementation Order
1. `lottie_sdk/` — models, compiler, validate, render (pure; unit-tested with hand-authored rigs, no LLM).
2. G0–G2 gates + prompts in `lottie_assets.py`; L0 baseline path retained.
3. Three processor call-site branches + `visual_engine` param + additive storage fields.
4. `static/lottie_player.html` + end-to-end draft (sqlite, canned story) proving character → scene → timeline.
5. `scripts/eval_lottie.py` (L0 vs L1 vs L2).
6. Later (out of scope): Remotion `@remotion/lottie` final render, replacing `player.html` as the delivery artifact.

---

## 9. Risks & Mitigations
- **Compiler correctness** is the novel risk → keep L1 deliberately small (≤8 parts, ≤4 poses, ≤3 clips); golden-file tests on compiled JSON shape.
- **LLM code execution** → restricted namespace in `author.py` (allowlist: SDK imports + math/typing only; no network/OS); timeouts; compile-before-render.
- **Grid-judge compatibility** → scene previews are montaged to a single PNG; individual scene JSONs remain the source of truth for the timeline.
- **Scope creep into PATCH** → PATCH branches only where the leaf is already called; no new orchestration.
