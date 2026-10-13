import base64
from uuid import uuid4
import boto3
import json
import time

import requests
import shutil
import os
import sys
from botocore.exceptions import NoCredentialsError
from pathlib import Path, PurePath
from PIL import Image
from typing import List, Set, Dict, Tuple, Optional, Union

from baasha_pipeline import chatbot as Chatbot
from baasha_pipeline.prompts.splitters import markdown_parse
from .configs import app_config
from typing import List, Optional, Dict, Union
from . import errors
from . import object_storage
from .logger import logging

MJ_IMAGINE_V2_URL = "https://api.goapi.ai/mj/v2/imagine"
MJ_FETCH_V2_URL = "https://api.goapi.ai/mj/v2/fetch"
MJ_UPSCALE_V2_URL = "https://api.goapi.ai/mj/v2/upscale"
IMG_GEN_TIMEOUT_SEC = 1200
IMG_UPSCALE_TIMEOUT_SEC = 1200
SLEEP_TIME_BETWEEN_CHECKS = 60
DEFAULT_STYLE_PRESET = "photorealistic"

def get_placeholder_url():
    return object_storage.build_asset_url("images/image.png")

PLACEHOLDER_URL = get_placeholder_url()


@errors.raise_ctx_errors
def get_token():
    return app_config.get().get("auth").get("goapi_midjourney_key")


@errors.raise_ctx_errors
def get_headers():
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-API-KEY": "{X_API_KEY}".format(X_API_KEY=get_token()),
    }


# Generate Images by calling GoAPI midjoruney API. The worklfow involves calling the /imagine API
# to enqueue image generation jobs, monitor the jobs for completion using the /fetch API
# Once the image samples are ready, we enqueue upsample jobs for the API. We monitor these for completion
# using the /fetch API and then retreive the Image URLs from the upscale jobs
@errors.raise_ctx_errors
def generate_images(
    image_prompts: Union[str, str],
    negative_prompt: str,
    out_dir: str,
    chatbot,
    callback=None,
) -> List[Dict[str, Union[str, bool, int]]]:
    imagine_task_ids, prompts, logs = enqueue_image_generations(
        image_prompts, negative_prompt, chatbot
    )

    imagine_results = {}
    wait_for_task_completion(
        imagine_task_ids,
        IMG_GEN_TIMEOUT_SEC,
        SLEEP_TIME_BETWEEN_CHECKS,
        imagine_results,
    )

    upsample_task_ids = enqueue_upsample_tasks(
        imagine_task_ids, imagine_results, image_prompts, ask_image_to_upscale, chatbot
    )
    upsample_results = {}
    wait_for_task_completion(
        upsample_task_ids,
        IMG_UPSCALE_TIMEOUT_SEC,
        SLEEP_TIME_BETWEEN_CHECKS,
        upsample_results,
    )

    i = 0
    os.makedirs(out_dir, exist_ok=True)
    files = []
    uid = uuid4()
    errors = [False] * len(upsample_task_ids)

    for idx, upsample_task_id in enumerate(upsample_task_ids):

        upsample_result = upsample_results.get(upsample_task_id, {}).get("image_url")
        temp_image_urls = imagine_results.get(upsample_task_id, {}).get(
            "temporary_image_urls"
        )

        if not upsample_result or upsample_task_id.startswith("placeholder"):
            errors[idx] = True

        if not upsample_result and len(temp_image_urls) > 0:
            upsample_result = temp_image_urls[0]

        filepath = save_image_file(
            upsample_result, file_name=f"{out_dir}/{uid}_{i}.png"
        )
        if callback:
            callback(i, upsample_result)

        files.append(filepath)
        i += 1

    object_store_paths = sync_directory_to_object_store(
        out_dir, files, "baasha-drafts", PurePath(out_dir).name
    )
    return object_store_paths, prompts, errors, logs


@errors.raise_ctx_errors
def enqueue_image_generations(
    image_prompts: Union[str, str], negative_prompt: str, chatbot: Chatbot.ChatInterface
) -> List[str]:
    task_ids = []
    prompts = []
    logs = []

    for idx, (image_prompt, ref) in enumerate(image_prompts):
        task_id, prompt, log = generate_image(
            chatbot, image_prompt, negative_prompt, ref
        )

        prompts.append(prompt)
        if task_id:
            logs.append({"log": log, "task_id": task_id})
            task_ids.append(task_id)
        else:
            logs.append({"log": log, "task_id": "placeholder"})
            logging.info("GoAPI-enqueue-image: adding a placeholder image")
            task_ids.append(f"placeholder-{idx}")

    return task_ids, prompts, logs


@errors.raise_ctx_errors
def generate_image(
    chatbot: Chatbot.ChatInterface,
    image_prompt: str,
    negative_prompt: str,
    character_url=None,
    retry=2,
) -> str:
    log = []
    full_prompt = build_full_prompt(image_prompt, negative_prompt, character_url)
    body = {
        "prompt": full_prompt,
        # "aspect_ratio": "16:9",
        "process_mode": "fast",
        "webhook_endpoint": "",
        "webhook_secret": "",
    }

    response = requests.post(
        MJ_IMAGINE_V2_URL,
        headers=get_headers(),
        json=body,
    )

    if response.status_code != 200:
        log.append({"status": "error", "error": response.text})
        if retry > 0:
            timeout = None
            new_prompt = None
            fix_error = identify_error_fix(image_prompt, response.text, chatbot)

            if fix_error:
                timeout = fix_error[0]
                new_prompt = fix_error[1]

            if timeout:
                time.sleep(min(timeout, 60))

            if new_prompt or timeout:
                log.append(
                    {"status": "retry", "timeout": timeout, "new_prompt": new_prompt}
                )

                tid, p, rlog = generate_image(
                    chatbot,
                    new_prompt or image_prompt,
                    negative_prompt,
                    character_url,
                    retry - 1,
                )

                log.extend(rlog)
                return tid, p, log

        log.append({"status": "no-retry"})
        return None, full_prompt, log

    data = response.json()

    log.append({"status": "queued" if data["status"] == "success" else "not queued"})

    return (
        (data["task_id"], full_prompt, log)
        if data["status"] == "success"
        else (None, full_prompt, log)
    )


@errors.raise_ctx_errors
def build_full_prompt(
    image_prompt: str, negative_prompt: str, character_url=None
) -> str:
    full_prompt = (
        str(image_prompt) + " --no " + str(negative_prompt) + " --v 6 --ar 4:7"
    )

    if character_url != None:
        full_prompt = full_prompt + " --cref " + str(character_url)

    return full_prompt


@errors.raise_ctx_errors
def wait_for_task_completion(task_ids, max_timeout, wait_interval, results):
    pending = []
    for tid in task_ids:
        if tid.startswith("placeholder"):
            results[tid] = {"image_url": PLACEHOLDER_URL}

        elif tid == "failed":
            logging.error("Image creation task failed for task id %s", tid)
        else:
            body = {"task_id": tid}
            response = requests.post(MJ_FETCH_V2_URL, json=body)

            if response.status_code != 200:
                logging.error(
                    f"GoAPI-task-completion: Non-200 response for fetch status: "
                    + str(response.text)
                )
                logging.info(f"GoAPI-task-completion: adding a placeholder image")

                results[tid] = {"image_url": PLACEHOLDER_URL}
                continue

            # logging.info("FETCH RESPONSE: %s", response.json())
            data = response.json()
            if data["status"] == "finished":
                logging.info("Task %s finished successfully", tid)
                results[tid] = data["task_result"]
            else:
                logging.info(
                    "Task %s is still not finished, current status %s ",
                    tid,
                    data["status"],
                )
                pending.append(tid)

    if len(pending) > 0 and max_timeout > 0:
        logging.info("Sleeping for %s before retrying.", wait_interval)
        time.sleep(wait_interval)
        return wait_for_task_completion(
            pending, max_timeout - wait_interval, wait_interval, results
        )
    elif len(pending) > 0:
        logging.error(
            "Could not wait long enough for %s tasks to complete. Returning results {}.",
            len(pending),
            len(results),
        )
        for p in pending:
            results[p] = {"image_url": PLACEHOLDER_URL}
    return results


@errors.raise_ctx_errors
def enqueue_upsample_tasks(task_ids, results, prompts, choose_image, chatbot):
    upsample_task_ids = []

    for idx, tid in enumerate(task_ids):
        if not tid or tid.startswith("placeholder"):
            upsample_task_ids.append("placeholder")
            continue

        imagine_img = results.get(tid).get("image_url")
        val = choose_image(imagine_img, prompts[idx][0], chatbot)
        index = str(val) if val else "4"

        data = {
            "origin_task_id": tid,
            "index": index,
            "webhook_endpoint": "",
            "webhook_secret": "",
        }
        response = requests.post(MJ_UPSCALE_V2_URL, headers=get_headers(), json=data)
        data = response.json()
        if response.status_code == 200:
            upsample_task_ids.append(data["task_id"])
        else:
            logging.error(
                f"GoAPI-upsample-tasks: Failed to enqueue upscale task , unexpected status code %s, %s",
                response.status_code,
                data,
            )
            logging.info("GoAPI-upsample-tasks: adding a placeholder image")
            upsample_task_ids.append(f"placeholder-{idx}")

    return upsample_task_ids


@errors.raise_ctx_errors
def save_image_file(url, file_name):
    """Download an image from a URL and save it to a local file.

    Args:
        url (str): The URL of the image to download.
        out_dir (str): The directory that contains the file
        file_name (str): The name of the local file to save the image to.
    """

    if "baasha" in url:
        return url

    # Send a GET request to the image URL
    response = requests.get(url)
    # Check if the request was successful (status code 200)
    if response.status_code == 200:
        # Open a local file for writing in binary mode
        with open(file_name, "wb") as f:
            # Write the contents of the response to the local file
            f.write(response.content)

        logging.info(f"Image '{url}' saved to '{file_name}'.")
        return file_name
    else:
        logging.error(f"Failed to download image from {url} ({response.status_code}).")
        logging.info(f"GoAPI-save-image: adding placeholder image")
        return PLACEHOLDER_URL


@errors.raise_ctx_errors
def sync_directory_to_object_store(local_directory, files, s3_bucket, s3_prefix=""):
    # Create an  S3 client
    cluster = app_config.get().get("auth").get("object_storage").get("cluster")
    s3 = boto3.client(
        "s3",
        aws_access_key_id=app_config.get()
        .get("auth")
        .get("object_storage")
        .get("access_key"),
        aws_secret_access_key=app_config.get()
        .get("auth")
        .get("object_storage")
        .get("secret_key"),
        endpoint_url="https://" + cluster,
    )

    # Iterate through all the files in the local directory
    s3.put_object(Bucket=s3_bucket, Key=f"{s3_prefix}/", Body="")
    success = False
    obj_urls = []

    for f in files:
        if "https" in f:
            # url
            obj_urls.append(f)
            continue

        relative_path = os.path.relpath(f, local_directory)
        s3_key = f"{s3_prefix}/{relative_path}" if s3_prefix else relative_path

        # Upload the file to S3
        s3.upload_file(f, s3_bucket, s3_key, ExtraArgs={"ACL": "public-read"})
        logging.info(f"Uploaded {f} to S3://{s3_bucket}/{s3_key}")
        obj_urls.append(f"https://{s3_bucket}.{cluster}/{s3_key}")
        success = True

    if success:
        shutil.rmtree(local_directory)

    return obj_urls


choose_image_to_upscale = """Given an image description and a collage of 4 images, can you select a single image which is most appropriate for the given image description. While comparing take into consideration the quality, style, relevancy, character focus, sharpness and aesthetics and select the image which best suits all these traits. The images are numbered from 1 to 4 from left to right. Output the position of the single selected image and short explanation for the choice as JSON enclosed in ```json with keys position, explain

Example Output: { "position": "1", "explain": "character focused, super sharp" }

Image Description + Image:
"""


@errors.log_ctx_errors
def ask_image_to_upscale(image_url, prompt, chatbot):
    response = requests.get(image_url)

    response.raise_for_status()

    prompt = Chatbot.Img(_bytes=response.content, text=choose_image_to_upscale + prompt)
    res = chatbot.fetch_text(prompt)

    out = markdown_parse(res)
    val = json.loads(out)

    logging.info(f"GoAPI-select-upscale-image: {out}")
    index = val.get("position")

    if int(index) > 0 and int(index) <= 4:
        return str(index)

    return "1"


fix_api_error_prompt = """Given an error message and input prompt, can you provide the right fix for the error. You can only identify two types of error `API-RATE-LIMITING` and `BANNED-WORDS`. \n Fix for respective errors :
    - API-RATE-LIMITING: give the required timeout in seconds to wait before retrying. Output a JSON with key as timeout enclosed in ```json.
    - BANNED-PROMPT: fix the given prompt/text by removing the banned/nswf/18+ words, while keeping the meaning same. Output a JSON with key as prompt enclosed in ```json.

Prompt:
"""


@errors.log_ctx_errors
def identify_error_fix(prompt, error_msg, chatbot):
    input = fix_api_error_prompt + prompt + f"\nError Message: {error_msg}"
    res = chatbot.fetch_text(input)

    out = markdown_parse(res)
    val = json.loads(out)

    logging.info(f"GoAPI-fix-error: {out}")

    return (val.get("timeout"), val.get("prompt"))


if __name__ == "__main__":
    n = "bad hands"

    p = [
        (
            "person with blood on face",
            None,
        )
    ]

    chatbot = Chatbot.ChatInterface("gemini-1.5-flash")
    chatbot.new_conversation()
    res = generate_images(p, n, ".", chatbot)
    chatbot.delete_conversation()
    logging.info(f"midjourney {res}")
