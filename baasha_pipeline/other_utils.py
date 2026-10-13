from time import time
from . import utils, object_storage, errors, vosk_toolkit
import os
from typing import *
import json
from uuid import uuid4
from threading import Thread
from .configs import remotion_ui_confs, app_config
from .logger import logging
import urllib.parse
import base64

file_dir = os.path.dirname(__file__)


@errors.raise_ctx_errors
def process_raw_text(text: str) -> List[str]:
    text = list(map(lambda x: x.strip(), text.splitlines()))
    text = list(filter(lambda x: x != "", text))
    return text


@errors.raise_ctx_errors
def text_to_speech(
    text: List[str],
    voice_key: str,
    tts_toolkit,
    config=app_config.get(),
    voice_description: Optional[str] = None,
) -> List[Tuple[int, str, str]]:
    audio_info, is_word_timepoints = utils.text_to_speech(
        config, text, voice_key, tts_toolkit, voice_description=voice_description
    )
    audios, local_audios, timepoint_map = utils.map_audio_timepoints(audio_info)

    audios = list(
        map(
            lambda t: (t[1], int(round(utils.get_media_duration(local_audios[t[0]])))),
            enumerate(audios),
        )
    )

    return audios, timepoint_map, is_word_timepoints


def cmp_word(w1, w2):
    i = 0
    for w in w1:
        if i >= len(w2) or w != w2[i]:
            break
        i += 1

    return len(w2) - i <= 2


@errors.raise_ctx_errors
def text_to_speech_as_single_audio(
    text, voice_key=None, tts_toolkit=None, config=app_config.get()
):
    single_text = " ".join(text)

    logging.info(f"single audio text : {single_text}")

    (audios, timepoint_map, is_word_timepoints) = text_to_speech(
        [single_text], voice_key, tts_toolkit, config
    )

    (audio_file, _) = audios[0]

    (splits, timepoint_new_map) = make_audio_split(text, audio_file, timepoint_map)

    return splits, timepoint_new_map, is_word_timepoints


@errors.raise_ctx_errors
def make_audio_split(text, audio_file, timepoint_map):
    timepoints = timepoint_map[audio_file]
    new_timepoint_map = {}

    splits = []
    st = 0
    last_text_time = 0

    for idx, t in enumerate(text):
        sen_words = list(filter(lambda x: x != "", t.strip().split(" ")))

        end = len(sen_words) - 1
        while end > 0 and not sen_words[end].isalpha():
            end -= 1

        last_word = sen_words[end]

        v = 0
        v2 = 0
        for i, w in enumerate(timepoints[st:]):

            if (
                last_word.lower().find(w[0].lower()) != -1
                and len(last_word) - len(w[0].strip()) <= 2
            ):
                v = i + 1
            elif cmp_word(w[0].lower(), last_word.lower()):
                v2 = i + 1

            # handle repetitions
            if end + 1 - v < 1 or end + 1 - v2 < 1:
                break

        words = st
        if v == 0 and v2 == 0:
            if idx == len(text) - 1:
                v = len(timepoints) - st
            else:
                v = len(sen_words)

        words = v + st
        if v2 > v:
            words = v2 + st

        # to add non-aplha characters
        if end < len(sen_words) - 1:
            words = min(words + len(sen_words) - 1 - end, len(timepoints))

        text_time = timepoints[words - 1][2]

        text_timepoints = list(
            map(
                lambda x: (x[0], x[1] - last_text_time, x[2] - last_text_time),
                timepoints[st:words],
            )
        )

        # print(text_timepoints, v, v2, st, words, sen_words, last_word)

        if idx == 0:
            splits.append((audio_file, text_time - last_text_time))
            # normalize
            new_timepoint_map[audio_file] = text_timepoints
        else:
            splits.append((str(idx), text_time - last_text_time))
            # normalize
            new_timepoint_map[str(idx)] = text_timepoints

        st = words
        last_text_time = text_time

    return splits, new_timepoint_map


@errors.log_ctx_errors
def get_bgm_from_name(name: str) -> Optional[Tuple[str, int]]:
    public_url = None
    output_file = None

    if name.startswith("http"):
        public_url = urllib.parse.unquote(name)

    elif name.startswith("baasha_file:"):
        base64String = name[name.index(":") + 1 :]
        decoded = base64.b64decode(base64String)
        output_file = os.path.join(file_dir, "tmp", f"bgm_{uuid4()}.mp3")
        with open(output_file, "wb") as f:
            f.write(decoded)

        public_url = object_storage.upload_file(
            object_storage.ASSETS_AUDIO_BUCKET,
            output_file,
            os.path.basename(output_file),
            object_storage.ACL_PUBLIC,
        )

    else:
        bgm_name = name.strip().lower().replace(" ", "_")
        public_url = object_storage.get_object_url_from_key(
            object_storage.BGM_BUCKET, bgm_name
        )

    if public_url == None:
        logging.info(f"PipelineUtils: bgm ({name}) not found")
        return None

    # download bgm to caculate duration
    local_path = output_file or utils.download_media_by_url(public_url)
    bgm_audio_dur = int(round(utils.get_media_duration(local_path)))
    return (public_url, bgm_audio_dur)


@errors.raise_ctx_errors
def keywords_to_desp(k):
    k = k.strip()
    return k.replace("#", "") + "|" + k


@errors.raise_ctx_errors
def get_vid_privacy(p):
    p = p.lower()
    if p == "public":
        return "public"
    elif p == "private":
        return "private"
    else:
        return "private"


@errors.raise_ctx_errors
def edit_ui_order(data, ordering):
    audios = list(enumerate(data["audios"]))
    images = list(enumerate(data["images"]))
    texts = list(enumerate(data["text"]))

    for k in ordering.keys():
        f = int(k) - 1
        t = int(ordering[k]) - 1

        logging.info(f"PipelineUtils: switch ui order {f} -> {t}")

        if len(audios) < f or f < 0 or t < 0 or t > len(audios):
            continue

        audios[f], audios[t] = (t, audios[f][1]), (f, audios[t][1])
        images[f], images[t] = (t, images[f][1]), (f, images[t][1])
        texts[f], texts[t] = (t, texts[f][1]), (f, texts[t][1])

    sortAndMap = lambda x: list(map(lambda y: y[1], sorted(x, key=lambda z: z[0])))

    data["audios"] = sortAndMap(audios)
    data["images"] = sortAndMap(images)
    data["text"] = sortAndMap(texts)

    return data


@errors.raise_ctx_errors
def get_ui_config(data):

    if len(data["audios"]) > 0:
        first_audio = data["audios"][0]
        data["audios"][0] = (first_audio[0], first_audio[1] + 0.0)

    if len(data["audios"]) > 1:
        last_audio = data["audios"][-1]
        data["audios"][-1] = (last_audio[0], last_audio[1] + 0.0)

    text_arr = data["text"]

    logging.info("generating image dims")
    images = list(
        map(lambda x: (x, utils.get_aspect_ratio("image", x)), data["images"])
    )

    # avatar = data.get("narrator_avatar", {})
    # if avatar.get("url") or avatar.get("url2"):
    #    data["narrator_avatar"]["ar"] = utils.get_aspect_ratio("video", avatar.get("url") or avatar.get("url2"))

    audios = []
    text = []
    total_time = 0
    for i in range(len(data["audios"])):
        audio = data["audios"][i]
        total_time += audio[1]
        audios.append(audio)
        text.append((text_arr[i], audio[1]))

    # if total_time > len(images) * 3 and len(images) > 0:
    # images = images + images.copy() * int((total_time // len(images)) + 1)

    video_dur = 10

    if data.get("video") and data["video"] and data["video"] != "":
        try:
            download_video = utils.download_media_by_url(data["video"])
            video_dur = utils.get_media_duration(download_video)
            res = utils.loop_video_by_time(download_video, total_time + 1)

            if res != None:
                data["video"] = res[0]
                video_dur = res[1]
        except Exception as e:
            logging.error(f"PipelineUtils: error while processing video")
            logging.info(f"PipelineUtils: continuing with unprocessed video")

    version = data.get("video_conf_version")
    if not version or not remotion_ui_confs.configs.get(version):
        version = "v5"

    user_ui_config = data.get("ui_config")
    total_video_time, ui_config = remotion_ui_confs.configs[version].get_ui_config(
        data, text, audios, images, video_dur, total_time + 2
    )
    fonts = remotion_ui_confs.configs[version].get_fonts(user_ui_config)

    other_confs = {
        "totalTime": total_video_time,
        "fonts": fonts,
        "ai_edits": data.get("ai_edits"),
    }

    return (ui_config, other_confs)


@errors.raise_ctx_errors
def get_video_config(data):
    ui_conf, other_confs = get_ui_config(data)

    conf = {
        "config": other_confs,
        "uiConfig": ui_conf,
    }

    return conf


@errors.raise_ctx_errors
def get_video_config_url(conf):
    key = f"{uuid4()}.json"
    public_url = object_storage.upload_data(
        object_storage.ASSETS_VIDEO_CONFIG,
        json.dumps(conf),
        key,
        object_storage.ACL_PUBLIC,
    )
    return public_url


@errors.raise_ctx_errors
def threaded_task(tag, task, callback, *args):
    def wrap():
        logging.info(f"PipelineUtils: {tag} thread started!")

        res = task(*args)
        logging.info(f"PipelineUtils: {tag} thread ended!")

        callback(res)
        logging.info(f"PipelineUtils: {tag} thread callback invoked!")

    return Thread(target=wrap)


@errors.raise_ctx_errors
def indexed_threaded_task(tag, idx, task, callback, *args):
    def wrap():
        logging.info(f"PipelineUtils: {tag} thread started!")

        res = task(*args)
        logging.info(f"PipelineUtils: {tag} thread ended!")

        callback((idx, res))
        logging.info(f"PipelineUtils: {tag} thread callback invoked!")

    return Thread(target=wrap)


if __name__ == "__main__":
    import requests

    u = "http://localhost:5000/draft/31d39475-d916-4798-b378-a53f14ce8404/493"
    vid_data = json.loads(requests.get(u).json()["video_data"])

    # print(vid_data)

    t = vid_data.get("text")

    print(vid_data["timepoints_map"])

    # f = text_to_speech_as_single_audio(t, None, "gtts")

    a = "tmp/rama.mp3"

    timepoints = vosk_toolkit.get_audio_timepoints(a)
    patched_timepoints = utils.patch_timepoints_words_v2(" ".join(t), timepoints)

    # print(patched_timepoints)

    tp = {}
    tp[a] = patched_timepoints

    f, a = make_audio_split(t, a, tp)

    # print(f, a)

    # conf = get_video_config(vid_data)

    # with open("remote.config.json", "w") as f:
    #    f.write(json.dumps(conf))
