# Future Research and Collaboration Avenues

## 1. Current State: The Pursuit of Extreme Realism
We have successfully transitioned the Baasha pipeline from generating hyper-stylized "CGI/Cinematic" visuals to an **Ultra-Realistic Documentary/UGC (User-Generated Content)** aesthetic.

### Key Innovations:
1. **Era-Adaptation Prompts:** The system dynamically adjusts its photographic heuristics based on the era.
   - *Modern:* Candids, iPhone 14 footage, harsh fluorescent lighting.
   - *Historical:* Gritty realism, authentic materials, natural ambient lighting (fire/sunlight), strictly no modern anachronisms.
2. **Visual Web-RAG (Retrieval-Augmented Generation):** The `processor.py` and `image_search_agent.py` pipelines work together to fetch real-world search results, scrape images, read them using a Vision LLM, and inject factual constraints into the global context before generating the diffusion prompts.
3. **Moodboard Logic & Native Grids:** The new `/api/moodboard` endpoint allows for rapid stylistic exploration by brainstorming multiple UGC-realistic art styles. It leverages `create_image_grid` for automatic 2x2 panel generation and vision-based splitting, ensuring visual alignment across complex stylistic references.

---

## 2. Collaboration Needs

To sustain and improve upon this high-fidelity pipeline, collaboration across multiple skill sets is required:

### A. Prompt Engineers & Generative Artists
* **Objective:** Expand the `realistic_image_system_prompt.md` into a comprehensive matrix of aesthetics (e.g., distinguishing between 1920s Kodak film, 1990s VHS camcorders, and 2024 smartphone cameras).
* **Task:** Continuously A/B test system prompts against new Image/Video models (like Flux 1.1, Midjourney v6, or Veo/Sora).

### B. Subject Matter Experts & Historians
* **Objective:** Validate the visual accuracy of historical outputs.
* **Task:** Review generated video outputs for historical inaccuracies (e.g., incorrect armor in Ancient Rome, modern hairstyles in the 1800s). Provide high-quality ground-truth descriptions that can be fed into the RAG context.

### C. QA Testers / Data Labelers
* **Objective:** Grade the "realism" and "temporal consistency" of generated videos.
* **Task:** Rate the transition fluency in the image-grid crop pipeline. Identify instances where the AI generated "hallucinations" (e.g., extra fingers, text generation artifacts).

---

## 3. Future Research Avenues

### A. Advanced Visual RAG
* **Currently:** The RAG system uses DuckDuckGo to grab top articles, screenshot them, and summarize them.
* **Future Research:**
  1. *Vectorized Visual Lore Textbooks:* Pre-vectorize massive datasets of historical facts, blueprints, and period-accurate clothing styles. When generating a Roman story, locally fetch chunks rather than relying on live web searches.
  2. *Reference Image Injection (ControlNet):* Instead of just summarizing search results into text context, automatically identify historically accurate images online, crop them, and pass them as *ControlNet or Image-to-Image reference* directly into the image generator.

### B. Temporal Consistency & Video Morphing
* **Currently:** Sliced images from a high-res grid are upscaled and sent to video models (like Gemini) with prompts dictating "natural cinematic motion".
* **Future Research:** How do we transition through complex historical scenes without the "AI morphing" effect? Research into optical flow constraints and multi-frame consistency models is critical.

### C. Audio Realism & Spatial SFX
* **Currently:** Basic TTS and keyword-based SFX mapping (`phrase-sounds` JSON prompt).
* **Future Research:** Sync the auditory landscape exactly with the drafted environment. If the image prompt dictates "harsh fluorescent lighting in a small concrete room", the TTS voice and background SFX should automatically apply an impulse-response (IR) reverb matching a small concrete room.

### D. Automated "Realism Scoring" Agent
* **Future Research:** Introduce a secondary Vision-LLM step that evaluates the final generated images *before* rendering the video. The judge compares the output to the "Realism Spec" and if it detects CGI gloss, perfect symmetrical faces, or Hollywood lighting, it automatically rejects the image and re-triggers the prompt with harsher negative constraints.
