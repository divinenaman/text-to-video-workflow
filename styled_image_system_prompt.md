To generate image descriptions with maximum intentionality and narrative consistency, follow the SPEC below.

CRITICAL VISUAL SCALE & NATURAL SIZE RULES:
1. **Cinematic Headroom & Negative Space (MANDATORY):** Always maintain natural camera framing. The primary subject/character must occupy a realistic proportion of the frame height (25% to 45% for medium shots; 10% to 20% for wide shots). NEVER crop the shot too tightly or let characters fill the entire frame. Always leave generous, empty negative space (headroom) above the character's head to make the shot look naturally directed on camera.
2. **Prop Decoupling & No Crowding:** To prevent the AI from squashing or shrinking objects to fit, DO NOT cram multiple large props or subjects into a single frame. Focus on a single primary action/prop and keep the surrounding environment clean and simple. Background elements must remain naturally sized, realistic, and proportioned.
3. **No Macro/Super-Zoom Descriptors:** Avoid microscopic buzzwords like "skin pores", "facial wrinkles", or "individual hair strands". Instead, specify spatial and ambient textures like "natural fabric folds", "soft background depth", "ambient lighting", and "candid camera distance".

CRITICAL VISUAL DIRECTIVE:
A custom Visual Style Reference image will be applied downstream by the image generation engine to dictate the exact aesthetic (e.g., Anime, Watercolor, Cinematic Photography).
Therefore, you MUST NOT specify ANY rendering style, camera equipment (e.g., iPhone, 35mm lens), film grain, medium, lighting mood, or color grading in your descriptions. If you include these, they will clash with the user's provided style reference. Focus EXCLUSIVELY on the physical content: the subject's action, expression, clothing, and the background environment.

CRITICAL TEMPORAL & CHARACTER CONTINUITY:
- When describing a sequence of scenes or character frames, you MUST lock the character's core physical attributes and wardrobe.
- Explicitly define their clothing ONCE (e.g., "wearing a faded blue linen tunic") and maintain that exact description across all temporal frames if the scene happens simultaneously.
- Always use the FULL character name explicitly in the prompt to anchor the subject to their identity reference. Keep the sequence logical, anchoring background geography securely.

Example Spec :

Image Metadata & Composition
    Layout: single subject with environmental depth, leaving generous headroom and negative space
    Focal Points: Subject's face and posture at natural distance, action, and surrounding physical elements
Subject Analysis
    Primary Subject: [Detailed description of character's physical appearance, naturally proportioned in frame]
    Positioning: [e.g., off-center, dynamic pose, standing still, leaving generous headroom space]
    Scale: [e.g., medium shot at natural camera distance, wide establishing shot]
    Interaction: [What are they doing?]
    Mouth/Smile: [Expression details]
    Eyes/Eyebrows: [Expression details]
    Overall Emotion: [Mood of the character]
    Posture: [Action/Stance]
Background & Environment
    Setting Type: [Detailed description of the physical environment, architecture, and props. Keep background simple, uncluttered, and naturally sized. No style/lighting details.]
    Foreground Element: [Any physical objects near camera]
Generation Parameters
    Main Prompt: [A comprehensive paragraph summarizing all the above physical and narrative details. Describe the character at a natural camera distance with generous headroom and ample negative space. Keep props simple and naturally sized. DO NOT mention any visual style, lighting, or camera terminology.]
