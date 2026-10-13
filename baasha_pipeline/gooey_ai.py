from . import errors, eleven_labs
import requests
from concurrent.futures import ThreadPoolExecutor
from .configs import app_config
import os


@errors.raise_ctx_errors
def get_token():
    return os.getenv('ELEVENLABS_KEY', '')
    # fallback to app config if set
    # return app_config.get().get('auth', {}).get('eleven_labs_key')


@errors.raise_ctx_errors
def convert_image_to_videos(engine, images, prompts):

    generated_videos = None

    with ThreadPoolExecutor() as executor:
        generated_videos = list(
            executor.map(text_to_video, [engine] * len(images), prompts)
        )

    return generated_videos


@errors.log_ctx_errors
def text_to_video(engine, prompt):
    payload = {"animation_prompts": [{"frame": 0, "prompt": prompt}], "fps": 12}

    response = requests.post(
        "https://api.gooey.ai/v2/DeforumSD",
        headers={
            "Authorization": "bearer " + get_token(),
        },
        json=payload,
    )
    assert response.ok, response.content

    result = response.json()

    return result.get("output", {}).get("output_video")


@errors.raise_ctx_errors
def lip_sync(source_face, text, tts):

    if not tts.get("engine") == "eleven_labs":
        raise Exception("tts not supported for gooey lipsync")

    payload = {
        "text_prompt": text,
        "input_face": source_face,
        "tts_provider": "ELEVEN_LABS",
        "elevenlabs_api_key": eleven_labs.get_key(),
        "elevenlabs_voice_id": tts.get("voice_id"),
        "elevenlabs_model": "eleven_multilingual_v2",
    }

    response = requests.post(
        "https://api.gooey.ai/v2/LipsyncTTS",
        headers={
            "Authorization": "bearer " + get_token(),
        },
        json=payload,
    )
    assert response.ok, response.content

    result = response.json()
    return result.get("output", {}).get("output_video")


if __name__ == "__main__":

    res = convert_image_to_videos(
        "",
        ["1"],
        [
            "Trader surrounded by open financial books and papers, notes and scribbled equations, calendar on the wall showing April 3rd, diagram of options strategies leaning against it, Afrofuturism-inspired futuristic elements, curious atmosphere, dutch angle composition, reminiscent of Sony Alpha a7 III camera aesthetic, translucent light effects --ar 9:16 --stylize 600"
        ],
    )

    print(res)
