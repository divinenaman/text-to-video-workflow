import base64
import boto3
import json
import logging
import time

import requests
import shutil
import os
import sys
from botocore.exceptions import NoCredentialsError
from pathlib import Path, PurePath
from PIL import Image
from .configs import app_config
import time

LOG_FILE = "/tmp/baasha_stability_generator.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler(sys.stdout)],
)

TEXT_TO_IMAGE_URL = (
    "https://api.stability.ai/v1/generation/stable-diffusion-xl-1024-v1-0/text-to-image"
)
UPSCALE_IMAGE_URL = (
    "https://api.stability.ai/v1/generation/esrgan-v1-x2plus/image-to-image/upscale"
)
ANIMATE_IMAGE_URL = "https://api.stability.ai/v2alpha/generation/image-to-video"


def get_token():
    return app_config.get().get("auth").get("stability_ai_key")


def get_headers():
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": "Bearer {STABILITY_API_KEY}".format(
            STABILITY_API_KEY=get_token()
        ),
    }


def generate_images(
    image_prompts, negative_prompt, out_dir, style_preset="photographic"
):
    """
    Generates images for a list of image prompts using Stability AI and stores them in an Object Storage bucket.

    :param image_prompts: List of image prompts
    :negative_prompt: Negative prompts to be applied for each image
    :out_di: Local storage directory
    :style_preset: for Stability AI style presets
    :return: list of image URLs store in Object Store
    """
    i = 0
    data = []
    for image_prompt in image_prompts:
        out_file = f"{i}"
        data.append({out_file: image_prompt, "upscaled": False})
        i += 1
        try:
            generate_image(
                image_prompt,
                negative_prompt,
                out_dir,
                out_file,
                style_preset=style_preset,
                steps=50,
            )
        except Exception as e:
            logging.error(
                "Failed to generate image {} for prompt {}".format(i, image_prompt),
                exc_info=e,
            )
    with open(f"{out_dir}/data.json", "w") as df:
        json.dump(data, df)

    image_urls = sync_directory_to_object_store(
        out_dir, "baasha-drafts", PurePath(out_dir).name
    )
    return image_urls


def generate_image(
    image_prompt,
    negative_prompt,
    out_dir,
    out_file,
    style_preset="photographic",
    width=768,
    hieght=1344,
    steps=40,
    cfg_scale=5,
    seed=int(time.time()),
    samples=1,
):
    body = {
        "steps": steps,
        "width": width,
        "height": hieght,
        "seed": seed,
        "cfg_scale": cfg_scale,
        "samples": samples,
        "style_preset": style_preset,
        "text_prompts": [
            {"text": image_prompt, "weight": 1},
            {"text": negative_prompt, "weight": -1},
        ],
    }

    response = requests.post(
        TEXT_TO_IMAGE_URL,
        headers=get_headers(),
        json=body,
    )

    if response.status_code != 200:
        raise Exception("Non-200 response: " + str(response.text))

    data = response.json()
    save_image_file(data, out_dir, file_name=f"{out_dir}/{out_file}.png")


def save_image_file(data, out_dir, file_name):
    # make sure the out directory exists
    if not os.path.exists(out_dir):
        os.makedirs(out_dir)
    for i, image in enumerate(data["artifacts"]):
        with open(file_name, "wb") as f:
            f.write(base64.b64decode(image["base64"]))


def upscale_images(source_images, out_dir):
    """
    Upscales images and uploads them to Object Storage

    :param source_images:
    :param out_dir:
    :return: array of image urls
    """
    upscaled_images = []
    for source_image in source_images:
        try:
            outfile = f"upscale_{Path(source_image).stem}"
            upscale_image(source_image, out_dir, outfile)
            upscaled_images.append(outfile)
            os.remove(source_image)
        except Exception as e:
            logging.error("Failed to upscale image {}".format(source_image), exc_info=e)

    image_urls = sync_directory_to_object_store(
        out_dir, "baasha-drafts", PurePath(out_dir).name
    )
    return image_urls


def upscale_image(source_image, out_dir, out_file):
    img = Image.open(source_image)
    response = requests.post(
        UPSCALE_IMAGE_URL,
        headers={
            "Accept": "application/json",
            "Authorization": "Bearer {STABILITY_API_KEY}".format(
                STABILITY_API_KEY=get_token()
            ),
        },
        files={"image": open(source_image, "rb")},
        data={"height": img.height},
    )

    if response.status_code != 200:
        raise Exception("Non-200 response: " + str(response.text))

    data = response.json()
    save_image_file(data, out_dir, file_name=f"{out_dir}/{out_file}.png")


def animate_image(in_file):

    headers = {
        "authorization": "Bearer {}".format(get_token()),
    }

    # Prepare form data with image and other fields
    files = {"image": ("image.png", open(f"{in_file}", "rb"), "image/png")}
    data = {
        "seed": "0",
        "cfg_scale": "2.5",
        "motion_bucket_id": "40",
        "width": "576",
        "height": "1024",
    }

    response = requests.post(ANIMATE_IMAGE_URL, headers=headers, files=files, data=data)
    print(response.text)
    return json.loads(response.text)


def get_animate_image(task_id, out_file):
    headers = {
        "authorization": "Bearer {}".format(get_token()),
        "accept": "application/json",
    }
    attempts = 0
    while attempts < 5:
        time.sleep(10)
        response = requests.get(
            "{}/result/{}".format(ANIMATE_IMAGE_URL, task_id),
            headers=headers,
            stream=True,
        )
        if response.status_code == 200:
            data = json.loads(response.text)
            if data["finishReason"] == "SUCCESS":
                print("animated")
                with open(out_file, "wb") as of:
                    of.write(base64.b64decode(data["video"]))
            break
        elif response.status_code == 202:
            print("Not giving up!")
            attempts += 1
        else:
            print("response is {}".format(response.status_code))
            break


def sync_directory_to_object_store(local_directory, s3_bucket, s3_prefix=""):
    # Create an S3 client
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
    for root, dirs, files in os.walk(local_directory):
        for file in files:
            local_path = os.path.join(root, file)
            relative_path = os.path.relpath(local_path, local_directory)
            s3_key = f"{s3_prefix}/{relative_path}" if s3_prefix else relative_path

            try:
                # Upload the file to S3
                s3.upload_file(
                    local_path, s3_bucket, s3_key, ExtraArgs={"ACL": "public-read"}
                )
                print(f"Uploaded {local_path} to S3://{s3_bucket}/{s3_key}")
                success = True
                if not s3_key.endswith("data.json"):
                    obj_urls.append(f"https://{s3_bucket}.{cluster}/{s3_key}")
            except NoCredentialsError:
                print("Credentials not available")
                success = False
                break
    if success:
        shutil.rmtree(local_directory)
    return obj_urls
