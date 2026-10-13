import logging
import os
import requests
from . import errors

API_URL = "https://api-inference.huggingface.co/models/openai/whisper-large-v3-turbo"
headers = {"Authorization": f"Bearer {os.getenv('HF_WHISPER_TOKEN', '')}"}


@errors.log_ctx_errors
def stt(filename):
    logging.info(f"Open-Whisper: running stt on {filename}")
    with open(filename, "rb") as f:
        data = f.read()
    response = requests.post(API_URL, headers=headers, data=data)

    logging.info(f"Open-Whisper: status {response.status_code}")
    logging.info(f"Open-Whisper: status {response.content}")

    return response.json()["text"]


if __name__ == "__main__":
    output = query("baasha_pipeline/tmp/media_21e6881b-a83a-418d-90e8-0970afb04016.mp3")
    print(output)
