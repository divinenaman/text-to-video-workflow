# Smooth Collaboration Roadmap

This document serves as the tactical roadmap for Baasha development, tracking recent momentum and outlining future technical upgrades.

## 1. Recent Changes & Fixes
- **Moodboard API Implementation:** Created `POST /api/moodboard` to enable high-speed stylistic brainstorming.
- **Modular Refactoring:** Extracted heavy generation logic from `server.py` into `processor.py` to simplify API maintenance.
- **Restored Realism Guide:** Fixed a critical bypass in `processor.py` that was disabling the UGC/Documentary style guide.
- **Spec Format Enforcement:** Prompts now strictly require the "Example Spec" format (Image Metadata, Color & Lighting, etc.) for all generated descriptions.
- **Parallel Grid Creation:** Ported `generate_moodboard` to `ThreadPoolExecutor` for concurrent style generation (~60-70% faster).
- **Premium Moodboard Studio:** Built a standalone, dashboard-style frontend with real-time progress steps and side-by-side comparison tables.
- **Fixed Style Bias:** Resolved the issue where historical topics were leaning towards "modern adaptations" by implementing the Era-Accuracy Anchor in the Art Director prompt.

## 2. Technical Updates & Upgrades
- **Grounded Context (Gemini Search):** Now natively integrated into Moodboard and Story generation. The chatbot performs live internet research to enrich the prompt's factual grounding.
- **One-Shot Grid Slicing:** Multi-image requests use the 2x2 grid generation pattern to ensure visual continuity across frames, with automated vision-based slicing for individual assets.

## 3. Future Upgrades (High Priority)
- **Vision-Based Slicing Implementation:** Restore automated 2x2 grid splitting (currently skipped for speed) to enable high-res individual panel downloads in the dashboard.
- **Moodboard-to-Draft Integration:** Allow users to "Lock" a style in the Moodboard Studio and pass it as the `Visual North Star` directly into the `Story Draft` pipeline.
- **Vectorized Visual Lore:** Pre-vectorize historical and cultural data (e.g., Roman architecture, Indian textiles) to replace live web-RAG with faster, curated local lookups.

## 4. Future Good-to-Haves (Wishlist)
- **Automated "Realism Judge":** A secondary agent that critiques the AI's output against the realism spec and handles automatic regenerations if CGI-gloss is detected.
- **Real-time Collaboration Buffers:** Web-socket based updates for the Moodboard page so multiple users can watch a grid being "thought out" in real-time.
- **Dynamic Prompt A/B Tester:** A dashboard to test how `realistic_image_system_prompt.md` changes affect actual output across various models.

---
*Refer to [collaboration_standards.md](file:///home/naman/dev/baasha/baasha-service-api/specs/collaboration_standards.md) for the "Rules of Engagement" when contributing to this repository.*
