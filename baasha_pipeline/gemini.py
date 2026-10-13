import logging
import os
import google.generativeai as google_genai
import requests
from .configs import app_config
from . import errors, object_storage, utils
from concurrent.futures import ThreadPoolExecutor
from typing import Optional
from uuid import uuid4
import time
import google.genai as google_genai_video_client
from google.genai import types as google_genai_video_types
import base64
from PIL import Image
import io
import wave


@errors.propogate_ctx_errors
def generate_image(
    prompt,
    refs=None,
    width=None,
    height=None,
    aspect_ratio="9:16",
    image_resolution="0.5K",
    use_filesystem=False,
):

    api_key = (
        app_config.get().get("auth").get("google_genai_image_key")
        or app_config.get().get("auth").get("google_genai_key")[0]
    )
    client = google_genai_video_client.Client(api_key=api_key)

    contents = [prompt]

    if refs:
        try:
            if isinstance(refs, str) or isinstance(refs, dict):
                refs = [refs]

            for ref in refs:
                ref_url = ref.get("url") if isinstance(ref, dict) else ref
                ref_type = (
                    ref.get("type", "subject") if isinstance(ref, dict) else "subject"
                )

                ref_bytes = None
                if ref_url and "http" in ref_url:
                    img_bytes_response = requests.get(ref_url, timeout=30)
                    img_bytes_response.raise_for_status()
                    stream = io.BytesIO(img_bytes_response.content)
                    ref_bytes = Image.open(stream)
                elif ref_url:
                    ref_bytes = Image.open(ref_url)

                if ref_bytes:
                    desp = None
                    name = None
                    if isinstance(ref, dict):
                        name = ref.get("name")

                    if ref_type == "style":
                        desp = "\n[Style/Aesthetic Reference]:"
                    elif ref_type == "scene":
                        desp = "\n[Scene Reference]:"
                    else:
                        desp = "\n[Character Reference]:"

                    if desp and name:
                        desp += f"\n{name}"

                    if desp:
                        contents.append(desp)
                    contents.append(ref_bytes)

                logging.info(f"Reference image loaded ({ref_type}).")
        except Exception as e:
            logging.error(f"Failed to fetch reference image: {e}")
            raise

    response = client.models.generate_content(
        model="gemini-3.1-flash-image-preview",
        contents=contents,
        config=google_genai_video_types.GenerateContentConfig(
            image_config=google_genai_video_types.ImageConfig(
                aspect_ratio=aspect_ratio, image_size=image_resolution
            )
        ),
    )

    for part in response.parts:
        if part.inline_data is not None and part.inline_data.mime_type.startswith(
            "image"
        ):
            if use_filesystem:
                with open("img.png", "wb") as f:
                    f.write(part.inline_data.data)
                return "img.png"
            else:
                public_url = object_storage.upload_data(
                    object_storage.ASSETS_IMG_BUCKET,
                    part.inline_data.data,
                    f"{uuid4()}_gemini_images.png",
                    object_storage.ACL_PUBLIC,
                )
                logging.info(f"gemini image url -> {public_url}")
                return public_url

    return None


def mk_img_dic_from_url(ref):
    img_bytes_response = requests.get(ref, timeout=30)
    img_bytes_response.raise_for_status()
    ref_bytes = img_bytes_response.content

    return google_genai_video_types.ImageDict(
        image_bytes=ref_bytes, mime_type="image/png"
    )


@errors.propogate_ctx_errors
def generate_video(
    prompt,
    ref=None,
    ref_bytes=None,
    last_ref=None,
    duration_seconds=4,
    aspect_ratio="9:16",
):

    api_key = app_config.get().get("auth").get("google_genai_key")[0]
    client = google_genai_video_client.Client(api_key=api_key)

    if ref_bytes or ref:
        try:
            if ref:
                ref_bytes = mk_img_dic_from_url(ref)

            else:
                ref_bytes = google_genai_video_types.ImageDict(
                    image_bytes=ref_bytes, mime_type="image/png"
                )

            if last_ref:
                last_ref = mk_img_dic_from_url(last_ref)

            logging.info("Reference image loaded.")
        except Exception as e:
            logging.error(f"Failed to fetch reference image: {e}")
            raise

    # Uses the "new" types alias
    video_config = google_genai_video_types.GenerateVideosConfig(
        duration_seconds=duration_seconds, aspect_ratio=aspect_ratio
    )

    if last_ref:
        video_config.last_frame = last_ref

    logging.info(f"gemini video final prompt: {prompt}")

    try:
        # Uses the "new" client alias
        operation_name = client.models.generate_videos(
            model="veo-3.1-fast-generate-preview",
            prompt=prompt,
            config=video_config,
            image=ref_bytes,
        )

        logging.info(f"Video operation started: {operation_name}")

        operation = client.operations.get(operation_name)

        while not operation.done:
            logging.info(f"Waiting for video generation...")
            time.sleep(10)
            operation = client.operations.get(operation_name)

        logging.info("Video generation operation complete.")

        logging.info(f"Full operation object: {operation}")

        if operation.error:
            logging.error(f"Video generation failed: {operation.error}")
            return None

        if operation.response and operation.response.generated_videos:
            video = operation.response.generated_videos[0]
            file_name = f"{uuid4()}_veo_video.mp4"
            client.files.download(file=video.video)
            video.video.save(file_name)

            # video_uri = operation.response.generated_videos[0].video.uri
            logging.info(f"Video generated, fetching from file: {file_name}")

            # 2. Download the video file from the URI
            # video_response = requests.get(video_uri, timeout=30)
            # video_response.raise_for_status()

            # 3. Get the raw bytes from the download
            # video_bytes = video_response.content
            # logging.info(f"Video bytes downloaded, size: {len(video_bytes)}")

            video_bytes = None
            with open(file_name, "rb") as f:
                video_bytes = f.read()

            public_url = object_storage.upload_data(
                object_storage.ASSETS_IMG_BUCKET,  # Consider a VIDEO_BUCKET
                video_bytes,
                f"{uuid4()}_gemini_video.mp4",
                object_storage.ACL_PUBLIC,
            )
            logging.info(f"Gemini video url -> {public_url}")
            return public_url
        else:
            logging.error("Operation finished but no video data was found.")
            return None

    except Exception as e:
        logging.error(f"An error occurred during video generation: {e}")
        pass

    return None


@errors.propogate_ctx_errors
def gemini_search(query: str):
    api_key = app_config.get().get("auth").get("google_genai_key")[0]
    client = google_genai_video_client.Client(api_key=api_key)

    grounding_tool = google_genai_video_types.Tool(
        google_search=google_genai_video_types.GoogleSearch()
    )

    config = google_genai_video_types.GenerateContentConfig(tools=[grounding_tool])

    response = client.models.generate_content(
        model="gemini-3-flash-preview",
        contents=query,
        config=config,
    )

    return response.text


@errors.log_ctx_errors
def generate_images(
    prompts: list[str],
    refs: Optional[list[Optional[str]]] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    aspect_ratio: str = "9:16",
    image_resolution="0.5K",
):
    results = []
    errors = []

    if not refs:
        refs = [None] * len(prompts)

    with ThreadPoolExecutor(max_workers=1) as executor:
        outputs = list(
            executor.map(
                generate_image,
                prompts,
                refs,
                [width] * len(prompts),
                [height] * len(prompts),
                [aspect_ratio] * len(prompts),
                [image_resolution] * len(prompts),
            )
        )

        for o in outputs:
            results.append(o[0])
            errors.append(o[1])

    return results, errors


def wave_file(filename, pcm, channels=1, rate=24000, sample_width=2):
    with wave.open(filename, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(rate)
        wf.writeframes(pcm)


@errors.log_ctx_errors
def tts(
    text,
    filename,
    voice_name="Puck",
    model="gemini-2.5-flash-preview-tts",
    voice_description=None,
):
    """
    Generates speech using Gemini's expressive voices.
    """
    try:
        api_key = app_config.get().get("auth").get("google_genai_key")[0]
        client = google_genai_video_client.Client(api_key=api_key)

        # Build content generation config with voice description prompting support
        config = google_genai_video_types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=google_genai_video_types.SpeechConfig(
                voice_config=google_genai_video_types.VoiceConfig(
                    prebuilt_voice_config=google_genai_video_types.PrebuiltVoiceConfig(
                        voice_name=voice_name
                    )
                )
            ),
        )
        if voice_description:
            text = (
                f"Read the text in the style of this voice description: {voice_description}\nSpeech: "
                + text
            )

        response = client.models.generate_content(
            model=model,
            contents=text,
            config=config,
        )
        data = response.candidates[0].content.parts[0].inline_data.data
        wave_file(filename, data)

        return filename, None
    except Exception as e:
        logging.error(f"Gemini TTS failed: {e}")
        return None, None

    return None, None


if __name__ == "__main__":
    app_config.get().get("auth")["google_genai_key"] = [
        os.environ.get("GOOGLE_GEMINI_KEY")
    ]

    # Test Image Generation

    grid_prompt = """### NARRATIVE ARC GENERATION PROTOCOL
Generate a multi-panel storyboard grid representing a continuous sequence that captures a visual arc. The output MUST be a single image containing a grid of panels, closely matching the layout style of the provided Style Reference.

### SPATIAL & COMPOSITION CONSTRAINTS (CRITICAL):
1. **LOCKED CAMERA**: The camera MUST remain at a fixed position (Stationary Tripod) for all panels. The background architecture and geography MUST remain static.
2. **WARDROBE & POSTURE (CRITICAL)**: You MUST strictly lock each character's clothing, hairstyle, and physical build across ALL panels. Do not let their clothes change style or color between frames.
3. **REFERENCE MULTIPLEXING**: You will receive multiple Character References. You MUST strictly isolate each character's identity to the specific panel they are mentioned in.
4. **STYLE MATCHING (CRITICAL)**: The final image MUST look stylistically EXACTLY like the Style Reference. Use a 2D hand-painted storyboard style, flat colors, clear outlines, comic/animatic aesthetic. Do NOT generate photorealistic, smartphone, or documentary style images. Match the exact illustration style, shading, and mood of the Style Reference.

1. **SUBSTANTIVE MOVEMENT**: Each panel represents a clear, progressive step in the narrative action.                                                                                 [0/1876]
2. **CONTINUOUS FLOW**: The subject's trajectory across the grid must be logical and continuous. If the subject is walking, they should move significantly from Panel 1 to Panel 8 while the e
nvironment stays fixed.

### SUBJECT & CONTEXT:
1. **VISUAL DNA**: Maintain strict character identity.
2. **CONTEXT PRESERVATION**: Restate era in EVERY frame prompt. No pronouns.

Descriptions of narrative arc frames:

Panel 1: Image Metadata & Composition: Candid smartphone photo, 9:16 vertical, medium shot. Primary Subject: Actor Vijay in a 2024 Tamil Nadu film set setting, wearing a simple white cotton
shirt with sleeves rolled up. Lighting: Harsh studio lights turning off, leaving only a dim ambient glow. Subject Analysis: Vijay looks directly into the lens with a weary but resolved expre
ssion, sweat on the forehead, unstyled natural hair. Background: Blurred film crew packing up equipment in the background of a Chennai studio. Generation Parameters: Raw photo, slight natura
l grain, high realism, not staged, authentic exhaustion.
Panel 2: Image Metadata & Composition: Documentary-style low-angle shot, 9:16 vertical. Primary Subject: A group of diverse Tamil Nadu citizens in a rural village. Subject Analysis: A young
man and an elderly woman looking upward with defiance, hands clenched. Lighting: Dim, flickering orange light as if from a kerosene lamp or a distant fire, high contrast shadows. Background:
 Silhouette of a village banyan tree against a dark night sky. Generation Parameters: Authentic period clothing, worn textures, mud and dirt, natural ambient lighting, gritty historical real
ism.
Panel 3: Image Metadata & Composition: Extreme close-up, 4:5 vertical depth. Primary Subject: A weathered, sun-tanned hand of a farmer placed firmly over a chest covered in a simple khadi sh
irt. Color & Lighting: Warm golden hour light hitting the skin texture, deep shadows in the fabric folds. Subject Analysis: Visible veins and calluses on the hand, signifying hard labor. Bac
kground: Out-of-focus green paddy fields of Tamil Nadu. Generation Parameters: Highly accurate documentary photography, natural skin tones, raw and unfiltered look.
Panel 4: Image Metadata & Composition: Wide shot, 9:16 vertical. Primary Subject: A sea of people gathered in a public square in Madurai. Color & Lighting: Bright, natural daylight, slightly
 overcast. Subject Analysis: Thousands of people from various walks of life, looking toward a central point, no individual faces clearly distinguishable but a collective sense of power. Back
ground: Traditional South Indian architecture and temple towers in the far distance. Generation Parameters: Shot on smartphone, realistic crowd density, authentic urban Tamil Nadu environmen
t.
Panel 5: Image Metadata & Composition: Candid iPhone 15 photo, eye-level shot. Primary Subject: Vijay standing at the threshold of a simple, rustic wooden door. Subject Analysis: Vijay is we
aring a faded white linen shirt, holding a heavy wooden door open with his right hand, looking back at the camera with a humble, inviting smile. Position: Off-center, authentic posture. Back
ground: A bright, sunlit path visible through the doorway. Generation Parameters: Natural depth of field, un-posed, highly naturalistic, documentary style.
Panel 6: Image Metadata & Composition: Macro shot of a chalkboard in a small village school. Primary Subject: The number '118' written boldly in white chalk. Color & Lighting: Cool, indoor n
atural light from a side window. Background: The texture of a worn green chalkboard with faint previous writings erased. Generation Parameters: High realism, focus on the chalk dust texture,
 authentic classroom setting in rural Tamil Nadu.
Panel 7: Image Metadata & Composition: Landscape shot, 9:16 vertical. Primary Subject: The sun rising over the Chennai coastline. Color & Lighting: Deep oranges, purples, and golds of a fres
h sunrise. Background: The silhouette of the Bay of Bengal and the city skyline. Generation Parameters: Natural ambient lighting, no filters, high dynamic range, peaceful yet powerful mood.
Panel 8: Image Metadata & Composition: Close-up, 9:16 vertical. Primary Subject: Vijay sitting at a plain wooden table with a stack of papers and a pen. Subject Analysis: Vijay wearing a cle
an white shirt, looking directly into the camera with intense focus and a slight nod of readiness. Lighting: Neutral, everyday office lighting. Background: A wall with a simple map of Tamil
Nadu. Generation Parameters: Authentic, un-staged, everyday look, raw and unedited, high realism."""

    grid_refs = [
        {
            "url": object_storage.build_asset_url("images/aba981d8-69cd-4060-988e-fb8018c44c16_gemini_images.png"),
            "type": "style",
        },
        {
            "url": object_storage.build_asset_url("images/3f6ae1c6-7527-4d5f-9a08-a6507a7dd377_gemini_images.png"),
            "type": "character",
            "name": "Thalapathy Vijay",
        },
        {
            "url": object_storage.build_asset_url("images/f9cd5fb0-df73-459b-a23c-8745722d22fc_gemini_images.png"),
            "type": "character",
            "name": "CM M.K. Stalin",
        },
        {
            "url": object_storage.build_asset_url("images/dc3e3766-35bc-4439-98bd-aea9f569f0e7_gemini_images.png"),
            "type": "character",
            "name": "Elite Core Cell Commando",
        },
        {
            "url": object_storage.build_asset_url("images/4e0e19c1-2e0d-404e-9382-f3784b83a86d_gemini_images.png"),
            "type": "character",
            "name": "The Silver Whistle",
        },
    ]

    out = generate_image(grid_prompt, grid_refs, use_filesystem=True)
    print(f"Image generated: {out}")

    # Test Expressive TTS
    # text_to_speak = "Hello! I am Puck, one of the new expressive voices from Gemini. I can sound very natural and engaging for your social media content. How do I sound?"
    # output_file = "gemini_tts_puck.wav"
    # print(f"Generating TTS with voice 'Puck'...")
    # res_file, _ = tts(text_to_speak, output_file, voice_name="Fenrir")
    # if res_file and os.path.exists(res_file):
    #    print(
    #        f"Success! Gemini TTS saved to {res_file} ({os.path.getsize(res_file)} bytes)"
    #    )
    # else:
    #    print("Failed to generate Gemini TTS audio.")
