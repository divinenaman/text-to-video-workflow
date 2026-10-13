# Collaboration & Development Standards

## 1. Modular Logic Pattern
To maintain a clean and collaborative `server.py`, all core generation logic must be extracted into `processor.py`.
- **Endpoint Responsibility:** `server.py` handles argument parsing, basic validation, and HTTP response mapping.
- **Generator Responsibility:** `processor.py` handles LLM interactions, asset generation (Images, Audio, Video), and business logic.

## 2. Grounding Context Pattern
Any new feature requiring internet-grounded accuracy (like Moodboard, Story Gen, or Character Research) must follow the **Grounded Context Pattern**:
1.  Use `processor.build_and_set_script_context(chatbot, text)` to trigger a Google Search grounding loop.
2.  All subsequent LLM calls in that session must rely on the pinned `global_ctx` rather than passing large context strings repeatedly in prompts.

## 3. Visual Identity (UGC Realism)
All image-related features must strictly adhere to the Documentary/UGC aesthetic.
- **Negative Constraints:** Avoid "CGI", "Cinematic", "Epic", "Artstation", "Hyperrealistic" (which ironically triggers AI-looking polish).
- **Positive Heuristics:** Use "Candid shot", "Smartphone grain", "Natural ambient lighting", "Unposed", "Documentary style".
- **Source of Truth:** Refer to `realistic_image_system_prompt.md` for the latest prompting tokens.
- **4-Axis Differentiation Framework:** For multi-style generation (like Moodboards), prompts must enforce contrast across:
    1. **Color Science** (e.g., desaturated grit vs warm film).
    2. **Optics** (e.g., wide-POV vs macro-telephoto).
    3. **Texture** (e.g., weathered/dusty vs clinical/sleek).
    4. **Narrative Mood** (e.g., documentary fly-on-the-wall vs subjective 1st-person).
- **Era-Accuracy Anchor:** All historical topics must explicitly lock the era/place in EVERY individual panel description to prevent "modern adaptation" bleed.

## 4. One-Shot Grid Generation
For multi-image generation (Moodboards, Storyboards), leverage `processor.create_image_grid`.
- **Consistency:** Generating 4 images in one 2x2 grid ensures significantly higher stylistic and color consistency compared to 4 individual calls.
- **Detection:** The system uses vision-based bounding box detection to slice these grids automatically.

## 5. Testing Standards
- **Contract Tests:** Add a test case in `test_api.py` for every new endpoint.
- **Mocking:** Since many calls are expensive (AI GPUs), use the `TESTING=True` environment variable to bypass heavy generation where appropriate in local development.
