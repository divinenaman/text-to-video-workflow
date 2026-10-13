# Character Bible & Visual Consistency Specification

## 1. Overview
The **Character Bible** system is a specialized pipeline designed to extract, visualize, and anchor character identities across the Baasha generation lifecycle. It ensures that characters maintain a consistent physical appearance (Visual DNA) and wardrobe across multiple scenes and episodes, even when using disparate reference images or complex style moodboards.

## 2. Character Extraction Pipeline (`POST /api/character_bible`)

### 2.1 Extraction Process
1.  **Deep Casting (`find-story-characters`):**
    - Parses the story/script to identify all significant entities.
    - Categorizes them as `fictional: true` (original characters) or `fictional: false` (historical figures/celebrities).
    - Generates a "Model Sheet" description for each, including ethnicity, facial architecture, and status-appropriate attire.
2.  **Parallel Real-World Lookalike Search:**
    - For non-fictional entities, the system triggers parallel Google Image Searches using isolated `ChatInterface` instances to avoid context corruption.
    - Resulting URLs are used as the primary "Character Reference" for identity anchoring.
3.  **Visual Bible Generation:**
    - Generates a high-fidelity reference portrait for each character.
    - **Face-Swap Logic:** Explicitly commands the image generator to "Extract the EXACT physical face/identity from the Character Reference" while "Aggressively applying the lighting/texture from the Style Reference."

## 3. Visual Consistency & Anchor Protocols

### 3.1 Single Frame Constraint
To prevent "grid-in-grid" artifacts when using moodboards as style references, all character generation prompts are appended with a strict anti-grid constraint:
> "SINGLE FRAME ONLY. NO GRIDS. CRITICAL: Extract the EXACT physical face/identity from the Character Reference... NEVER replicate the grid layout of the Style Reference."

### 3.2 Reference Multiplexing & Filtering
During the **One-Shot Image Grid** generation (where 8 panels are generated at once), the system implements **Name-Based Reference Filtering**:
- **Problem:** Passing 5 different character references to an 8-panel grid prompt causes identity bleeding and composition chaos.
- **Solution:** The `processor.create_image_grid` function scans the specific panel prompts for character names. It only passes a Character Reference to the image engine if that specific character's name is detected in the prompt text.

### 3.3 Temporal Coherence & Wardrobe Locking
- **Realistic Image Guide (`realistic_image_system_prompt.md`):** Updated with a mandatory "Temporal Continuity" section.
- **Wardrobe Locking:** Prompt Architects (`story-split-and-styling`) are instructed to define clothing explicitly once (e.g., "wearing a faded blue linen shirt") and maintain that exact string across all subsequent panels.
- **Pronoun Ban:** Script generation models are strictly forbidden from using pronouns (he/she/they). They must use explicit **FULL CHARACTER NAMES** (e.g., "Marcus Aurelius") to ensure the reference filtering and anchoring logic triggers correctly.

## 4. Technical Implementation Details

### 4.1 Parallelization Architecture
The `generate_character_bible` function in `processor.py` uses `ThreadPoolExecutor` with a pool size of 10 to handle lookalike searches. Each thread manages its own `thread_chatbot` instance to ensure thread-safety and prevent race conditions in Gemini's conversational memory.

### 4.2 Endpoint Data Structure
The character bible is stored in the `Draft` model's `character_ref` field as a JSON array of objects:
```json
[
  {
    "name": "General Maximus",
    "description": "A battle-hardened man with grey-streaked hair...",
    "url": "https://storage.baasha.ai/refs/maximus.png",
    "search_url": "https://google.com/search?q=russell+crowe+gladiator"
  }
]
```
