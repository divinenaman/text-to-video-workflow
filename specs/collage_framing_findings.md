# Understanding Start-End Collage Framing

## The Problem
The native video API (Veo) had credit limitations or input constraints preventing the use of standard two-image (start frame + end frame) prompts for scene transitions.

## The Hack
We introduced a custom engine key `start_end_collage_framing` in `server.py` that concatenates the two images into a single collage, treating it as a unified reference map for the video generator.

## Evolution & Findings

1. **Side-by-Side (Literal Start/End)**: We stitched images horizontally and prompted the model to "start at the left image and end at the right image".
    *   **Result**: The model treated it as a split-screen layout and rendered both halves simultaneously.
2. **Top-Bottom Vertical Stitch**: We tried stitching them vertically and prompting to transition top-to-bottom.
    *   **Result**: Still exhibited split-screen behavior.
3. **Horizontal Stitch with "Panning" Prompt**: We returned to horizontal side-by-side but changed the semantics. We prompted the model to treat the image as a "wide panorama" and explicitly instructed the camera to *pan from left to right* over the duration of the shot.
    *   **Result**: The movement logic improved, but Veo enforces a strict 9:16 vertical video output. Because the input panorama was extremely wide (aspect ratio > 1:1), Veo padded the top and bottom with massive black bars to force the frame into 9:16.
4. **Enforcing 9:16 Aspect Ratio on Canvas**: We modified the PIL image processing step to generate a strict 9:16 black canvas. We then pasted the wide panorama into the dead center of the 9:16 frame.
    *   **Result**: Prevented Veo from blindly interpreting the raw dimensions, but the black bars are now baked into the reference image itself (to maintain the 9:16 ratio without distorting the start/end images). The generated video retains these horizontal letterboxes.

## Future Specifications for Improvement (To-Do)

To achieve a full-screen, seamless transition *without* black bars, we need to rethink how the collage is structured to naturally fit a 9:16 window while still allowing for movement.

**Potential Strategies:**

1.  **Vertical Panning (The Infinite Scroll):**
    *   **Approach:** Instead of side-by-side, stitch the images vertically (one on top of the other).
    *   **Canvas Geometry:** The final collage should match the *exact* width of a 9:16 frame but be twice as tall (e.g., 9:32 aspect ratio). Let Veo crop into the 9:16 frame.
    *   **Prompt:** Instruct the camera to start at the top 9:16 window and pan downwards to the bottom 9:16 window.
    *   **Why it might work:** Vertical video models are exceptionally good at understanding vertical scrolling/panning motions (like navigating a smartphone screen). They may naturally understand that only a portion of the tall canvas is visible at any given time.

2.  **Zoom-in / Zoom-out (Picture-in-Picture):**
    *   **Approach:** Shrink the "end" image and place it dead center *inside* the "start" image (like a painting on a wall).
    *   **Canvas Geometry:** Strict 9:16.
    *   **Prompt:** Instruct the camera to physically fly forward, scaling and zooming in continuously until the inner picture fills the entire 9:16 frame.

3.  **Cross-Dissolve via Frame Overlay:**
    *   **Approach:** If Veo inherently struggles to understand physical panning across a collage map without displaying the seam, we may need to abandon the panning prompt.
    *   **Canvas Geometry:** Overlay both images on top of each other with 50% opacity, creating a visual ghosting effect of both scenes on a strict 9:16 canvas.
    *   **Prompt:** "A smooth temporal crossfade. The video starts looking exactly like scene A, and magically transforms/morphs into scene B."

4.  **Investigate Veo `crop` and `aspect_ratio` Arguments:**
    *   Check if the underlying Google GenAI SDK allows us to explicitly tell the model how to interpret a non-baseline aspect ratio without us needing to manually inject black bars in PIL.
