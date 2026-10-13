import requests
import json
from .logger import logging
from . import errors
from .configs import app_config


@errors.raise_ctx_errors
def get_ideogram_token():
    return app_config.get().get("auth").get("ideogram_key")


@errors.log_ctx_errors
def generate_image(prompt):
    """
    Create a task for image generation using the Ideogram API.
    Args:
        prompt (str): Prompt for image generation.
    Returns:
        object: data[0].url
    """
    ideogram_api_url = "https://api.ideogram.ai/v1/ideogram-v3/generate"

    headers = {"Api-Key": get_ideogram_token()}

    payload = {
        "prompt": p,
        "rendering_speed": "DEFAULT",
        "aspect_ratio": "9x16",
        "num_images": 1,
    }

    try:
        logging.info(f"Creating Ideogram task with prompt: {prompt}")
        response = requests.post(ideogram_api_url, headers=headers, data=payload)

        response_data = response.json()
        img = response_data.get("data")[0].get("url")
        return img

    except requests.exceptions.RequestException as e:
        logging.error(f"Request error creating Ideogram task: {e}")
        return None
    except json.JSONDecodeError:
        logging.error(f"Failed to decode JSON response from Ideogram: {response.text}")
        return None
    except Exception as e:
        logging.error(f"An unexpected error occurred creating Ideogram task: {e}")
        return None


@errors.log_ctx_errors
def generate_images(prompts):
    if not prompts:
        logging.info("No prompts provided for Ideogram generation.")
        return []

    res = [None] * len(prompts)

    def cb(i, url):
        res[i] = url

    with ThreadPoolExecutor() as executor:
        _ = list(
            executor.map(
                generate_image, prompts, list(range(len(prompts))), [cb] * len(prompts)
            )
        )

    return res
