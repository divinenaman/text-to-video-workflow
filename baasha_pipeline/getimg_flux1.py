from io import BytesIO
from uuid import uuid4
from . import errors, object_storage
from .logger import logging
from .configs import app_config
import time
import requests
from . import goapi_flux
import json
import base64
import os
from huggingface_hub import InferenceClient

URL_IMAGE_TO_IMAGE = "https://fal.run/fal-ai/flux/dev/image-to-image"
URL = "https://fal.run/fal-ai/flux/schnell"

def get_fal_key():
    return app_config.get().get("auth").get("fal_token")

def get_headers():
    key = get_fal_key()
    return {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:127.0) Gecko/20100101 Firefox/127.0",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.5",
        "Content-Type": "application/json",
        "Connection": "keep-alive",
        "Authorization": f"Key {key}",
    }

def get_placeholder_image():
    return object_storage.build_asset_url("images/image.png")

PLACEHOLDER_IMAGE = get_placeholder_image()


def generate_images(
    prompts,
    refs,
    width=None,
    height=None,
    callback=None,
    negative_prompt=None,
    image_engine=None,
):
    try:
        res = []

        if image_engine == "goapi_flux1":
            res = goapi_flux.generate_images(
                prompts,
                refs,
                width=width,
                height=height,
                negative_prompt=negative_prompt,
            )

        elif image_engine in ["segmind_flux1", "hf_flux1", "getimg_flux1", "fal_flux1"]:

            fn = generate_using_hf

            if image_engine == "segmind_flux1":
                fn = generate_using_segmind
            elif image_engine == "getimg_flux1":
                fn = get_img_ai_api_call
            elif image_engine == "fal_flux1":
                fn = generate_image

            def cb(im):
                if not im:
                    im = PLACEHOLDER_IMAGE
                if callback:
                    callback(len(res), im)
                res.append(im)

            for p, r in zip(prompts, refs):
                logging.info(f"starting img gen using {image_engine} => {p}")
                url = fn(p, ref=r, width=width, height=height)
                logging.info(f"ending img-gen using {image_engine}")

                res.append(url)
                # t = other_utils.threaded_task("GET_IMG_FLUX1", fn, cb, p, r)
                # t.start()
                # tasks.append(t)
                time.sleep(20)

            # for t in tasks:
            #    t.join()

        res = list(map(lambda x: PLACEHOLDER_IMAGE if x == None else x, res))
        return res
    except Exception as e:
        logging.error(f"GetImgFlux1: generate_images: {e}")
        return [PLACEHOLDER_IMAGE] * len(prompts)


def generate_image(p, ref=None):
    response = None
    try:
        data = {"prompt": p, "image_size": "portrait_16_9"}
        url = URL
        if ref:
            data["image_url"] = ref
            url = URL_IMAGE_TO_IMAGE

        response = requests.post(url, headers=get_headers(), json=data).json()
        img = response.get("images")[0]["url"]
        return img
    except Exception as e:
        logging.error(f"GetImgFlux1: generate_image: {e} \t {response}")
        return None


def get_img_ai_api_call(p, ref=None):
    url = "https://getimg.ai/api/pipelines/flux-v1-dev"
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:127.0) Gecko/20100101 Firefox/127.0",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Content-Type": "application/json",
        "Origin": "https://getimg.ai",
        "Connection": "keep-alive",
        "Referer": "https://getimg.ai/text-to-image",
        "Cookie": "",
    }

    data = {
        "tool": "generator",
        "style": "photorealism",
        "prompt": p,
        "width": 720,
        "height": 1280,
        "num_images": 1,
    }

    if ref:
        data["image_url"] = ref
        data["strength"] = 0.90

    response = requests.post(url, headers=headers, data=json.dumps(data))

    try:
        res = response.json()
        logging.info(res)
        return res[0]["images"][0]["jpegUrl"]
    except Exception as e:
        logging.error(e)
        return None


@errors.log_ctx_errors
def generate_using_hf(p, width=None, height=None, ref=None, headers={}, retry=2):

    token = app_config.get().get("auth").get("hf_token")
    client = InferenceClient(
        provider="hf-inference",
        api_key=token,
    )

    image = client.text_to_image(
        prompt=p,
        model="black-forest-labs/FLUX.1-dev",
        width=width or 1080,
        height=height or 1920,
    )

    image_bytes = BytesIO()
    image.save(image_bytes, format="PNG")  # You can change the format as needed
    image_bytes = image_bytes.getvalue()

    public_url = object_storage.upload_data(
        object_storage.ASSETS_IMG_BUCKET,
        image_bytes,
        f"{uuid4()}_hf_flux.jpg",
        object_storage.ACL_PUBLIC,
    )
    return public_url


def to_b64(img_path):
    with open(img_path, "rb") as image_file:
        data = image_file.read()
    return base64.b64encode(data).decode("utf-8")


@errors.log_ctx_errors
def generate_using_segmind(p, ref=None, retry=1):
    print(p)
    api_key = app_config.get().get("auth").get("segmind_api_key", "")
    url = "https://api.segmind.com/v1/fast-flux-schnell"
    url_ref = "https://api.segmind.com/v1/flux-pulid"

    data = {
        "prompt": p,
        "steps": 25,
        "samples": 1,
        "seed": 29122959,
        "denoise": 1,
        "scheduler": "simple",
        "sampler_name": "euler",
        "base64": False,
        "height": 1280,
        "width": 720,
        "num_steps": 20,
        "output_quality": 80,
        "num_outputs": 1,
    }

    if ref:
        url = url_ref
        data["id_weight"] = 1.05
        data["main_face_image"] = ref  # to_b64(img_path)
        data["denoise"] = 0.88
        data["output_format"] = "png"

    response = requests.post(url, json=data, headers={"x-api-key": api_key})

    if response.status_code == 429 and retry > 0:
        # rate limited
        time.sleep(10)
        return generate_using_segmind(p, ref, retry - 1)

    response.raise_for_status()

    content = response.content
    ext = "jpg"

    if ref:
        ext = "png"

    content_path = os.path.join(
        os.path.dirname(__file__), "tmp", f"flux_gen_{uuid4()}.{ext}"
    )
    with open(content_path, "wb") as f:
        f.write(content)

    public_url = object_storage.upload_file(
        object_storage.ASSETS_IMG_BUCKET,
        content_path,
        os.path.basename(content_path),
        object_storage.ACL_PUBLIC,
    )

    return public_url


if __name__ == "__main__":
    ch = object_storage.build_asset_url("images/placeholder_img_prison_mick.jpg")
    t = generate_images(
        [
            "Ratan Tata, a remarkable business magnate, embodies an aura of authority and distinction. His strong facial structure, accentuated by a prominent jawline, is complemented by a mature gaze, reflecting a mix of determination and wisdom. Tata's gray or graying hair, often neatly trimmed, adds to his dignified appearance. His attire, typically formal and polished, reflects his professional stature and business acumen. Noticeable are his intelligent and expressive eyes, conveying a desire to make a positive impact. Tata's whole demeanor exudes confidence, professionalism, and a commitment to innovation, encapsulating his unique and commanding presence."
        ],
        [None],
        callback=None,
        image_engine="hf_flux1",
    )

    print("flux1 -> ", t)
