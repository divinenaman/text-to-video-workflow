# Director's Override Specification Guide

This document serves as a standard operating procedure (SOP) for translating a raw creative reference document (like a visual bible, a director's moodboard, or an aesthetic manifesto) into a functional `director_cut.json` override file for the Baasha cinematic pipeline.

## 1. Understanding the Pipeline Architecture
Before writing the override, you must understand that the override JSON injects custom prompt instructions into three distinct AI agents:

1.  **`screenplay`**: The Narrative Agent. It breaks down user input into `set_registry` (3D spaces) and `shots` (camera angles, dialogue, action).
2.  **`character`**: The Casting Agent. It reads the story and outputs character visual profiles, voice descriptions, and real-world search queries.
3.  **`grid`**: The Storyboard Agent. It takes the character images and story shots and generates the visual storyboard panels.

---

## 2. Deconstructing the Reference Document
When you receive a reference document (e.g., "Make it look like a 1990s Anime"), break it down into the following operational categories:

### A. Narrative & Pacing Rules (For `screenplay`)
*   **Pacing:** Are we doing fast cuts or slow burns? (e.g., *Requires deliberate silent action beats and micro-expressions.*)
*   **Tone:** Is the dialogue snappy, raw, or poetic? (e.g., *Grounded, serious, emotionally raw dialogue.*)

### B. Visual Identity & Mechanics (For `character`)
*   **Fidelity Logic:** How do we handle real-world people vs. fictional ones? (e.g., *If real, preserve exact facial architecture above stylization.*)
*   **Costume/Props:** Does the era demand specific materials? (e.g., *1990s era-appropriate clothing.*)

### C. Aesthetic & Rendering Directives (For `grid` & `character`)
*   **Lighting & Textures:** Soft vs Hard? (e.g., *Flat cel shading, hard-edged shadow separation, muted dark grays, no glossy rendering.*)
*   **Camera Language:** Static vs dynamic? (e.g., *Maintain perfect architectural geometry.*)

### D. Negative Constraints (Crucial)
*   What are the hallmarks of failure for this style? (e.g., *Avoid: cute anime, exaggerated proportions, 3D CGI, modern gradients.*)

---

## 3. Drafting the Override JSON: Step-by-Step

### Stage 1: The `screenplay` Override
Your goal here is to constrain the LLM from acting like a basic text generator and force it to act like a Cinematographer.

*   **Pacing Spec:** Explicitly tell the LLM to insert "silent shots" or "reaction shots". Left to its own devices, an LLM will just write non-stop dialogue.
*   **Constraint Injection:** Add the `Strict Dialogue Constancy` (one speaker per shot) and `Forensic Set Design` rules to force structured JSON output.
*   **The Continuity vs. Override Rule:** LLMs love spatial continuity and will ignore user-requested flashbacks to avoid creating new locations. **Always include a rule stating:** *"Maintain continuous space generally, BUT you MUST strictly honor the user's explicit story beats/flashbacks by creating new scenes."*
*   **Metadata Locking:** Force the LLM to use bracketed metadata for physical state: `[Name] (Position, Action, Emotion)`. This prevents characters from magically teleporting between cuts.

### Stage 2: The `character` Override
Your goal here is to ensure the image generator receives the exact right prompts to cast the actors correctly without "hallucinating" their faces.

*   **The Fictional vs. Real-World Toggle:** This is the most important mechanic.
    *   **Real People (`fictional: false`):** Instruct the prompt to *OMIT* facial descriptions. We rely entirely on the Google Search image for their face. However, *DO* instruct it to explicitly describe their **Costume and Clothing** so the image generator knows how to dress them.
    *   **Fictional (`fictional: true`):** Instruct it to write a deep, multi-sentence physical description.
*   **Search Query Specificity:** Tell the LLM not to use generic search terms (like "2020s film look"). Force it to combine the actor's identity with the specific emotional state of the scene (e.g., *"Actor Suriya intense angry look"*).
*   **The Single Frame Constraint:** Always append: `"SINGLE FRAME ONLY. NO GRIDS."` to prevent the image model from accidentally generating a comic-book grid when we only want a single character portrait.

### Stage 3: The `grid` Override
Your goal here is to dictate the final render style of the storyboard frames.

*   **Template Preservation:** Instruct the model to strictly respect the input grid layout (borders, margins, panel count).
*   **Core Visual Style:** Dump your heavily researched aesthetic terms here (e.g., *Authentic late-1980s cel-animation, flat shading, organic linework, analog film grain*).
*   **Anti-Clone Protocol:** Image models tend to copy-paste faces in crowds. Explicitly write: *"For crowds, draw distinct individuals... absolutely no copy-pasted identical clones."*

---

## 4. Common Pitfalls to Watch Out For

1.  **The "Beautification" Trap:** Most base image models naturally skew towards making subjects look "attractive" or "modern." If your reference requires grit, age, or a specific vintage look, your **Negative Constraints** must be aggressive (e.g., *NO glossy skin, NO beautified faces, NO modern 3D rendering*).
2.  **The "Lazy Search" Trap:** If the LLM doesn't have an exact year or movie, it will output a lazy search query like *"Actor Name look"*. The override must explicitly threaten the LLM to derive context from the scene (e.g., *"Actor Name rugged bearded crying"*).
3.  **The Continuity Override Trap:** As noted, if a user writes "he remembers his childhood," the LLM will just write a shot of the actor staring blankly, rather than cutting to a childhood scene. The screenplay prompt must forcefully prioritize sudden narrative cuts over geographic continuity.
