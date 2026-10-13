from .. import object_storage
from . import splitters

import requests

EDITABLE_LABELS = ["title", "count"]


def process_and_populate_prompt(prompt_dict, data):
    prompt = prompt_dict.get("prompt")

    if not prompt:
        return None, None

    for l in prompt_dict.get("editable_labels", []):
        if l in EDITABLE_LABELS and data.get(l):
            prompt = prompt.replace(f"<{l}>", str(data.get(l)))

    splitter_fn = lambda x: x
    if prompt_dict.get("splitter"):
        s = prompt_dict.get("splitter")
        if s == "basic_newline":
            splitter_fn = splitters.basic_newline_splitter
        elif s == "basic_json":
            splitter_fn = splitters.json_splitter

    def splitter_with_prefix_suffix(x):
        s = splitter_fn(prompt_dict)(x)
        prefix = data.get("prefix", "")
        suffix = data.get("suffix", "")

        if not prefix and not prefix:
            return s

        if prefix:
            prefix = prefix + ", "
        if suffix:
            suffix = ", " + suffix

        return list(map(lambda y: prefix + y + suffix, s))

    return prompt, splitter_with_prefix_suffix


def get_image_gen_prompt_from_storage(key, data):
    url = object_storage.get_object_url_from_key(
        object_storage.ASSETS_PROMPT_IMAGE_GEN, key
    )

    if not url:
        return None, None

    req = requests.get(url)
    # print(req.json())
    prompt_dict = req.json()
    return process_and_populate_prompt(prompt_dict, data)


def get_script_gen_prompt_from_storage(key, data):
    url = object_storage.get_object_url_from_key(
        object_storage.ASSETS_PROMPT_SCRIPT_GEN, key
    )

    if not url:
        return None, None

    req = requests.get(url)
    prompt_dict = req.json()
    return process_and_populate_prompt(prompt_dict, data)
