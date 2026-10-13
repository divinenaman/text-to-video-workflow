from logging import error
import requests
import json
import time
from concurrent.futures import ThreadPoolExecutor
from .logger import logging
from . import errors
from .configs import app_config


@errors.raise_ctx_errors
def get_token():
    return app_config.get().get("auth").get("goapi_midjourney_key")


@errors.propogate_ctx_errors
def create_task(
    prompt,
    ref_image,
    api_key,
    width=None,
    height=None,
    negative_prompt=None,
    model="Qubico/flux1-dev",
):
    """
    Create a task for image generation.

    Args:
        prompt (str): Prompt for image generation.
        images (list[str]): List of reference images.
        api_key (str): Your GoAPI Key.
        model (str, optional): Model to use for generation. Defaults to "Qubico/flux1-dev".
        task_type (str, optional): Type of task. Defaults to "txt2img".

    Returns:
        str: Task ID.
    """
    # Create task payload
    payload = {
        "model": model,
        "task_type": "txt2img",
        "input": {
            "prompt": prompt,
            "width": width or 720,
            "height": height or 1280,
            "negative_prompt": negative_prompt
            or "bad hands"
            or "text, writing, words, letters, blurry focus, multiple people",
        },
    }

    if ref_image:
        payload["task_type"] = "img2img"
        payload["input"]["image"] = ref_image

    # Send request to create task
    headers = {"X-API-Key": api_key, "Content-Type": "application/json"}
    response = requests.post(
        "https://api.goapi.ai/api/v1/task", headers=headers, data=json.dumps(payload)
    )

    # Check if task was created successfully
    if response.status_code == 200:
        return response.json()["data"]["task_id"]
    else:
        logging.info(f"Error creating task {model} : {response.text}")
        return None


@errors.propogate_ctx_errors
def get_task_result(task_id, idx):
    if not task_id:
        raise Exception("goapi_flux1 : empty task_id")

    headers = {"X-API-Key": get_token(), "Content-Type": "application/json"}
    i = 0
    while i < 15:
        i += 1
        response = requests.get(
            f"https://api.goapi.ai/api/v1/task/{task_id}", headers=headers
        )
        if response.status_code == 200:
            task_status = response.json()["data"]["status"]
            if task_status == "completed":
                output = response.json()["data"]["output"]
                url = output.get("image_url") or output.get("video_url")
                logging.info(f"GOAPI-FLUX-completed : {url}")
                return url
            elif task_status != "processing":
                logging.info(f"GOAPI_FLUX: task status {task_status}!", response.json())
            time.sleep(5)
        else:
            time.sleep(5)

    raise Exception("goapi_flux1 : task polling timed out")


@errors.log_ctx_errors
def generate_images(
    prompts,
    reference_images,
    width=None,
    height=None,
    negative_prompt="bad hands",
    model="Qubico/flux1-dev",
):
    """
    Generate images using the Flux API.

    Args:
        prompts (list[str]): List of prompts for image generation.
        reference_images (list[list[str]]): List of lists of reference images for each prompt.
        api_key (str): Your GoAPI Key.
        model (str, optional): Model to use for generation. Defaults to "Qubico/flux1-dev".
        task_type (str, optional): Type of task. Defaults to "txt2img".

    Returns:
        list[str]: List of generated image URLs.
    """

    # Create tasks in parallel
    api_key = get_token()
    task_ids = []
    errors = []

    for p, r in zip(prompts, reference_images):
        (tid, err) = create_task(
            p,
            r,
            api_key,
            model=model,
            negative_prompt=negative_prompt,
            width=width,
            height=height,
        )
        task_ids.append(tid)
        errors.append(err)

    api_key = get_token()
    urls = [None] * len(task_ids)

    with ThreadPoolExecutor() as executor:
        results = list(
            executor.map(get_task_result, task_ids, list(range(len(task_ids))))
        )

        for r in results:
            urls.append(r[0])
            errors.append(r[1])

    return urls, errors


@errors.raise_ctx_errors
def convert_image_to_videos(engine, images, prompts):

    generated_videos = None

    with ThreadPoolExecutor() as executor:
        generated_videos = list(
            executor.map(img_to_video, [engine] * len(images), images, prompts)
        )

    return generated_videos


@errors.raise_ctx_errors
def img_to_video(engine, img, prompt):

    m, t = None, None

    if engine == "goapi_wanx":
        m = "Qubico/wanx"
        t = "img2video-14b"

    if engine == "goapi_hailuo":
        m = "i2v-01-live"
        t = "img2video"

    if engine == "goapi_hunyuan":
        m = "Qubico/hunyuan"
        t = "fastvideo-txt2video"

    if not m or not t:
        return None

    url = "https://api.goapi.ai/api/v1/task"

    payload = {
        "model": m,
        "task_type": t,
        "input": {"image": img, "prompt": prompt, "aspect_ratio": "9:16"},
    }

    h = {"X-API-Key": get_token(), "Content-Type": "application/json"}
    response = requests.request("POST", url, headers=h, data=json.dumps(payload))
    res = response.json()

    tid = res["data"].get("task_id")
    logging.info(f"GOAPI-IMG-TO-VIDEO: task id : {tid}")

    results = get_task_result(tid, None)

    return results


if __name__ == "__main__":
    # prompts = ["a little cat"]
    # reference_images = [ch]
    # api_key = X_API_KEY

    # generated_images = generate_images(prompts, reference_images, api_key)
    # logging.info(generated_images)  # List of generated image URLs

    # res = img_to_video(
    #    "goapi_wanx",
    #    "https://baasha-drafts.us-east-1.linodeobjects.com/42aa7515-7152-4d2a-9989-d46db13d20a9.1/7c060c7b-9891-47c7-ada7-79f62cf1b915_2.png",
    #    "horizontal pan",
    # )

    res = get_task_result("a08e79d5-37f2-439d-a714-6029f8d699f1", None, get_token())

    logging.info(f"midjourney {res}")
