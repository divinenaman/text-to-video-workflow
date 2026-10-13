from . import utils, other_utils
from . import chatbot as BaashaChat
import re
from .configs import app_config
from .prompts import splitters as PromptSplitters
from .prompts.script_gen import v2 as ScriptGenPrompts
from .prompts.image_gen import v4 as ImageGenPrompts
from . import errors
from .logger import logging


@errors.raise_ctx_errors
def split_text(text):
    regex = '.*prompt.*:.*"(?P<prompt>.*)"'
    matched = re.finditer(regex, text)
    res = []
    for m in matched:
        d = m.groupdict()
        if d.get("prompt") != None:
            res.append(d.get("prompt"))
    return res


@errors.raise_ctx_errors
def process_script(content):
    regex = '.*script.*:.*"(?P<script>[\s\S]*)"'
    matched = re.finditer(regex, content, re.IGNORECASE)

    for m in matched:
        d = m.groupdict()
        if d.get("script") != None:
            return d.get("script")

    return None


@errors.raise_ctx_errors
def generate_video_data(
    topic,
    content=None,
    image_prompts_list=None,
    image_urls=None,
    image_ref_url=None,
    bgm_name=None,
    voice_name="default",
    tts_toolkit=None,
    config=app_config.get(),
):
    result = {
        "title": topic,
        "text": [],
        "images": [],
        "video": "",
        "audios": [],
        "bgm": ("", 0),
        "image_prompts_list": [],
        "description": "#shorts #content #amazing #ai #openai #youtube",
        "keywords": "#shorts,#content,#amazing,#ai,#openai,#youtube,"
        + config.get("default_keywords"),
        "privacyStatus": "public",
        "onScreenTitle": "",
        "timepoints_map": {},
        "is_word_timepoints": False,
        "category": 24,
    }
    threads_store = {
        "content": None,
        "image_prompts_list": [],
        "images": [],
        "bgm": None,
        "audios": [],
    }
    queue = {
        "text": [],
        "image_prompts_list": [],
        "images": [],
        "audios": [],
        "bgm": [],
    }

    chatbot_ins = None

    def cb(key, applyFns=[]):
        def fn(data):
            for f in applyFns:
                data = f(data)
            logging.info(f"HuggingPipeline: {key} data queued")
            queue[key].append(data)

        return fn

    if not content:
        chatbot = BaashaChat.ChatInterface("gemini")
        chatbot.new_conversation()
        chatbot_ins = chatbot

        gen_content_prompts = ScriptGenPrompts.ask_for_script_on_topic_with_few_shots(
            topic
        )
        content_gen_splitter = lambda x: PromptSplitters.json_splitter(
            {"json_keys": ["Script"]}
        )(x)[0]
        threads_store["content"] = other_utils.threaded_task(
            "CONTENT_GEN",
            chatbot.fetch_text,
            cb("text", [content_gen_splitter, other_utils.process_raw_text]),
            gen_content_prompts,
        )
        threads_store["content"].start()
    else:
        if isinstance(content, list):
            result["text"] = content
        else:
            result["text"] = other_utils.process_raw_text(content)

    if not image_prompts_list and not image_urls:
        image_prompts_list = ImageGenPrompts.character_switched_prompts(topic)
        logging.info(f"HuggingPipeline: image prompts generated {image_prompts_list}")
    else:
        result["image_prompts_list"] = image_prompts_list

    # TODO: add image generation logic if need

    for t in threads_store["images"]:
        t.join()

    for _, img in sorted(queue["images"], key=lambda x: x[0]):
        result["images"] = result["images"] + img

    if image_urls:
        result["images"] = result["images"] + image_urls

    if len(threads_store["images"]) > 0:
        logging.info(f"HuggingPipeline: images generated")

    if not bgm_name:
        bgm_name = "powerful-gym-rock-121485.mp3"

    threads_store["bgm"] = other_utils.threaded_task(
        "BGM_FETCH", other_utils.get_bgm_from_name, cb("bgm"), bgm_name
    )
    threads_store["bgm"].start()

    if threads_store["content"]:
        threads_store["content"].join()

    for d in queue["text"]:
        result["text"] = result["text"] + d

    task = other_utils.indexed_threaded_task(
        "TTS",
        0,
        other_utils.text_to_speech_as_single_audio,
        cb("audios"),
        result["text"],
        voice_name,
        tts_toolkit,
    )
    task.start()
    threads_store["audios"].append(task)

    audios = []
    timepoint_map = {}
    is_word_timepoints = False

    for t in threads_store["audios"]:
        t.join()

    for _, data in sorted(queue["audios"], key=lambda x: x[0]):
        audios = audios + data[0]
        timepoint_map.update(data[1])
        is_word_timepoints = data[2]

    result["audios"] = audios
    result["timepoints_map"] = timepoint_map
    result["is_word_timepoints"] = is_word_timepoints

    threads_store["bgm"].join()

    for d in queue["bgm"]:
        if d:
            result["bgm"] = d

    if chatbot_ins:
        chatbot_ins.delete_conversation()

    return result


if __name__ == "__main__":

    out = generate_video_data("Air Jordans")

    print(out)
