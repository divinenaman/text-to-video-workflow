import requests
from .configs import app_config
from . import utils, errors
from .logger import logging
import os
import json


@errors.raise_ctx_errors
def get_api():
    return app_config.get().get("coqui_server")


@errors.log_ctx_errors
def tts(text):
    api = get_api()
    response = requests.post(f"{api}/tts", json={"text": text, "link": True})

    if response.status_code != 200:
        raise Exception("coqui-tts: non-200 response: " + str(response.text))

    res = response.json()
    link = res.get("link")
    out = utils.download_media_by_url(f"{api}/static/{link}", force_ext="wav")

    return out


def healthy():
    try:
        api = get_api()
        response = requests.get(f"{api}/health")
        if response.status_code != 200:
            return False
        return True
    except Exception as e:
        logging.info("coqui-tts: not healthy, %s", e)
        return False


if __name__ == "__main__":
    # print(tts("Hey there this is a Test!"))
    print(healthy())
