from logging import log
import requests
from . import errors
from .logger import logging
import time


@errors.raise_ctx_errors
def get_token():
    return app_config.get().get("auth").get("eachlabs_ai_token")


@errors.raise_ctx_errors
def invoke_lip_sync(image, audio):
    API_KEY = get_token()
    HEADERS = {"X-API-Key": API_KEY, "Content-Type": "application/json"}
    response = requests.post(
        "https://api.eachlabs.ai/v1/prediction/",
        headers=HEADERS,
        json={
            "model": "omnihuman",
            "version": "0.0.1",
            "input": {"audio_url": audio, "image_url": image, "mode": "normal"},
        },
    )
    response.raise_for_status()
    prediction = response.json()
    if prediction["status"] != "success":
        raise Exception(f"Prediction failed: {prediction}")
    return prediction["predictionID"]


@errors.raise_ctx_errors
def get_prediction(prediction_id):
    API_KEY = get_token()
    HEADERS = {
        "X-API-Key": API_KEY,
        "Content-Type": "application/json",
    }
    t = 10
    i = 0
    while i < t:
        result = requests.get(
            f"https://api.eachlabs.ai/v1/prediction/{prediction_id}", headers=HEADERS
        ).json()

        if result["status"] == "success":
            return result.get("output")
        elif result["status"] == "error":
            raise Exception(f"Prediction failed: {result}")

        i += 1
        time.sleep(60)

    raise Exception(f"Prediction timed-out: {prediction_id}")


@errors.raise_ctx_errors
def lip_sync(image, audio):
    prediction_id = invoke_lip_sync(image, audio)
    logging.info(f"EachLabs_AI: prediction id: {prediction_id}")
    return get_prediction(prediction_id)


if __name__ == "__main__":
    from . import object_storage
    img = object_storage.build_asset_url("RaginiFolkFables.png")
    aud = object_storage.build_asset_url("audios/b3f1f3fd-9feb-4747-a01e-f9c794a3c6f3_audio.mp3")

    try:
        # result = lip_sync(img, aud)
        result = get_prediction("15356930384571854594")
        print("Prediction successful!")
        print(result)  # Print the result
    except Exception as e:
        print(f"Error: {e}")
