import replicate
from . import object_storage, errors, utils
from .configs import app_config
from uuid import uuid4
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

token_loaded = False
from functools import lru_cache


@lru_cache(maxsize=None)
@errors.raise_ctx_errors
def load_token():
    """
    Loads the Replicate API token into an environment variable.
    Using lru_cache ensures this function only runs once and is thread-safe.
    """
    t = app_config.get().get("auth").get("replicate_token")
    os.environ["REPLICATE_API_TOKEN"] = t


@errors.log_ctx_errors
def lip_sync(engine, reference, audio, upload=False):
    load_token()

    output = None

    if engine == "replicate_sadtalker":
        output = replicate.run(
            "cjwbw/sadtalker:a519cc0cfebaaeade068b23899165a11ec76aaa1d2b313d40d214f204ec957a3",
            input={
                "facerender": "facevid2vid",
                "pose_style": 0,
                "preprocess": "crop",
                "still_mode": True,
                "driven_audio": audio,
                "source_image": reference,
                "use_enhancer": True,
                "use_eyeblink": True,
                "size_of_image": 256,
                "expression_scale": 1,
            },
        )
    elif engine == "replicate_video_retalking":
        output = replicate.run(
            "chenxwh/video-retalking:db5a650c807b007dc5f9e5abe27c53e1b62880d1f94d218d27ce7fa802711d67",
            input={"face": reference, "input_audio": audio},
        )

    else:
        return None

    video_content = output.read()
    file = f"{uuid4()}_lip_sync_1.mp4"

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


@errors.log_ctx_errors
def remove_background(video_url, use_chroma_key=False, upload=False):
    load_token()

    output, p_1, p_2, public_url_1, public_url_2 = None, None, None, None, None
    file = f"{uuid4()}_no_bg.mp4"

    # green
    color = "#008000"

    output = replicate.run(
        "lucataco/rembg-video:c18392381d1b5410b5a76b9b0c58db132526d3f79fe602e04e0d80cb668df509",
        input={"mode": "Fast", "video": video_url, "background_color": color},
    )

    video_content = output.read()
    if upload:
        public_url_1 = object_storage.upload_data(
            object_storage.ASSETS_VIDEO_BUCKET,
            video_content,
            file,
            object_storage.ACL_PUBLIC,
        )

    if use_chroma_key or not upload:
        p_1 = os.path.join(os.path.dirname(__file__), "tmp", file)
        with open(p_1, "wb") as f:
            f.write(video_content)

    if use_chroma_key:
        p_2 = utils.chroma_key(p_1)

        if upload and p_2:
            public_url_2 = object_storage.upload_file(
                object_storage.ASSETS_VIDEO_BUCKET,
                p_2,
                file,
                object_storage.ACL_PUBLIC,
            )

    if upload:
        return public_url_1, public_url_2
    else:
        return p_1, p_2


@errors.propogate_ctx_errors
def generate_image(
    prompt,
    ref,
    image_engine="replicate_flux_kontext",
    aspect_ratio="9:16",
    output_format="png",
):
    load_token()

    model_map = {
        "replicate_ideogram": "ideogram-ai/ideogram-v3-quality",
        "replicate_flux_kontext": "black-forest-labs/flux-kontext-pro",
        "replicate_flux_schnell": "black-forest-labs/flux-schnell",
        "replicate_flux_krea_dev": "black-forest-labs/flux-krea-dev",
        "replicate_flux_dev": "black-forest-labs/flux-dev",
        "replicate_sdxl": "stability-ai/sdxl:7762fd07cf82c948538e41f63f77d685e02b063e37e496e96eefd46c929f9bdc"
    }

    model_identifier = model_map.get(image_engine)
    if not model_identifier:
        raise Exception(f"unkown replicate model used - {image_engine}")

    input_payload = {
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
    }

    if image_engine == "replicate_ideogram":
        input_payload.update(
            {
                "resolution": "None",
                "style_type": "None",
                "magic_prompt_option": "Auto",
            }
        )
    else:  # for flux models
        input_payload.update(
            {
                "output_format": output_format,
                "prompt_upsampling": False,
            }
        )

    output = replicate.run(model_identifier, input=input_payload)
    file = f"{uuid4()}_{image_engine}.png"

    image_content = output.read()
    public_url = object_storage.upload_data(
        object_storage.ASSETS_IMG_BUCKET,
        image_content,
        file,
        object_storage.ACL_PUBLIC,
    )

    return public_url


@errors.log_ctx_errors
def generate_images(
    prompts: list[str],
    refs: list[Optional[str]],
    image_engine="replicate_flux_kontext",
    aspect_ratio="9:16",
    output_format="png",
):
    load_token()

    results = []
    errors = []

    with ThreadPoolExecutor() as executor:
        outputs = list(
            executor.map(
                generate_image,
                prompts,
                refs,
                [image_engine] * len(prompts),
                [aspect_ratio] * len(prompts),
                [output_format] * len(prompts),
            )
        )

        for o in outputs:
            results.append(o[0])
            errors.append(o[1])

    return results, errors


@errors.log_ctx_errors
def text_to_speech(text, voice_id="Casual_Guy"):
    load_token()

    input = {
        "text": text,
        "emotion": "auto",
        "voice_id": voice_id,
        "language_boost": "None",
        "english_normalization": True,
    }

    output = replicate.run(
        "minimax/speech-02-turbo",
        input=input,
    )

    audio_content = output.read()
    file = f"{uuid4()}_minimax_tts.mp3"

    p = os.path.join(os.path.dirname(__file__), "tmp", file)
    with open(p, "wb") as f:
        f.write(audio_content)
    return p


@errors.propogate_ctx_errors
def voice_cloning(voice_file_url):
    load_token()

    input = {
        "voice_file": voice_file_url,
        "need_noise_reduction": True,
        "need_volume_normalization": True,
    }

    output = replicate.run(
        "minimax/voice-cloning",
        input=input,
    )

    return (output.get("voice_id"), output.get("preview"))


if __name__ == "__main__":

    from . import object_storage
    img = object_storage.build_asset_url("RaginiFolkFables.png")
    aud = object_storage.build_asset_url("audios/b3f1f3fd-9feb-4747-a01e-f9c794a3c6f3_audio.mp3")

    # out = lip_sync(img, aud)
    # out = remove_background(
    #    "https://bashupload.com/icDuy/vaEYD.mp4?download=1",
    #    use_chroma_key=True,
    #    upload=False,
    # )

    out_ideogram = generate_images(
        [
            'Person standing in front of Azure AI Services logo board with "Multi-service Resource" and "Single-service Resources" options, modern office background, photorealistic, sense of wonder, close-up perspective, captured with Leica M10 and Leica Summilux-M 35mm f/1.4 ASPH lens, spotlight illumination, neon accents --ar 9:16 --stylize 600'
        ]
    )

    out_kontext = generate_images(
        [
            'Person standing in front of Azure AI Services logo board with "Multi-service Resource" and "Single-service Resources" options, modern office background, photorealistic, sense of wonder, close-up perspective, captured with Leica M10 and Leica Summilux-M 35mm f/1.4 ASPH lens, spotlight illumination, neon accents --ar 9:16 --stylize 600'
        ],
        image_engine="replicate_flux_kontext",
    )

    print(out_ideogram, out_kontext)
