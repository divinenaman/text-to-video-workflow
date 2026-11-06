# Proposal: Director-Aware Editorial Timeline for FFmpeg Renders

**Status:** Proposed  
**Scope:** FFmpeg rendering path, first  
**Date:** 2026-11-06

## Summary

Replace the FFmpeg renderer's implicit audio-led slideshow schedule with an
explicit editorial timeline. Picture duration, audio duration, and audio
placement must be independent values. The screenplay/director establishes how
long an image or action beat stays on screen; generated audio is measured and
placed on that timeline rather than defining the shot's duration.

The renderer should support intentional pauses before speech, dialogue or
voiceover continuing over a cut, reaction holds after speech, and transitions
that overlap pictures without unintentionally shifting or truncating audio.

## Problem

The current FFmpeg manifest uses `video_data.audios[i][1]` as the duration for
shot `i`. It schedules that audio at the shot start and truncates or pads it to
the same window. It does not use `cinematic[i].duration` to determine picture
duration. Consequently, a short dialogue line can make a scene feel rushed,
while an action beat's intended screen time is lost.

The generated draft inspected for this proposal had 50 planned scenes totalling
211 seconds, audio entries totalling 183 seconds, and a final render of about
159 seconds. Many voiceover scenes had `"-1"` audio entries, so they rendered
as silence despite containing narration text. Picture, speech, and silence
currently lack a shared, explicit editorial schedule.

## Goals

- Give every shot an explicit visual duration, independent of its audio.
- Place generated dialogue, voiceover, ambience, and effects on a common
  timeline with measured durations and optional offsets.
- Preserve authored action and reaction time when speech is shorter than the
  shot.
- Avoid truncating speech when it is longer than its planned shot.
- Support audio that starts before a cut or continues over a cut (J-cuts and
  L-cuts).
- Make cinematic pauses, transitions, and sound levels predictable and
  inspectable.
- Keep existing drafts renderable through a legacy-compatible fallback.

## Non-goals for the first version

- Replacing the screenplay format or introducing a full non-linear editor.
- Supporting arbitrary multi-track manual editing in the create form.
- Reworking the Remotion renderer in the same change.
- Automatically changing or speeding up speech to fit a shot.
- Generating ambience or sound effects that are not already requested by the
  draft.

## Proposed timeline model

Add a versioned `editorial_timeline` object to `video_data`. Existing
`cinematic`, `audios`, and `timepoints_map` remain the source inputs during
migration; the timeline is a normalized, renderer-facing schedule.

```json
{
  "version": 1,
  "fps": 25,
  "shots": [
    {
      "shot_index": 0,
      "visual_duration_sec": 5.5,
      "transition_out": {
        "type": "dissolve",
        "duration_sec": 0.45
      },
      "beats": [
        {
          "kind": "voiceover",
          "asset": "https://.../narration.mp3",
          "asset_duration_sec": 3.8,
          "start_offset_sec": 0.6,
          "gain_db": 0,
          "timepoints_ref": "https://.../narration.mp3"
        }
      ],
      "hold_after_audio_sec": 1.1
    }
  ]
}
```

### Timing semantics

- `visual_duration_sec` controls how long the shot occupies the picture
  timeline. It includes the shot's motion/animation.
- Each audio beat has an `asset_duration_sec` measured from the generated
  media, not inferred from the planned shot length. It is metadata for
  validation and playback scheduling.
- `start_offset_sec` is relative to the shot's start. Negative offsets are
  allowed only when the beat explicitly permits pre-lap into the previous
  shot; otherwise it is clamped or rejected during validation.
- `hold_after_audio_sec` is descriptive/editorial metadata. It must not extend
  the shot a second time when the explicit visual duration already includes
  that hold.
- A beat may cross a shot boundary. The canonical audio start/end are derived
  from shot start plus offset and measured duration; do not truncate at a
  picture cut.
- Transition overlap changes the picture timeline's shot start times. Audio
  offsets must be calculated against those final starts, not against
  uncompressed shot durations.
- Dialogue and voiceover are distinct beat kinds. `"silence"` is intentional
  silence; missing audio for a spoken line is an error/status, not silence.

The exact representation may be refined during implementation, but these
semantics are required.

## Timeline authoring and duration policy

1. **Director/screenplay duration is the picture baseline.** Use the existing
   `cinematic[].duration` when present. For old drafts without it, retain the
   legacy audio duration or a documented fallback.
2. **Measure generated audio.** Probe each TTS output after generation and
   save its actual duration. Preserve word/character timepoints when available.
3. **Short audio does not shorten a shot.** Keep the remaining time for action,
   visual emphasis, or a reaction/hold. Do not fill it with a new image
   automatically.
4. **Long audio does not get cut or time-compressed.** The default policy is
   to extend the shot to the audio end, unless an explicit subsequent shot can
   carry the tail as an L-cut. Record any duration adjustment in the timeline.
5. **Overlaps are explicit.** J/L-cuts require a permitted overlap and must not
   cause unrelated dialogue tracks to collide. A later shot may begin while
   prior audio continues.
6. **Frame rounding is deterministic.** Convert final start/end times to frame
   boundaries only at render time, using the configured FPS.

An eventual pacing policy may choose among `preserve_director_duration`,
`extend_for_audio`, and `fit_target_runtime`; the first implementation should
use `preserve_director_duration` with safe extension for audio that would
otherwise be cut.

## Audio editorial behavior

- Generate a TTS beat for each spoken dialogue line and each narration/voiceover
  line. Only explicit silence/action beats should produce no speech audio.
- Preserve per-character voice assignments for dialogue. Voiceover uses the
  configured narrator voice, with a clear fallback when no narrator is set.
- Store audio asset URL, measured duration, speaker/narrator, beat kind,
  start offset, gain, and available timepoint reference.
- Support per-beat gain and a project-level mix policy. Initial controls:
  narration/dialogue level, music level, optional music ducking under speech,
  and ambience/effects level when those tracks exist.
- Missing or failed TTS must surface in draft status/logs and must not silently
  be serialized as intentional silence.

## Render pipeline changes

### Timeline preparation

- Add a pure timeline-preparation step that accepts `video_data` and returns
  validated ordered shots plus absolute audio events.
- Prefer `editorial_timeline` when present.
- For legacy drafts, derive visual durations from `cinematic[].duration` when
  available, otherwise from legacy audio durations; normalize `"-1"` as
  intentional silence only where the scene metadata says silence or no speech.
- Validate alignment across text, cinematic metadata, images, and audio.
  Report mismatched lengths and missing assets clearly.

### FFmpeg rendering

- Render each still/image/video shot for `visual_duration_sec`, not
  `audios[i][1]`.
- Apply camera motion across the full visual duration.
- Build the final picture track with transition overlap while maintaining a
  precise shot-start table.
- Build audio as timestamped events using measured duration and absolute start
  time. Use delay/mix filters that allow audio to continue across picture cuts.
- Mix voice, music, and effects as separate logical tracks before final mux.
- Export timeline diagnostics (shot starts/ends, audio starts/ends, extensions,
  overlaps, and missing assets) to the render log.

Remotion can consume the same normalized timeline in a later phase.

## User experience

### Defaults

Keep the create form concise. Provide a small set of project-level defaults:

- **Pacing:** Balanced / Deliberate / Fast (maps to duration and hold defaults,
  not to speech speed).
- **Target runtime:** optional; advisory for the screenplay/timeline.
- **Narrator voice:** explicit voice selection or existing default behavior.
- **Audio mix:** dialogue/narration, music, and effects levels; music ducking.
- **Transitions:** default type and duration.

### Per-shot controls

Expose detailed timing in the stages/storyboard editor, not in the initial
creation form:

- Visual duration.
- Beat type: dialogue, voiceover, silence/action, ambience, or effect.
- Audio preview and measured duration.
- Start offset and allow-cross-cut toggle for J/L-cuts.
- Hold after speech, transition out, and optional per-shot gain.

Show computed timing (for example, “5.5s picture · voiceover starts +0.6s ·
3.8s audio · 1.1s remaining hold”) so edits are understandable.

## Backward compatibility and migration

- Do not rewrite existing drafts as part of deployment.
- Create a normalized timeline in memory when rendering legacy drafts.
- Persist `editorial_timeline` when a draft is newly generated or explicitly
  healed/edited.
- Keep old `audios` tuple entries readable until all consumers migrate.
- Preserve FFmpeg's existing transition behavior as the initial default.
- Do not regenerate images when rebuilding audio or the timeline.

## Failure handling

- Missing spoken audio should be marked as a generation failure for that beat,
  while retaining already generated images and successful audio assets.
- If an audio asset cannot be probed, log the failure and block final render
  unless a known duration is supplied; do not silently substitute a short
  audio-derived shot duration.
- If timeline arrays do not align, fail validation with scene indices and
  expected/actual lengths.
- Make render retries idempotent by caching successful audio and visual
  assets; only regenerate missing or explicitly invalidated assets.

## Acceptance criteria

1. A shot with a 6-second director duration and 2-second dialogue renders for
   6 seconds, with a 4-second visual tail/hold unless another explicit beat
   changes the schedule.
2. A 7-second spoken line on a 4-second shot is not truncated or sped up; the
   timeline extends the shot or carries audio across a valid cut and reports
   the choice.
3. An explicitly authored voiceover scene receives narrator audio; it is not
   converted to silence because its speaker is null.
4. An intentional silent action beat stays silent for its authored duration.
5. A permitted L-cut continues audio over the next image without moving the
   next image's start unexpectedly.
6. A permitted J-cut begins audio before the associated image at the requested
   offset.
7. Dissolve overlap reduces picture runtime by the expected amount without
   shifting audio away from its scheduled absolute times.
8. Legacy drafts without a timeline still render, with the selected fallback
   policy visible in diagnostics.
9. Rebuilding audio/timing does not invoke image generation or upscaling.

## Decisions required before implementation

- Should target runtime be a hard constraint or a screenplay-generation hint?
- For speech longer than its shot, should the default always extend that shot,
  or first attempt an L-cut into the following shot?
- Should action shots have a generated/selected ambience bed in the first
  release, or only support ambience metadata and mixing?
- Which timeline fields are user-editable versus director-generated and
  locked by default?
- Should Remotion be updated in the same release or after the FFmpeg behavior
  is validated?

## Suggested implementation sequence

1. Fix speech classification and TTS generation for voiceover and dialogue;
   preserve intentional silence.
2. Add timeline normalization and validation with legacy fallback.
3. Change FFmpeg picture duration to use the normalized visual timeline and
   place audio independently.
4. Add diagnostics and focused renderer tests for offsets, holds, overlaps,
   long audio, and old drafts.
5. Add stage-editor timing controls and pacing/mix defaults.
6. Port the normalized timeline contract to Remotion after FFmpeg results are
   validated.
