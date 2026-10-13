import logging
import requests
from . import errors
from .configs import app_config


API_URL = "https://router.huggingface.co/fal-ai/fal-ai/chatterbox/text-to-speech"


def get_headers():
    token = app_config.get().get("auth").get("hf_token")
    return {"Authorization": f"Bearer {token}"}


@errors.log_ctx_errors
def tts(text, audio_url):
    j = {"text": text, "audio_url": audio_url}
    response = requests.post(API_URL, headers=get_headers(), json=j)

    logging.info(f"Chatterbox: status {response.status_code}")

    return response.json()


if __name__ == "__main__":
    output = tts(
        "Hi how are you ?",
        "https://storage.googleapis.com/eleven-public-prod/premade/voices/SOYHLrjzK2X1ezoPC6cr/86d178f6-f4b6-4e0e-85be-3de19f490794.mp3",
    )
    print(output)
