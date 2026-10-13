# Baasha MCP Design Decisions & Architecture

This document catalogs the core design philosophies and technical decisions behind the Baasha Model Context Protocol (MCP) server. By documenting these decisions, we ensure that all future improvements, tool additions, and AI collaborative efforts operate cohesively under the same Mental Model.

## 1. The "Creative Director" Persona
The MCP is not merely a pipeline wrapper; it is built to actively elevate the agent to the role of **Creative Director**.
*   **Design Decision**: Tools and docstrings explicitly nudge the agent to exercise creative judgment, critique assets, and iterate, rather than just executing a linear script.
*   **Implementation**: Tools like `get_production_spec` and `get_agent_manual` feed a structured "Mental Model" straight into the agent’s context.

## 2. Research as Protocol Stage 0
A frequent failure of agentic video generation is hallucinated contexts.
*   **Design Decision**: Grounded research must precede generative output.
*   **Implementation**: We exposed `search_web()`—which wraps the engine's Gemini Google Search tool. The agent is directed to use this tool to fact-check histories, verify cultural attire, and understand scenic lighting *before* starting any drafting.

## 3. Top-Down vs. Bottom-Up Steering
Generative APIs usually force one paradigm (either "give me a prompt and I generate" or "give me exactly what to render"). The MCP supports both.
*   **Design Decision**: `content_type` acts as the directional flag.
*   **Implementation**:
    *   **Top-Down (`content_type="reel"`)**: The agent provides fully researched, locked-in text. The pipeline treats the text as exactly what must be narrated.
    *   **Bottom-Up (`content_type="story"`)**: The agent passes in research context, rough plot points, or themes. The backend generates a polished, cinematic script utilizing the context constraint.

## 4. Visual Continuity via Moodboards
Text-to-Video architectures often drift stylistically from scene to scene.
*   **Design Decision**: Aesthetic choices should be made and validated holistically before the heavy generation begins.
*   **Implementation**: The `generate_moodboard()` tool allows the agent to generate multiple "Style Grids" cheaply. A successful grid yields a `grid_url`, which is subsequently passed as `moodboard_reference` into `start_draft_pipeline` or `refine_draft` to lock the visual seed.

## 5. Granular Aesthetic Controls
We removed messy, legacy style prompts that often conflict with inner AI logic.
*   **Design Decision**: Aesthetics must be passed structurally.
*   **Implementation**: The `image_styles` JSON dictionary was strictly defined, categorizing visual inputs into predictable keys: `themes`, `emotions`, `camera_angles`, `camera_lens`, `lighting`, and `color_palettes`. This forces the agent to direct shot semantics professionally.

## 6. The Stateful Patch Workflow
Generating a whole video recursively is computationally wasteful and practically useless if only one scene was hallucinated.
*   **Design Decision**: Edits must be index-based and surgical.
*   **Implementation**: The `refine_draft` tool supports `edit_story_sentence` (swapping script lines via index) and `regen_images` (re-rendering specific scenes). The agent polls output using `get_draft`, isolates the failing artifact, and patches only what's required.

## 7. Mandatory Strict Versioning
Generative iteration loses value if you cannot revert your context.
*   **Design Decision**: The server refuses stateful tool-calls without explicit version tracking.
*   **Implementation**: `idea_id` acts as the project wrapper, but all mutating pipeline tools strictly require a `version_id`. Tools output a `composite_id` (`{uuid}.{version}`) so agents explicitly track branches of work natively.
