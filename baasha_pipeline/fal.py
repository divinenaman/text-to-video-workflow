import fal_client as fal
from . import object_storage, errors, utils
from .configs import app_config
from uuid import uuid4
import os
from functools import lru_cache
from .logger import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional


@lru_cache(maxsize=None)
@errors.raise_ctx_errors
def load_token():
    """
    Loads the Fal API token into an environment variable.
    Using lru_cache ensures this function only runs once and is thread-safe.
    """
    t = app_config.get().get("auth").get("fal_token")
    os.environ["FAL_KEY"] = t


@errors.log_ctx_errors
def image_to_video(prompt, image_url, upload=False):
    load_token()

    result = fal.subscribe(
        "fal-ai/bytedance/seedance/v1/lite/image-to-video",
        arguments={
            "prompt": prompt,
            "image_url": image_url,
            "aspect_ratio": "9:16",
            "resolution": "480p",
            "duration": "3",
        },
    )

    logging.info(result)

    try:
        video_url = result["video"]["url"]
    except Exception as e:
        logging.info(e)
        video_url = result["video"].url

    import requests

    video_content = requests.get(video_url).content

    file = f"{uuid4()}_fal_video.mp4"

    if upload:
        public_url = object_storage.upload_data(
            object_storage.ASSETS_VIDEO_BUCKET,
            video_content,
            file,
            object_storage.ACL_PUBLIC,
        )
        return public_url

    else:
        p = os.path.join(os.path.dirname(__file__), "tmp", file)
        with open(p, "wb") as f:
            f.write(video_content)
        return p


@errors.propogate_ctx_errors
def generate_video(
    prompt,
    ref=None,
    last_ref=None,
    duration_seconds=4,
    aspect_ratio="9:16",
    resolution="480p",
    generate_audio=False,
    use_filesystem=False,
    model="kling",
):
    load_token()

    resolution_str = str(resolution).strip().lower()

    supported_res = ["480p", "720p", "1080p"]
    if model == "ltx":
        supported_res = ["1080p"]

    elif model == "minmax":
        supported_res = ["512p", "768p"]

    if resolution_str not in supported_res:
        resolution_str = supported_res[0]

    arguments = {
        "prompt": prompt,
        "duration": duration_seconds,
        "aspect_ratio": aspect_ratio,
        "resolution": resolution_str,
        "fps": 25,
        "generate_audio": generate_audio,
    }

    start_img_key = "start_image_url"
    end_img_key = "end_image_url"

    if model == "ltx" or model == "seedance":
        start_img_key = "image_url"
        end_img_key = "end_image_url"

    if ref:
        arguments[start_img_key] = ref
    if last_ref:
        arguments[end_img_key] = last_ref

    logging.info(f"Starting Fal video generation with arguments: {arguments}")

    try:
        md = "fal-ai/kling-video/v3/standard/image-to-video"

        if model == "ltx":
            md = "fal-ai/ltx-2.3/image-to-video/fast"
        elif model == "minmax":
            md = "fal-ai/minimax/hailuo-02/standard/image-to-video"
        elif model == "seedance":
            md = "fal-ai/bytedance/seedance/v1.5/pro/image-to-video"

        result = fal.subscribe(
            md, arguments=arguments, with_logs=False, client_timeout=500
        )

        logging.info(f"Fal video generation result: {result}")

        try:
            video_url = result["video"]["url"]
            logging.info(f"Fal video URL: {video_url}")
        except Exception as e:
            logging.info(f"Could not parse video URL with dict key: {e}")
            video_url = result["video"].url

        if not video_url:
            logging.error("Fal finished but no video URL was found.")
            return None

        import requests

        video_content = requests.get(video_url, timeout=60).content

        file_name = f"{uuid4()}_fal_video.mp4"
        if use_filesystem:
            p = os.path.join(os.path.dirname(__file__), "tmp", file_name)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb") as f:
                f.write(video_content)
            logging.info(f"Fal video saved locally: {p}")
            return p
        else:
            public_url = object_storage.upload_data(
                object_storage.ASSETS_VIDEO_BUCKET,
                video_content,
                file_name,
                object_storage.ACL_PUBLIC,
            )
            logging.info(f"Fal video uploaded successfully: {public_url}")
            return public_url

    except Exception as e:
        logging.error(f"An error occurred during Fal video generation: {e}")
        return None


@errors.propogate_ctx_errors
def generate_image(
    prompt,
    refs=None,
    width=None,
    height=None,
    aspect_ratio="9:16",
    image_resolution="1K",
    image_engine="fal/z-image",
    use_filesystem=False,
):
    load_token()

    image_urls = []
    mask_image_url = None

    if refs:
        if isinstance(refs, str) or isinstance(refs, dict):
            refs = [refs]

        image_idx = 1
        ref_prompts = []
        for ref in refs:
            ref_url = ref.get("url") if isinstance(ref, dict) else ref
            ref_type = (
                ref.get("type", "subject") if isinstance(ref, dict) else "subject"
            )

            if ref_url:
                if ref_type == "mask":
                    mask_image_url = ref_url
                else:
                    image_urls.append(ref_url)

                    name = ref.get("name") if isinstance(ref, dict) else None

                    if ref_type == "style":
                        desp = "Style Reference, do not recreate the background, people, things and recreate just the style"
                    elif ref_type == "scene":
                        desp = "Scene Reference"
                    else:
                        desp = "Character Reference"

                    if name:
                        desp += f" - {name}"

                    ref_prompts.append(
                        f"Input image {image_idx} to be used as {desp} only."
                    )
                    image_idx += 1

        if ref_prompts:
            prompt += "\nReferences:\n" + "\n".join(ref_prompts)

    quality_map = {"1K": "low", "2K": "medium", "4K": "high"}
    quality = quality_map.get(str(image_resolution).upper(), "low")

    aspect_ratio_map = {
        "1:1": "square_hd",
        "4:3": "landscape_4_3",
        "16:9": "landscape_16_9",
        "3:4": "portrait_4_3",
        "9:16": "portrait_16_9",
    }

    if aspect_ratio and aspect_ratio in aspect_ratio_map:
        image_size = aspect_ratio_map[aspect_ratio]
    elif width and height:
        image_size = {"width": width, "height": height}
    else:
        image_size = "auto"

    logging.info(f"fal image prompt: {prompt}")

    arguments = {
        "prompt": prompt,
        "quality": quality,
        "output_format": "png",
        "image_size": image_size,
    }

    if image_urls:
        arguments["image_urls"] = image_urls
    if mask_image_url:
        arguments["mask_image_url"] = mask_image_url

    model = "fal-ai/z-image/turbo/image-to-image"

    if image_engine == "fal/z-image":
        model = "fal-ai/z-image/turbo/image-to-image"
        arguments["strength"] = 0.9
        arguments["image_url"] = image_urls[0]

    if image_engine == "fal/gpt":
        model = "openai/gpt-image-2/edit"

    result = fal.subscribe(model, arguments=arguments, with_logs=False)

    logging.info(result)

    try:
        if "data" in result and "images" in result["data"]:
            image_url = result["data"]["images"][0]["url"]
        else:
            image_url = result["images"][0]["url"]
    except Exception as e:
        logging.info(e)
        try:
            if hasattr(result, "data"):
                image_url = result.data.images[0].url
            else:
                image_url = result.images[0].url
        except Exception as inner_e:
            logging.error(f"Failed to parse image URL from result: {inner_e}")
            return None

    if not image_url:
        return None

    import requests

    image_content = requests.get(image_url).content

    file_name = f"{uuid4()}_fal_image.png"

    if use_filesystem:
        p = os.path.join(os.path.dirname(__file__), "tmp", file_name)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(image_content)
        return p
    else:
        public_url = object_storage.upload_data(
            object_storage.ASSETS_IMG_BUCKET,
            image_content,
            file_name,
            object_storage.ACL_PUBLIC,
        )
        return public_url


@errors.log_ctx_errors
def generate_images(
    prompts: list[str],
    refs: Optional[list[Optional[str]]] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    aspect_ratio: str = "9:16",
    image_resolution="1K",
    image_engine="fal/z-image",
):
    results = []
    errs = []

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
                [image_engine] * len(prompts),
            )
        )

        for o in outputs:
            results.append(o[0])
            errs.append(o[1])

    return results, errs


if __name__ == "__main__":
    if os.environ.get("FAL_KEY"):
        if "auth" not in app_config.get():
            app_config.get()["auth"] = {}
        app_config.get()["auth"]["fal_token"] = os.environ.get("FAL_KEY")

    test_prompt = (
        "A cinematic shot of a majestic an Indian city at sunset highly detailed."
    )

    p = """### NARRATIVE ARC GENERATION PROTOCOL
Generate a grid representing a continuous cinematic sequence that captures a substantive visual arc. The panels must be usable as keyframes for a 1-minute video take.

### SPATIAL & COMPOSITION CONSTRAINTS (CRITICAL):
1. **SPATIAL ANCHORING & FREE CAMERA**: The panels represent different cinematic camera setups (Wide Establishing Shot, Over-The-Shoulder, Reverse Angle, Close-Up) within highly detailed physical spaces. If multiple panels share the same Location description, you MUST maintain perfect architectural geometry, furniture placement, and lighting continuity for that room across those panels, even as the camera spins 180 degrees or changes angles. Treat the room like a fixed 3D render.
2. **OBJECT PERMANENCE & PROPS (CRITICAL)**: DO NOT invent large furniture (like tables, desks, or thrones) unless explicitly requested in the prompt. Do not randomly add them mid-scene.
3. **DEPTH & PERSPECTIVE**: Ensure foreground and background elements align with the location description. Maintain realistic scale. No giant floating heads over tiny backgrounds.
4. **WARDROBE & POSTURE**: You MUST strictly lock each character's clothing, hairstyle, and physical build across ALL panels. Characters MUST maintain realistic anatomical postures.
5. **DYNAMIC CROWDS (NO CLONES)**: If a panel includes a group of people or goons, give them diverse facial features, expressions, and slightly varied postures. DO NOT copy-paste identical clones.
6. **NO SPLIT SCREENS**: Each panel MUST be a single cinematic frame. ABSOLUTELY NO diagonal split-screens, comic-book dividers, or in-panel collages.
7. **REFERENCE MULTIPLEXING**: You will receive multiple Character References. You MUST strictly isolate each character's identity to the specific panel they are mentioned in. DO NOT bleed or merge different character faces/clothes together. NEVER create deformed compositions.

### PROGRESSIVE ARC LOGIC:
1. **SUBSTANTIVE MOVEMENT**: Each panel represents a clear, progressive step in the narrative action or cinematic camera movement.
2. **CONTINUOUS FLOW**: The subject's trajectory across the grid must be logical and continuous.

### SUBJECT & CONTEXT:
1. **VISUAL DNA**: Maintain strict character identity.
2. **CONTEXT PRESERVATION**: Restate era in EVERY frame prompt. No pronouns.

Descriptions of narrative arc frames:

Panel 1: Continuing in the exact same location as the previous panel. SET MODIFICATIONS: None Left side shows C. Joseph Vijay’s steady, calm gaze. Right side shows M. K. Stalin’s snarling, furious expression.
Follow the style reference for the visual art style, colors, lighting, and overall aesthetic of the provided style reference strictly across all panels. This grid will consits of scenes from 11 to 11 and is a direct continuation of the previous scenes. Refer to location, lighting, and characters as established in the references. create a single frame only"""

    test_ref = {
        "url": object_storage.build_asset_url("images/Screenshot%20from%202026-04-30%2004-59-08.png"),
        "type": "style",
    }

    print("Testing Fal generate_image...")
    res = generate_image(
        prompt=p,
        refs=[test_ref],
        aspect_ratio="9:16",
        image_resolution="1K",
        use_filesystem=True,
    )

    print(f"Result: {res}")

    # Test generate_video
    # print("Testing Fal generate_video...")
    # video_res = generate_video(
    #    prompt="Charging towards the seated person aggresively",
    #    ref="https://baasha-assets.us-east-1.linodeobjects.com/images/b2863fd0-bb09-4a98-b75e-94cd71632414_fal_image.png",
    #    last_ref="https://baasha-assets.us-east-1.linodeobjects.com/images/badb9986-6d04-427b-bae8-b397f69d12e8_fal_image.png",
    #    duration_seconds=4,
    #    aspect_ratio="9:16",
    #    resolution="480p",
    #    generate_audio=True,
    #    use_filesystem=True,
    #    model="seedance",
    # )
    # print(f"Video Result: {video_res}")
