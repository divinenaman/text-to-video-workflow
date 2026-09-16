# Specification: image_layers v2 (Advanced Depth & Parallax)

## 1. Overview
The current `image_layers` implementation is a functional MVP using a programmatic "yellow outline" row-scan heuristic. v2 transitions from these rudimentary OpenCV heuristics to **Semantic Segmentation** powered by multimodal LLMs (Gemini 2.5 Flash) combined with generative cleanup, enabling professional-grade 3D parallax and depth-compositing.

## 2. Core Improvements

### 2.1. Semantic Segmentation via Gemini 2.5 (Replaces Row-Scanning)
*   **Approach**: We abandoned the rigid `cv2` row-scanning method and SAM in favor of **Gemini 2.5 Flash's native spatial understanding**. Gemini 2.5 can natively output 2D bounding boxes and 2D probability masks for segmented objects.
*   **Workflow (`segment_image_layer` in `processor.py`)**:
    1.  Pass the raw image alongside a prompt to Gemini via our `ChatInterface`.
    2.  Prompt requests the segmentation mask for the "primary subject highlighted with a yellow outline/border".
    3.  Gemini outputs a JSON payload containing:
        *   `box_2d`: `[y0, x0, y1, x1]` coordinates normalized to 0-1000.
        *   `mask`: Base64 encoded PNG probability map.
    4.  The pipeline decodes this base64 PNG, resizes it using `PIL` to perfectly fit the `box_2d` dimensions mapped to the original image's aspect ratio.
*   **Benefit**: This eliminates the severe artifacts caused by hardcoded yellow line detection. It cleanly handles complex character silhouettes (hair, flowing clothes) and automatically fills "holes" (negative space between arms/legs).

### 2.2. Advanced Mask Processing & Compositing
*   **Thresholding**: The probability map from Gemini is binarized around the midpoint (127) using `cv2.threshold`.
*   **Edge Feathering**: We apply a **Gaussian Blur** (`k=7`) to the binary mask. This smooths the jagged edges inherent to AI masks before applying it as an Alpha channel.
*   **Alpha Composition**: The full-size, feathered numpy array is injected directly into the `RGBA` Alpha channel of the original unresized image, generating a high-quality transparent PNG.

### 2.3. Background Generative In-painting
*   **The "Ghosting" Problem**: If we only extract the foreground subject, panning the camera in Remotion reveals the subject still baked into the background layer.
*   **The Fix**: Use generative in-painting to clean the background.
*   **Implementation**:
    *   Using `gemini.generate_image` with a `subject_removal_prompt`: *"Completely remove the subject identified by the #b3b400 yellow outline and realistically reconstruct the background..."*
    *   This "Clean Background" is rendered in Remotion directly behind the extracted subject.

### 2.4. Remotion Integration Enhancements (Next Phase)
*   **Prop Expansion**: Pass `layer_depth` or `layer_z_index` to the rendering config.
*   **Depth Stacking**: Support multiple layers (e.g., `background`, `mid_ground_elements`, `foreground_subject`).
*   **Motion**: Auto-apply a slight counter-motion between the background and foreground during pans to create the "3D Depth" illusion.

## 3. Implementation Status
1.  **DONE**: `segment_image_layer` integrated into `processor.py` utilizing `BaashaChat.Img` and Gemini 2.5 Flash.
2.  **DONE**: Native mask scaling, thresholding, and `k=7` Gaussian Blur feathering.
3.  **TODO**: Replace `utils.remove_background_using_border` inside `create_image_layer` entirely with the new `segment_image_layer` pipeline.
4.  **TODO**: Wire the new alpha-layer URLs directly into the Remotion React payload for parallax rendering.
