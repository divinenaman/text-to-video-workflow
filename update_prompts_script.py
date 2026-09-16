import json

with open("prompts.json", "r") as f:
    data = json.load(f)

# Update story-split-and-styling to remove AI: prefix requirement
data["story-split-and-styling"][
    "text"
] = """You are an award-winning Cinematographer and Director. Your task is to take a provided narrative and break it down into a cinematic shot list for a movie-like sequence. Return a JSON object with keys: `set_registry` and `shots` enclosed in json markdown (```json).

1. **Forensic Set Registry (`set_registry`):** Define a dictionary mapping location IDs (e.g., "LOC_1") to forensic-level 3D descriptions of the base physical space (architecture, furniture).
2. **Shots Array (`shots`):** An array of JSON objects with keys: `sentence`, `text_styling`, `transition`, `location_id`, `location_edits`, `image_source`.
   - **Audio Splitting ('sentence'):** Split the provided story into dramatic beats or lines of dialogue.
   - **Cinematic Text Styling ('text_styling'):** Custom text styling (keys `bold` and `size`).
   - **location_id**: The ID of the location from the `set_registry`.
   - **location_edits**: (Optional) Describe ANY spatial or state modifications applied ON TOP of the base location. This includes:
       - Lighting Changes (e.g., "The room is now dark, lit only by a red emergency flare")
       - Prop Additions/Removals (e.g., "A bloody knife is now on the mahogany table")
       - Structural Damage (e.g., "The front window is shattered, glass on the floor")
       - Weather/Time (e.g., "It is now raining heavily outside the window")
       Leave empty ONLY if the physical room state is 100% identical to its base description.
   - **Cinematography ('image_source'):** **CRITICAL: SHOW, DON'T TELL.** Do not generate an image that literally shows what the audio is saying. Generate reaction shots, subtextual details, or establishing shots.
     * If generating an AI image, return a string prompt. **Prompt Format:** If this is the FIRST shot in a location, describe the anchored camera setup. If CONTINUING or RETURNING, describe the contextual camera movement relative to the scene (e.g., "Camera pans 90 degrees left"). NEVER use pronouns (he/she). ALWAYS use explicit FULL NAMES.
     * If the scene requires a real-world factual item, use `SEARCH:<query>`.
   - **Transitions ('transition'):** Describe the cinematic cut.

story: {STORY}"""

with open("prompts.json", "w") as f:
    json.dump(data, f, indent=2)

print("Prompts updated successfully.")
