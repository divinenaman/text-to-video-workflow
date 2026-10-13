import requests
import time
from . import errors  # Assuming errors.py exists in the same directory
from .logger import logging  # Assuming logger.py exists
from .configs import app_config

BASE_URL = "https://lemonslice.com/api/v2"
GENERATE_URL = f"{BASE_URL}/generate"
GENERATIONS_URL = f"{BASE_URL}/generations"


@errors.raise_ctx_errors
def get_token():
    return app_config.get().get("auth").get("lemon_slice_ai_token")


@errors.raise_ctx_errors
def generate_video(img_url, audio_url):
    headers = {
        "accept": "application/json",
        "authorization": f"Bearer {get_token()}",
        "content-type": "application/json",
    }
    data = {"img_url": img_url, "audio_url": audio_url}

    response = requests.post(GENERATE_URL, headers=headers, json=data)
    response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
    result = response.json()
    job = result.get("job_id")
    logging.info(f"Generate video result: {job}")
    return job


@errors.raise_ctx_errors
def get_generation(generation_id, retry=10):
    url = f"{GENERATIONS_URL}/{generation_id}"
    headers = {"authorization": f"Bearer {get_token()}"}

    response = requests.get(url, headers=headers)
    response.raise_for_status()
    result = response.json()

    status = result.get("status")

    if status == "completed":
        link = result.get("video_url")
        logging.info(f"LEMON_SLICE_VIDEO: {link}")
        return link

    elif status == "error":
        logging.error(f"LEMON_SLICE_ERROR: {result}")
        return None

    elif retry > 0:
        time.sleep(60)
        return get_generation(generation_id, retry - 1)

    logging.info(f"LEMON_SLICE_TIMEOUT: {result}")
    return None


@errors.raise_ctx_errors
def lip_sync(img_url, audio_url):
    job_id = generate_video(img_url, audio_url)
    if job_id:
        generation_response = get_generation(job_id)
        return generation_response

    return None


if __name__ == "__main__":
    from . import object_storage
    img = object_storage.build_asset_url("RaginiFolkFables.png")
    aud = object_storage.build_asset_url("audios/b3f1f3fd-9feb-4747-a01e-f9c794a3c6f3_audio.mp3")
    resp = lip_sync(img, aud)
    print("Generation Response:", resp)
