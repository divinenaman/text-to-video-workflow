import requests
from .configs import app_config
from . import errors
import base64

API_URL = "https://api.sarvam.ai/text-to-speech"


@errors.raise_ctx_errors
def get_key():
    API_KEY = app_config.get().get("auth").get("sarvam_ai_key")
    if not API_KEY:
        raise ValueError("Sarvam AI API key not found in config")
    return API_KEY


@errors.log_ctx_errors
def tts(text, filename, voice="anushka", lang="hi-IN"):
    """
    Generates speech from text using Sarvam AI TTS.
    """
    api_key = get_key()

    headers = {
        "api-subscription-key": api_key,
        "content-type": "application/json",
    }

    payload = {
        "text": text,
        "target_language_code": lang,
        "speaker": voice,
        "pitch": 0,
        "pace": 1,
        "loudness": 1,
        "speech_sample_rate": 22050,
        "enable_preprocessing": True,
        "model": "bulbul:v2",
    }

    response = requests.post(API_URL, headers=headers, json=payload)

    if response.status_code == 200:
        audio = response.json().get("audios")[0]
        original_bytes = base64.b64decode(audio)
        with open(filename, "wb") as f:
            f.write(original_bytes)
        return filename
    else:
        response.raise_for_status()


if __name__ == "__main__":
    import os

    # This is an example of how to use the tts function.
    # You will need to set the 'sarvam_ai_key' in your app_config.
    # For example, in app_config.py:
    # "sarvam_ai_key": "your_sarvam_api_key"
    text_to_speak = "नमस्ते, यह एक परीक्षण है।"
    output_filename = os.path.join(os.getcwd(), "sarvam_test.wav")

    try:
        tts(text_to_speak, output_filename)
        print(f"Audio content written to file '{output_filename}'")
    except Exception as e:
        print(f"An error occurred: {e}")
