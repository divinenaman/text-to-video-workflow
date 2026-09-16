# Micro-Drama Pipeline Architecture Proposal

## 1. Overview
This specification outlines the architectural changes required to transition the `baasha-service-api` from an "Explainer/Narrative Video" generator into an "Episodic Micro-Drama" generator.

The core paradigm shift is moving from a **Slide-Deck Mental Model** (Voiceover + Literal Visual) to a **Virtual Film Set Mental Model** (Dialogue + Subtextual Visuals + Spatial/Temporal Continuity).

---

## 2. Core Architectural Shifts

### A. Decoupling Audio from Visuals (Show, Don't Tell)
Currently, the LLM generates a sentence and pairs an image that literally represents it.
**New Paradigm:** The script and the camera operate independently. Visuals must provide subtext, reaction, or establish space, rather than just mirroring the dialogue.

### B. Stateful "Show Bible" (Temporal Continuity)
Currently, `get_episodic_memory` pulls previous drafts. This is insufficient for tracking physical changes.
**New Paradigm:** Introduce a `SeriesState` (Show Bible) object stored in the DB. It acts as the ultimate source of truth for character appearances, wardrobe, and location aesthetics, updating dynamically as the plot progresses (e.g., tracking an injury or outfit change).

### C. Spatial Continuity (The Virtual Set)
Currently, generating a scene with two people talking results in the background shapeshifting between cuts.
**New Paradigm:** Generate an Establishing Shot first. Use that shot as a visual anchor (via ControlNet or similar `image_reference` flags in the image engine) for all subsequent close-ups in that scene to maintain room geometry.

### D. Multi-Character & Emotional Audio
Currently, the system relies heavily on a single `voice_id` (narrator).
**New Paradigm:** The audio pipeline must support multiple concurrent `voice_ids`, emotional TTS tagging (whispering, shouting), and structural silence (cinematic "beats").

---

## 3. Data Structure Modifications

### 3.1 The "Show Bible" Object (`SeriesState`)
A new database table or JSON blob attached to the parent `Idea` model (when `is_series = True`).

```json
{
  "series_id": "uuid",
  "locations": {
    "johns_kitchen": "Mid-century modern kitchen, green subway tile, dimly lit. [Base Image Reference URL]"
  },
  "characters": {
    "John": {
      "base_prompt": "35yo man, sharp jawline, stubble, hazel eyes",
      "voice_id": "elevenlabs_john_v1",
      "current_state": {
        "wardrobe": "wrinkled white dress shirt",
        "physical_status": "bruise on left cheekbone (since ep 2)",
        "emotional_baseline": "paranoid"
      }
    }
  }
}
```

### 3.2 The Screenplay JSON Structure (Replaces `split_text_into_sentences`)
The LLM output for a scene must move from a flat array to a rich, cinematic script structure.

```json
{
  "scene_number": 1,
  "location_ref": "johns_kitchen",
  "shots": [
    {
      "shot_id": 1,
      "camera_angle": "ESTABLISHING WIDE SHOT",
      "visual_action": "Rain beats against the window of the dimly lit kitchen.",
      "image_prompt": "...", // Injects location_ref data
      "audio": {
        "type": "sfx",
        "description": "Heavy rain, distant thunder",
        "duration_sec": 3.0
      }
    },
    {
      "shot_id": 2,
      "camera_angle": "MACRO CLOSE UP",
      "visual_action": "John's hands gripping a coffee mug so hard his knuckles are white.",
      "image_prompt": "...", // Injects John's current_state
      "anchor_to_shot_id": 1, // Tells image engine to use Shot 1 as background reference
      "audio": {
        "type": "dialogue",
        "character": "John",
        "text": "I told you, I didn't see anything.",
        "tts_emotion": "suppressed rage, whispering"
      }
    },
    {
      "shot_id": 3,
      "camera_angle": "REACTION SHOT, MEDIUM CROWD",
      "visual_action": "Mary standing in the doorway, arms crossed, skeptical.",
      "image_prompt": "...",
      "anchor_to_shot_id": 1,
      "audio": {
        "type": "silence", // The "Cinematic Beat"
        "duration_sec": 2.0
      }
    }
  ]
}
```

---

## 4. Pipeline Execution Updates (`processor.py`)

1. **Pre-Flight (Context Gathering):**
   - Fetch the `SeriesState` (Show Bible).
   - Inject the current state of characters and locations into the Screenplay Prompt.
2. **Screenplay Generation:**
   - Execute the new LLM prompt to generate the structured JSON (as seen in 3.2).
3. **Asset Generation (Phased Approach):**
   - **Phase 1 (Establishing):** Generate all `ESTABLISHING` shots first.
   - **Phase 2 (Anchored):** Generate close-ups/reaction shots, passing the relevant Establishing Shot URL to the image engine API (e.g., `init_image` or `controlnet_ref`).
4. **Audio & Timeline Assembly:**
   - Map `character` names to their assigned `voice_id` from the Show Bible.
   - Generate TTS audio.
   - Generate "Silence" audio files for cinematic beats.
   - Assemble the video config timeline using exact durations (Shot duration = Audio duration).

---

## 5. New LLM Prompt Design (Concept)

**Prompt Name:** `micro-drama-screenplay`

**System Instructions:**
"You are a prestige TV Screenwriter and Cinematographer. Your goal is to write a compelling micro-drama scene.
1. **Show, Don't Tell:** Never make the visual a literal translation of the dialogue. Use visual subtext. If a character is angry but speaking calmly, show their fist clenching.
2. **Spatial Continuity:** Begin scenes with an ESTABLISHING SHOT. Follow with specific camera angles (e.g., OVER THE SHOULDER, CLOSE UP).
3. **Pacing:** Drama requires silence. Use the 'silence' audio type to create tension (beats) before or after important dialogue.
4. **State Adherence:** You will be provided a 'Show Bible'. You MUST respect the current wardrobe and physical status of the characters in your visual prompts."
