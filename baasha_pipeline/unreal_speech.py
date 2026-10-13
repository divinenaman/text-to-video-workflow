# Long endpoint: /synthesisTasks
# - Up to 500,000 characters
# - Asynchronous, takes ~1s per 800 chars
# - Returns a TaskId (use to check status)

import os

import requests
from .configs import app_config
from . import errors, utils
from .logger import logging
import time


def api_key():
    return (
        app_config.get().get("auth").get("unreal_speech_key")
        or os.environ.get("UNREAL_SPEECH_KEY")
        or ""
    )


def poll_handler(response):
    if response.status_code == 200:
        task = response.json().get("SynthesisTask")
        if task:
            logging.info(f"unreal-task-status: {task}")
            task_id = task.get("TaskId")
            output_uri = task.get("OutputUri")
            status = task.get("TaskStatus")

            if status == "completed" and output_uri:
                return output_uri

            time.sleep(2)
            resp = requests.get(
                f"https://api.v8.unrealspeech.com/synthesisTasks/{task_id}",
                headers={"Authorization": f"Bearer {api_key()}"},
                json={},
            )

            return poll_handler(resp)
        return None
    else:
        logging.error(
            f"UNREAL-SPEECH-ERROR: {response.status_code} - {response.content}"
        )
        return None


@errors.log_ctx_errors
def generate_audio(t, voice_key="Will"):
    if not voice_key:
        voice_key = "Will"

    response = requests.post(
        "https://api.v8.unrealspeech.com/synthesisTasks",
        headers={"Authorization": f"Bearer {api_key()}"},
        json={
            "Text": t,  # Up to 500,000 characters
            "VoiceId": voice_key,  # Dan, Will, Scarlett, Liv, Amy
            "Bitrate": "192k",  # 320k, 256k, 192k, ...
            "Speed": "0.2",  # -1.0 to 1.0
            "Pitch": "0",  # -0.5 to 1.5
            "TimestampType": "word",  # word or sentence
            #'CallbackUrl': '<URL>', # pinged when ready
        },
    )
    url = poll_handler(response)
    logging.info(f"UNREAL-SPEECH: generation {url}")
    if url:
        time.sleep(2)
        out = utils.download_media_by_url(url, force_ext="wav")
        return out

    return None


if __name__ == "__main__":
    t = "Check the status of a speech synthesis task."
    o = generate_audio(t)
    print(o)
