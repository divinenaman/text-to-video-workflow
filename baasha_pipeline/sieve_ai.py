import requests
from . import object_storage, errors
from .configs import app_config
from .logger import logging
from uuid import uuid4
import os
import json
import time


@errors.raise_ctx_errors
def get_token():
    return app_config.get().get("auth").get("sieve_ai_token")


def poll_job_status(job_id, api_key, max_attempts=10, wait_interval=5):

    url = f"https://mango.sievedata.com/v2/jobs/{job_id}"
    headers = {"X-API-Key": api_key}

    for attempt in range(max_attempts):
        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)

            job_data = response.json()
            status = job_data.get("status")

            if status == "finished":
                logging.info(
                    f"Sieve_JOB {job_id} completed after {attempt + 1} attempts."
                )
                return job_data.get("outputs", [])[0].get("data").get("url")
            else:
                logging.info(
                    f"Sieve_JOB {job_id} status: {status}. Attempt {attempt + 1}/{max_attempts}. Waiting {wait_interval} seconds..."
                )
                time.sleep(wait_interval)

        except requests.exceptions.RequestException as e:
            logging.info(f"Sieve_JOB Error during request: {e}")
            return None

    logging.info(f"Sieve_JOB {job_id} did not complete within {max_attempts} attempts.")
    return None


@errors.log_ctx_errors
def sieve_lipsync(video_url, audio_url, upload=False):

    url = "https://mango.sievedata.com/v2/push"
    headers = {"Content-Type": "application/json", "X-API-Key": get_token()}
    data = {
        "function": "sieve/lipsync",
        "inputs": {
            "file": {"url": video_url},
            "audio": {"url": audio_url},
            "backend": "sievesync-1.1",
            "enable_multispeaker": False,
            "enhance": "default",
            "downsample": False,
            "cut_by": "audio",
        },
    }

    response = requests.post(url, headers=headers, data=json.dumps(data))

    if response.status_code != 200:
        print(f"Error: {response.status_code}, {response.text}")
        return None

    resp = response.json()

    if not resp.get("id"):
        return None

    job_id = resp.get("id")
    video_url = poll_job_status(job_id, get_token(), max_attempts=10, wait_interval=30)

    if not video_url:
        logging.info(f"Error fetching sieve job {job_id} content")

    file = f"{uuid4()}_sieve_lipsync.mp4"

    if upload:
        video_data = requests.get(video_url).content
        public_url = object_storage.upload_data(
            object_storage.ASSETS_VIDEO_BUCKET,
            video_data,
            file,
            object_storage.ACL_PUBLIC,
        )
        return public_url
    else:
        video_data = requests.get(video_url).content
        p = os.path.join(os.path.dirname(__file__), "tmp", file)
        with open(p, "wb") as f:
            f.write(video_data)
        return p


if __name__ == "__main__":
    from . import object_storage
    img = object_storage.build_asset_url("RaginiFolkFables.png")
    aud = object_storage.build_asset_url("audios/b3f1f3fd-9feb-4747-a01e-f9c794a3c6f3_audio.mp3")

    u = sieve_lipsync(img, aud, False)
    print(u)
