from typing import Any, Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor

from dataclasses import asdict, dataclass, field
import json
import logging
import os
import random
import re
from typing import AsyncIterator
from baasha_pipeline.build_scraper import scrape_page
from hugchat.hugchat import ChatBot
import requests
import time
import asyncio
import io
from PIL import Image
from baasha_pipeline import (
    other_utils,
    stability_generator,
    goapi_midjourney_generator,
    gemini,
    goapi_flux,
    object_storage,
    getimg_flux1,
    utils,
    replicate_api,
    eachlabs_ai,
    errors,
    fal,
)
from baasha_pipeline.chatbot import Img
from uuid import uuid4
from baasha_pipeline.prompts import splitters as PromptSplitters
from baasha_pipeline.prompts.splitters import markdown_parse
from baasha_pipeline import chatbot as BaashaChat
from requests.auth import CONTENT_TYPE_FORM_URLENCODED
from sqlalchemy.orm import exc
from textblob import TextBlob
from baasha_pipeline import (
    image_search_agent,
    gooey_ai,
    lemon_slice_ai,
    ideogram,
    text_embeddings,
)
from baasha_pipeline.image_search_agent import (
    search as google_search_agent,
    summarize_page,
)
from baasha_pipeline import motion_graphics_agent
from models import AssetGenStages
import cv2
import numpy as np
import io
import base64
from PIL import Image

logger = logging.getLogger(__name__)


@errors.log_ctx_errors
def verify_subject_continuity(last_frame_url: str, next_img_url: str) -> bool:
    img1_bytes = requests.get(last_frame_url, timeout=30).content
    img2_bytes = requests.get(next_img_url, timeout=30).content

    chatbot = BaashaChat.ChatInterface()

    prompt = "Look at Image 1 and Image 2. Is there AT LEAST ONE primary human subject or main character that is present in BOTH Image 1 and Image 2? (It is okay if a new character enters in Image 2, as long as at least one character from Image 1 is still present). Reply with only 'YES' or 'NO'."

    img1 = BaashaChat.Img(_bytes=img1_bytes, text="Image 1")
    img2 = BaashaChat.Img(_bytes=img2_bytes, text="Image 2")

    response = chatbot.fetch_text([img1, img2, prompt])

    logging.info(
        f"verify character presense: {last_frame_url} vs {next_img_url} -> {response}"
    )

    return "YES" in (response or "").upper()


class ExceptionWithLogs(Exception):
    def __init__(self, msg, logs):
        super().__init__(msg)

        self.msg = msg
        self.logs = logs


@dataclass
class StyleData:
    themes: List[str] = field(default_factory=list)
    emotions: List[str] = field(default_factory=list)
    camera_angles: List[str] = field(default_factory=list)
    camera_lens: List[str] = field(default_factory=list)
    lighting: List[str] = field(default_factory=list)
    color_palettes: List[str] = field(default_factory=list)

    def to_text(self):
        return ", ".join(self.to_list())

    def to_list(self):
        res = []
        for l in [
            self.themes,
            self.emotions,
            self.camera_angles,
            self.camera_lens,
            self.lighting,
            self.color_palettes,
        ]:
            if l:
                res.extend(l)

        return res


def to_style_data(data: Optional[Dict]) -> Optional[StyleData]:
    if not data:
        return None
    try:
        style_data = StyleData(
            themes=data.get("themes", []),
            emotions=data.get("emotions", []),
            camera_angles=data.get("camera_angles", []),
            camera_lens=data.get("camera_lens", []),
            lighting=data.get("lighting", []),
            color_palettes=data.get("color_palettes", []),
        )

        return style_data
    except Exception as e:
        logging.error("Error while parsing styles")
        return None


subject_removal_prompt = "Completely remove the subject identified by the #b3b400 yellow outline and realistically reconstruct the background. The output must be a clean, high-quality landscape image with no trace of the subject or the outline."


_PROMPT_LIBRARY = None
_OVERRIDE_CACHE = {}


def get_prompt_text(prompt_name, overrides=None):
    global _PROMPT_LIBRARY
    if _PROMPT_LIBRARY is None:
        with open("prompts.json") as json_file:
            _PROMPT_LIBRARY = json.load(json_file)

    base_text = _PROMPT_LIBRARY.get(prompt_name).get("text")
    if not overrides:
        return base_text

    if isinstance(overrides, str):
        if overrides not in _OVERRIDE_CACHE:
            try:
                with open(f"static/override/{overrides}.json") as f:
                    _OVERRIDE_CACHE[overrides] = json.load(f)
            except Exception as e:
                logging.error(f"Failed to load override file {overrides}.json: {e}")
                _OVERRIDE_CACHE[overrides] = {}
        overrides = _OVERRIDE_CACHE[overrides]

    if not isinstance(overrides, dict):
        return base_text

    # Map back to UI names
    ui_key = None
    if prompt_name in ["content-gen-split-and-styling", "story-split-and-styling"]:
        ui_key = "screenplay"
    elif prompt_name == "one-shot-image-grid":
        ui_key = "grid"
    elif prompt_name == "holistic-grid-judge":
        ui_key = "judge"
    elif prompt_name == "find-story-characters":
        ui_key = "character"

    if not ui_key or ui_key not in overrides:
        return base_text

    custom_text = overrides[ui_key]
    if not custom_text or not custom_text.strip():
        return base_text

    # Apply merging logic to preserve format constraints
    if prompt_name == "content-gen-split-and-styling":
        split_marker = "### Creative Constraints:"
        if split_marker in base_text:
            format_spec = base_text.split(split_marker)[1]
            return custom_text + "\n\n" + split_marker + format_spec

    elif prompt_name == "story-split-and-styling":
        split_marker = "### Output Keys:"
        if split_marker in base_text:
            format_spec = base_text.split(split_marker)[1]
            return custom_text + "\n\n" + split_marker + format_spec

    elif prompt_name == "one-shot-image-grid":
        if "{DESCRIPTIONS}" not in custom_text:
            return (
                custom_text
                + "\n\nDescriptions of narrative arc frames:\n\n{DESCRIPTIONS}"
            )

    elif prompt_name == "holistic-grid-judge":
        split_marker = "### Output Format"
        if split_marker in base_text:
            format_spec = base_text.split(split_marker)[1]
            return custom_text + "\n\n" + split_marker + format_spec

    elif prompt_name == "find-story-characters":
        split_marker = "### Output Format:"
        if split_marker in base_text:
            format_spec = base_text.split(split_marker)[1]
            return custom_text + "\n\n" + split_marker + format_spec

    return custom_text


def get_prompts_from_json_file(filename):
    with open(filename) as json_file:
        prompt_library = json.load(json_file)
    return prompt_library


def generate_data(
    chatbot,
    task_key,
    task_quest,
    task_processors=None,
    is_context=False,
    append_context=False,
):
    result = {task_key: None}

    def enqueue(key, processors):
        def temp(data):
            if data is not None:
                logger.debug("Queued %s", data)
                if processors:
                    for p in processors:
                        data = p(data)
                result[key] = data

        return temp

    task = other_utils.threaded_task(
        "{}_GEN".format(task_key.upper()),
        chatbot.fetch_text,
        enqueue(task_key, task_processors),
        task_quest,
        is_context,
        append_context,
    )
    task.start()
    task.join()
    return result[task_key]


sounds_list = [
    # "applause_crowd",
    "birds",
    "clock_ticking",
    "coffee_pour",
    "fire_blaze",
    "flame",
    "footsteps",
    "horse",
    "keyboard",
    "laser",
    "meow",
    "rattle_snake",
    "snake_hiss",
    "swords_hit",
    "thunder",
    "thunderstorm",
    "train_horn",
    "war",
    "wolf_howl",
    "whoosh",
    "typing-keyboard",
    "cash",
    "cinematic-riser",
    "impact-thud",
    "vinyl-scratch",
]


def get_word_sound_effects(chatbot, timepoints: Dict[str, List[Tuple[str, int, int]]]):
    base_url = "https://baasha-bgm.us-east-1.linodeobjects.com/effects/"
    sentences = list(
        map(lambda x: " ".join(list(map(lambda y: y[0], x))), timepoints.values())
    )
    s = " ".join(sentences)

    sounds = ", ".join(sounds_list)
    p = get_prompt_text("sound-effects").format(STORY=s, SOUNDS=sounds)

    res = generate_data(chatbot, "sound_effects", p)
    sound_map: dict[str, list[tuple[str, int, int]]] = {}
    if res:
        parsed_out = PromptSplitters.json_splitter(
            {"json_keys": ["word", "sound"], "join": False}
        )(res)

        for pairs in parsed_out:
            word = pairs.get("word")
            sound = pairs.get("sound")

            for k in timepoints.keys():

                if not sound_map.get(k):
                    sound_map[k] = []

                for i in timepoints[k]:
                    url = base_url + sound + ".mp3"
                    if word.lower() == i[0].lower() and sound in sounds_list:
                        sound_map[k].append((url, i[1], i[2]))

    return sound_map


def list_find(arr, v, l=0, h=-1):
    if h == -1:
        h = len(arr)

    for idx in range(l, h):
        i = arr[idx]
        if i[0].lower().startswith(v.lower()):
            return idx
    raise Exception("value not found")


def generate_phrase_sound_effects(chatbot, sounds, story):
    p = get_prompt_text("phrase-sounds").format(STORY=story, SOUNDS=sounds)
    res = generate_data(chatbot, "sound_effects", p)

    if res:
        parsed_out = PromptSplitters.json_splitter(
            {"json_keys": ["phrase", "sound"], "join": False}
        )(res)

        return parsed_out

    return None


def get_phrase_sound_effects(
    chatbot, sounds_list, audios: list[tuple[str, float]], timepoints
):
    sentences = list(
        map(lambda x: " ".join(list(map(lambda y: y[0], x))), timepoints.values())
    )
    s = " ".join(sentences)
    sounds = ", ".join(list(set(map(lambda x: x["name"], sounds_list))))
    parsed_out = generate_phrase_sound_effects(chatbot, sounds, s)
    sound_map: list[tuple[str, float, float, str]] = []
    if parsed_out:
        story: list[tuple[float, list[tuple[Any, Any, Any]]]] = []
        for a in audios:
            tpoints = timepoints.get(a[0])

            if not tpoints:
                continue

            m = list(map(lambda x: (x[0], x[1], x[2]), tpoints))
            story.append((a[1], m))

        for pairs in parsed_out:
            phrase = pairs.get("phrase").strip().lower()
            sound = pairs.get("sound")
            url = None
            if phrase.strip() == "":
                break

            for s in sounds_list:
                if s["name"] == sound.strip():
                    url = s["url"]
                    break

            if not url:
                continue

            for l in range(len(story)):
                m = story[l][1]

                splits = phrase.split(" ")
                st: tuple[int, int] | None = None
                en: tuple[int, int] | None = None
                i = 0
                while i < len(m):
                    sw: tuple[int, int] | None = None
                    try:
                        sw = (l, list_find(m, splits[0], i))
                    except Exception as e:
                        pass

                    if sw is None:
                        break

                    ew: tuple[int, int] | None = None
                    try:
                        ew = (l, list_find(m, splits[-1], sw[1] + 1))
                    except Exception as e:
                        if l + 1 < len(story):
                            m2 = story[l + 1][1]
                            try:
                                ew = (l + 1, list_find(m2, splits[-1]))
                            except Exception as e:
                                pass

                    if ew is None:
                        break

                    across_sentence = sw[0] != ew[0]
                    length = (
                        ew[1] - sw[1] + 1
                        if not across_sentence
                        else len(story[sw[0]][1]) - sw[1] + ew[1] + 1
                    )

                    if ew is not None and length - len(phrase) <= 2:
                        st = sw
                        en = ew
                        break
                    i += 1

                if st is not None and en is not None:
                    first_word: tuple[str, int, int] = story[st[0]][1][st[1]]
                    last_word: tuple[str, int, int] = story[en[0]][1][en[1]]
                    t = 0.0

                    for ix in range(0, st[0]):
                        t += story[ix][0]

                    start_time: float = float(t + first_word[1])
                    end_time: float = 0.0
                    if st[0] != en[0]:
                        end_time = float(t + story[st[0]][1][-1][1] + last_word[2])
                    else:
                        end_time = float(t + last_word[2])

                    if (
                        url is not None
                        and start_time is not None
                        and end_time is not None
                        and phrase is not None
                    ):
                        sound_map.append((url, start_time, end_time, phrase))
                    break

    sound_map = sorted(sound_map, key=lambda x: x[1])
    logging.info(f"phrase sound map: {sound_map}")

    return sound_map


@errors.log_ctx_errors
def build_script_context(chatbot, script):
    """
    Builds a highly grounded context using an iterative 2-turn research agent loop:
    Turn 1 (Discovery): Generates 1-2 broad overview search queries to discover the general topic.
    Turn 2 (Nuanced Deep-Dive): Uses Turn 1's facts to generate 2-3 highly specific deep-dive queries.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def run_queries(queries_list, max_workers=2):
        if not queries_list:
            return []
        results = []
        link = lambda x: f"https://duckduckgo.com/?q={x.replace(' ', '+')}&ia=web"
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_query = {
                executor.submit(summarize_page, chatbot, link(q), q): q
                for q in queries_list[:3]
            }
            for future in as_completed(future_to_query):
                query = future_to_query[future]
                try:
                    res = future.result(timeout=12)
                    if res:
                        results.append(res)
                except Exception as exc:
                    logging.warning(f"Grounding query '{query}' failed: {exc}")
        return results

    # --- Turn 1: Discovery ---
    logging.info(f"Initiating Turn 1 (Discovery Search) for topic: {script}")
    discovery_quest = (
        f"The user wants to write a script/content about the following topic or text: '{script}'.\n"
        "Generate exactly 1 or 2 high-level, broad search queries to discover what this main subject, "
        "product, event, or entity is in general. Focus on general definition and overview. "
        "Output the queries as a JSON array of strings enclosed in ```json."
    )
    discovery_out = generate_data(chatbot, "discovery_search_queries", discovery_quest)
    try:
        discovery_queries = json.loads(markdown_parse(discovery_out, lang="json"))
    except Exception as e:
        logging.error(f"Failed to parse discovery queries: {e}")
        discovery_queries = []

    discovery_summaries = run_queries(discovery_queries, max_workers=2)
    discovery_context = (
        "\n---\n".join(discovery_summaries) if discovery_summaries else ""
    )

    # --- Turn 2: Nuanced Deep-Dive ---
    logging.info(f"Initiating Turn 2 (Nuanced Deep-Dive Search) for topic: {script}")
    if discovery_context:
        deep_dive_quest = (
            f"We are writing a script/content about the following topic or text: '{script}'.\n\n"
            f"Here is the general information we discovered from our initial search:\n"
            f'"""\n{discovery_context}\n"""\n\n'
            "Now that you understand the general context, generate exactly 2 or 3 highly specific, highly nuanced "
            "deep-dive search queries to gather exact technical specifications, features, stats, histories, or "
            "critical details necessary to write an authentic, premium, and highly accurate script.\n"
            "Output the queries as a JSON array of strings enclosed in ```json."
        )
    else:
        deep_dive_quest = (
            f"We are writing a script/content about the following topic or text: '{script}'.\n"
            "Generate exactly 2 or 3 specific search queries to gather necessary facts, specifications, "
            "details, or behaviors about the subject of this text.\n"
            "Output the queries as a JSON array of strings enclosed in ```json."
        )

    deep_dive_out = generate_data(chatbot, "deep_dive_search_queries", deep_dive_quest)
    try:
        deep_dive_queries = json.loads(markdown_parse(deep_dive_out, lang="json"))
    except Exception as e:
        logging.error(f"Failed to parse deep-dive queries: {e}")
        deep_dive_queries = []

    deep_dive_summaries = run_queries(deep_dive_queries, max_workers=2)

    # --- Synthesis ---
    all_summaries = discovery_summaries + deep_dive_summaries
    final_summary = ""
    if all_summaries:
        logging.info(
            f"Successfully gathered {len(all_summaries)} context points via 2-turn grounding loop."
        )
        final_summary = (
            "### GROUNDING CONTEXT (Use this to ensure factual accuracy):\n"
            + "\n---\n".join(all_summaries)
        )

    return final_summary


@errors.log_ctx_errors
def build_and_set_script_context(chatbot, script):
    ctx = build_script_context(chatbot, script)
    chatbot.set_global_ctx(ctx)


def generate_story_and_title(chatbot, prompt, scenes=8, guidance=""):
    story_sentences = generate_story(chatbot, prompt, scenes, guidance)
    title = generate_title(chatbot, story_sentences)
    return story_sentences, title


def generate_story_as_json(chatbot, prompt, scenes=8, guidance=""):
    # prime for story writing
    generate_data(chatbot, "story_prompt", get_prompt_text("plot-prompt-v1"))

    story_quest = get_prompt_text("reverse-prompt-v4").format(
        PROMPT=prompt, GUIDANCE=guidance, SCENES=scenes
    )
    viral_spec = get_viral_story_spec() or ""
    story_quest = viral_spec + "\n\n" + story_quest if viral_spec else story_quest
    story = generate_data(chatbot, "story_prompt", story_quest)
    # JSONs with key as sentence
    logger.info("story: %s", story)
    parsed_story = PromptSplitters.json_splitter(
        {"json_keys": ["sentence"], "join": False}
    )(story)
    story_sentences = list(map(lambda x: x["sentence"], parsed_story))
    logger.debug("Story sentences: %s", story_sentences)

    hook_quest = get_prompt_text("hook-prompt-v2").format(PROMPT=prompt)
    hook = generate_data(chatbot, "hook_prompt", hook_quest)
    # JSON with key as hook
    parse_hook = PromptSplitters.json_splitter({"json_keys": ["hook"], "join": False})(
        hook
    )
    hook_sentences = list(map(lambda x: x["hook"], parse_hook))

    logger.debug("parsed_story: %s", story_sentences)
    logger.debug("parse_hook: %s", hook_sentences)

    return [" ".join(hook_sentences)] + story_sentences


def generate_story_as_paragraph(chatbot, prompt, scenes=8, guidance=""):
    # prime for story writing
    generate_data(chatbot, "story_prompt", get_prompt_text("plot-prompt-v1"))

    story_quest = get_prompt_text("reverse-prompt-v3").format(
        PROMPT=prompt, GUIDANCE=guidance, SCENES=scenes
    )
    viral_spec = get_viral_story_spec() or ""
    story_quest = viral_spec + "\n\n" + story_quest if viral_spec else story_quest
    story = generate_data(chatbot, "story_prompt", story_quest)

    hook_quest = get_prompt_text("hook-prompt-v1").format(PROMPT=prompt)
    hook = generate_data(chatbot, "hook_prompt", hook_quest)

    script_sentences = [hook.strip('"')] if hook else []
    for line in story.splitlines():
        ln = line.strip()
        if ln.startswith("Sure!"):
            continue
        for s in ln.split("."):
            if s.strip():
                script_sentences.append(s.strip())
    return script_sentences


def test_story_gen(chatbot, prompt, guidance=""):
    # Automated Factual Grounding (Summary Context)
    build_and_set_script_context(chatbot, prompt)

    # Use split_text_into_sentences_with_styling flow
    # Pass "viral short form" ensures we use 'content-gen-split-and-styling' (which handles both gen and split)
    # instead of 'story-split-and-styling' (which only splits existing text).
    res = split_text_into_sentences_with_styling(
        chatbot, prompt, guidance or "viral short form video", image_styles=None
    )
    return res


def generate_story(chatbot, prompt, scenes=8, guidance=""):
    res = test_story_gen(chatbot, prompt, guidance)

    if not res:
        res = generate_story_as_json(chatbot, prompt, scenes, guidance)
    elif isinstance(res, tuple):
        # res is (text_list, styling_list, search_images, gen_images)
        return " \n ".join(res[0])
    return res

    if len(res) == 0:
        res = generate_story_as_paragraph(chatbot, prompt, scenes, guidance)

    return " \n ".join(res)


def generate_title(chatbot, story_sentences):
    # prime for title writing
    viral_spec = get_viral_story_spec() or ""
    title_quest = get_prompt_text("title-text")
    title_quest = viral_spec + "\n\n" + title_quest if viral_spec else title_quest
    title = generate_data(chatbot, "title_prompt", title_quest)
    return title


def generate_image_prompts(
    algo,
    chatbot,
    script_lines,
    scene_count,
    characters="",
    image_styles=None,
    image_config=None,
    guidance=None,
    callback=None,
):
    if algo == "beats":
        return generate_image_prompts_beats(
            chatbot, script_lines, scene_count, image_styles
        )
    else:
        res = generate_image_prompts_ner(
            chatbot,
            script_lines,
            scene_count,
            characters,
            image_styles,
            image_config,
            guidance=guidance,
            callback=callback,
        )
        return res[0]


def generate_image_prompts_beats(chatbot, script_lines, scene_count, image_styles=""):
    # prime for image prompt writing
    beats_quest = get_prompt_text("beat-sheet-v1").format(LINES=script_lines)
    beats_parts = generate_data(chatbot, "beats_prompt", beats_quest)

    image_quest = get_prompt_text("beat-sheet-images").format(
        SCENE_COUNT=scene_count, BEAT_SHEET=beats_parts
    )
    image_prompts = generate_data(chatbot, "image_prompt", image_quest)
    images_beats = extract_json(image_prompts)

    results = []
    for beat, prompt in images_beats.items():
        results += prompt
        extras = len(results) - scene_count
        if extras > 0:
            for _ in range(extras):
                # randomly remove image prompts if count is too high
                results.pop(random.randrange(1, len(results) - 1))
    logger.debug("Generated %d image prompts", (len(results)))
    return stylize_image_prompts(results, image_styles)


@errors.log_ctx_errors
def get_image_prompt_spec(is_styled=False):
    system_prompt = None
    file_name = (
        "styled_image_system_prompt.md"
        if is_styled
        else "realistic_image_system_prompt.md"
    )
    try:
        with open(file_name, "r", encoding="utf-8") as f:
            system_prompt = f.read()
    except FileNotFoundError:
        pass

    return system_prompt


@errors.log_ctx_errors
def get_viral_story_spec():
    viral_story_prompt = None
    with open("viral_story.md", "r", encoding="utf-8") as f:
        viral_story_prompt = f.read()

    return viral_story_prompt


def find_story_characters(
    chatbot,
    story,
    image_styles,
    image_config,
    prompt_key="find-story-characters",
    style_refs=None,
    user_characters=None,
    cinematic_data=None,
    prompt_overrides=None,
):
    banned_words = get_prompt_text("banned-words")

    story_text = story
    if isinstance(story, list):
        if len(story) > 0 and isinstance(story[0], dict):
            story_text = "\n".join(
                [
                    f"{s.get('character', 'Character')}: {s.get('text', '')}"
                    for s in story
                    if isinstance(s, dict)
                ]
            )
        else:
            story_text = "\n".join([str(s) for s in story])

    prompt = get_prompt_text(prompt_key, prompt_overrides).format(
        TEXT=story_text, BANNED_WORDS=banned_words
    )

    identified_characters = set()
    if user_characters:
        for k in user_characters.keys():
            identified_characters.add(k)

    if isinstance(story, list):
        for s in story:
            if isinstance(s, dict) and s.get("character"):
                identified_characters.add(s["character"])
            elif isinstance(s, str):
                import re

                matches = re.findall(r"\[([A-Za-z0-9 _-]+)\]", s)
                for m in matches:
                    identified_characters.add(m)
    elif isinstance(story, str):
        import re

        matches = re.findall(r"\[([A-Za-z0-9 _-]+)\]", story)
        for m in matches:
            identified_characters.add(m)

    if cinematic_data:
        for c in cinematic_data:
            if isinstance(c, dict):
                if c.get("speaker"):
                    identified_characters.add(c["speaker"])
                motion = c.get("motion_prompt") or ""
                import re

                matches = re.findall(r"\[([A-Za-z0-9 _-]+)\]", motion)
                for m in matches:
                    identified_characters.add(m)

    if identified_characters:
        char_list_str = ", ".join(sorted(list(identified_characters)))
        prompt += (
            f"\n\nCRITICAL SPEAKER & CHARACTER EXPECTANCY:\n"
            f"The screenplay generator has already identified and referred to the following character names in the screenplay: {char_list_str}.\n"
            f"You MUST generate a visual casting profile and voice description for EXACTLY these characters. Do not invent new names or ignore these. Ensure they match exactly."
        )

    image_prompt_spec = get_image_prompt_spec(is_styled=bool(style_refs)) or ""
    prompt = image_prompt_spec + "\n\n" + prompt if image_prompt_spec else prompt

    raw_text = generate_data(chatbot, "find_characters", prompt)
    parsed_text = PromptSplitters.json_splitter(
        {
            "json_keys": [
                "name",
                "description",
                "fictional",
                "search",
                "voice_description",
            ],
            "join": False,
        }
    )(raw_text)
    filtered = list(
        filter(lambda x: x.get("name") != None and x.get("name") != "", parsed_text)
    )

    process_prompts = []
    for r in filtered:
        if r and r.get("description"):
            process_prompts.append(r["description"])

    if len(process_prompts) > 0 and not style_refs:
        enhanced_prompts = enhance_prompts(process_prompts, image_styles, image_config)
        j: int = 0
        for i in range(len(filtered)):
            if filtered[i] and filtered[i].get("description"):
                filtered[i]["description"] = enhanced_prompts[j]
                j += 1

    chatbot.clear_ctx()

    return filtered


def generate_character_bible(
    chatbot,
    story,
    image_styles,
    image_config,
    outdir,
    prompt_key="find-story-characters",
    style_reference_urls=None,
    user_characters=None,
    cinematic_data=None,
    prompt_overrides=None,
):
    """
    Identifies characters and generates their visual references eagerly and in batch.
    Uses user_characters to maintain consistency across episodes.
    """
    characters = find_story_characters(
        chatbot,
        story,
        image_styles,
        image_config,
        prompt_key,
        style_reference_urls,
        user_characters=user_characters,
        cinematic_data=cinematic_data,
        prompt_overrides=prompt_overrides,
    )

    char_image_config = image_config.copy()

    if not char_image_config.get("name"):
        char_image_config["name"] = "gemini_nano_banana"

    # Prepare style references
    style_refs = []
    if style_reference_urls:
        style_refs = [
            {
                "url": s,
                "type": "style",
                "name": "COMPLETELY IGNORE any faces, identities, or characters in this image. Use it EXCLUSIVELY for lighting, color grading, and texture only.",
            }
            for s in style_reference_urls
        ]

    search_tasks = {}
    for i, char in enumerate(characters):
        # 1. Check if this character matches one from previous references
        matched = match_character(char["name"], user_characters or {}, [])
        if matched:
            is_url, url_data = matched
            if is_url:
                logging.info(
                    f"Character {char['name']} matched from previous references."
                )
                characters[i]["url"] = url_data
                characters[i]["urls"] = [url_data]
                continue

        if char.get("url"):
            continue

        # 2. Extract real-world search tasks
        search_query = char.get("search")
        is_fictional = str(char.get("fictional", "true")).lower() == "true"

        if search_query and not is_fictional:
            search_tasks[i] = search_query

    # Execute searches in parallel
    search_results = {}
    if search_tasks:
        import concurrent.futures

        def run_search(tup):
            idx, query = tup
            logging.info(f"Searching for real-world reference: {query}")
            thread_chatbot = BaashaChat.ChatInterface()
            thread_chatbot.new_conversation()
            res = multi_google_search(
                thread_chatbot, [query], outdir=outdir, animate=False
            )
            try:
                thread_chatbot.delete_conversation()
            except Exception:
                pass
            return idx, res

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(2, len(search_tasks))
        ) as executor:
            futures = [
                executor.submit(run_search, item) for item in search_tasks.items()
            ]
            for future in concurrent.futures.as_completed(futures):
                try:
                    idx, out = future.result()
                    search_results[idx] = out
                except Exception as e:
                    logging.error(f"Parallel search failed: {e}")

    prompts_to_gen = []
    char_indices = []
    char_ref = {}

    for i, char in enumerate(characters):
        if char.get("url"):
            continue

        if i in search_tasks:
            search_out = search_results.get(i)
            if search_out and len(search_out) > 0 and search_out[0]:
                url = search_out[0][0]
                if url:
                    characters[i]["search_url"] = url
                    characters[i]["search_urls"] = [url]

                    # Build a highly descriptive hybrid prompt that combines character visual description with clear style transfer rules:
                    desc = char.get(
                        "description", "A high quality straight full body portrait."
                    )
                    clean_desc = desc.split("SINGLE FRAME ONLY.")[0].strip()

                    upscale = (
                        f"HIGH FIDELITY STYLE TRANSFER & REGENERATION PORTRAIT.\n"
                        f"Subject Description: {clean_desc}\n\n"
                        f"INSTRUCTIONS:\n"
                        f"1. Extract the exact face structure, physical features, and build from the character reference image to maintain absolute identity consistency.\n"
                        f"2. Apply the visual medium, art style, rendering texture, and aesthetic of the provided style reference image perfectly onto the subject.\n"
                        f"3. Output a clean, high-quality, single-subject full frame portrait. No grids, no comic dividers, no split screens."
                    )
                    prompts_to_gen.append(upscale)
                    char_indices.append(i)
                    char_ref[str(i)] = url
                    continue

        desc = char.get("description")
        if desc:
            prompts_to_gen.append(desc)
            char_indices.append(i)

    if prompts_to_gen:
        logging.info(f"Generating Visual Bible for {len(prompts_to_gen)} characters...")

        # Pass style_refs for each prompt in the batch
        batch_refs = []
        for i in range(len(char_indices)):
            ref = style_refs.copy() if style_refs else []
            if char_ref.get(str(i)):
                actual_char = characters[char_indices[i]]
                ref.append(
                    {
                        "type": "character",
                        "name": actual_char["name"],
                        "url": char_ref[str(i)],
                    }
                )
            batch_refs.append(ref)

        urls, _, gen_map, errors, logs = image_gen(
            prompts_to_gen,
            batch_refs,
            outdir,
            char_image_config,
            chatbot,
        )

        for k, url in enumerate(urls):
            if url:
                char_idx = char_indices[k]
                characters[char_idx]["url"] = url
                characters[char_idx]["urls"] = [url]
                characters[char_idx]["image_engine"] = char_image_config["name"]

    return characters


def generate_image_prompts_ner(
    chatbot,
    script_lines,
    scene_count,
    characters="",
    image_styles=None,
    image_config=None,
    ner_prompt_key="ner-v1",
    ner_image_prompt_key="entity-to-image",
    guidance=None,
    callback=None,
    allow_retry=1,
):
    logger.debug("script lines :: %s", script_lines)

    # prime for image prompt writing
    def get_entities():
        res = []
        quest = get_prompt_text(ner_prompt_key)
        generate_data(chatbot, "ner_prompt", quest, is_context=True)

        for t in script_lines:
            try:
                quest = get_prompt_text(f"{ner_prompt_key}-completion").format(
                    SENTENCE=t
                )
                entities = generate_data(chatbot, "ner", quest)
                parsed_entities = PromptSplitters.json_splitter(
                    {"json_keys": ["entity"], "join": True}
                )(entities)
                if len(parsed_entities) == 0 or len(parsed_entities[0]) < 10:
                    # incorrect format
                    logger.debug("prompting LLM to reformat")
                    quest = get_prompt_text(f"{ner_prompt_key}-correction").format(
                        PREV_OUTPUT=entities
                    )
                    entities = generate_data(chatbot, "ner", quest)
                    parsed_entities = PromptSplitters.json_splitter(
                        {"json_keys": ["entity"], "join": True}
                    )(entities)
                if len(parsed_entities) > 0:
                    res.append(parsed_entities[0])
                else:
                    res.append(None)
            except Exception as e:
                logger.error("ner gen error ::: ", e)
                res.append(None)

        chatbot.clear_ctx()

        return res

    def get_prompts(entities, script_lines, allow_retry):
        result = []
        banned_words = get_prompt_text("banned-words")
        quest = get_prompt_text(f"{ner_image_prompt_key}").format(
            TEXT=" ".join(script_lines),
            BANNED_WORDS=banned_words,
            CHARACTERS=characters,
            GUIDANCE=guidance or "",
        )

        image_prompt_spec = get_image_prompt_spec(is_styled=bool(image_styles)) or ""
        quest = image_prompt_spec + "\n\n" + quest if image_prompt_spec else quest

        generate_data(
            chatbot,
            "entity_to_image_prompt",
            quest,
            is_context=True,
            append_context=True,
        )

        quest = get_prompt_text(f"{ner_image_prompt_key}-completion").format(
            ENTITY="\nEntity: ".join(entities), COUNT=str(len(entities))
        )
        prompt_out = generate_data(chatbot, "image-prompt-gen", quest)
        parsed_prompt = json.loads(markdown_parse(prompt_out, lang="json"))

        logging.info(f"generate-prompts : {parsed_prompt}")

        for idx, p in enumerate(parsed_prompt):
            result.append(
                (
                    p.get("image"),
                    p.get("character"),
                )
            )
            if callback:
                callback(idx, p.get("image"))

        chatbot.clear_ctx()

        if allow_retry <= 0:
            return result

        lines_retry = []
        entity_retry = []
        for idx, s in enumerate(script_lines):
            if len(result) <= idx:
                result.append((None, None))

            if not result[idx] or not result[idx][0]:
                result[idx] = (None, None)
                lines_retry.append(s)
                entity_retry.append(entities[idx])

        if len(lines_retry) > 0:
            retry_result = get_prompts(entity_retry, lines_retry, allow_retry - 1)
            i = 0
            for idx in range(0, len(result)):
                if not result[idx] or not result[idx][0]:
                    result[idx] = retry_result[i]

        return result

    entities_gen = script_lines  # get_entities()

    results: List[Any] = []
    for bucket in range(0, len(script_lines), 10):
        end = min(len(script_lines), bucket + 10)
        bucket_results = get_prompts(
            entities_gen[bucket:end], script_lines[bucket:end], allow_retry
        )
        results = results + bucket_results

    for idx, s in enumerate(script_lines):
        if not results[idx][0]:
            results[idx] = (s, results[idx][1])

    process_prompts = []
    for r in results:
        if r and r[0]:
            process_prompts.append(r[0])

    enhanced_prompts = enhance_prompts(process_prompts, image_styles, image_config)
    j: int = 0
    for i in range(len(results)):
        if results[i] and results[i][0]:
            results[i] = (enhanced_prompts[j], results[i][1])
            j += 1

    return (
        results,
        entities_gen,
    )


def stylize_image_prompts(image_prompts: List[str], image_styles):
    if hasattr(image_styles, "to_list"):
        image_styles = image_styles.to_list()

    styles_text = ", ".join(image_styles) if image_styles else ""
    return [f"{p} {styles_text}" if p and styles_text else p for p in image_prompts]


def match_character(name, user_characters, character_list):
    name = name or "None"
    name = name.lower()
    try:
        for n in list(user_characters.keys()):
            if str(n) in str(name) and n != "narrator_avatar":
                return (True, user_characters[n])
    except Exception as e:
        pass

    try:
        for (idx, ch) in enumerate(character_list):
            logging.info(f"match character: {name} vs {ch.get('name')}")
            if ch.get("name", "####").lower().strip().replace(
                " ", ""
            ) == name.strip().replace(" ", ""):
                logging.info(f"character matched: {name}")

                if ch.get("url") == None:
                    return (False, idx)
                else:
                    logging.info(
                        f"matched character {ch.get('name')} : {character_list[idx].get('url')}"
                    )
                return (True, character_list[idx].get("url"))

        return None
    except Exception as e:
        logger.error("no character found for name %s", name, e)
        return None


def image_gen(
    gen_image_descriptors,
    refs,
    out_path,
    image_config={"name": "replicate_flux_kontext"},
    chatbot=None,
):
    gen_image_urls = []
    gen_image_prompts = gen_image_descriptors
    image_model_map = {}
    logs = []
    errors: Optional[List[str]] = None

    image_engine = image_config.get("name")
    aspect_ratio = image_config.get("aspect_ratio", "9:16")
    image_resolution = image_config.get("resolution", "1K")
    prompt_strength = image_config.get("prompt_strength", None)

    # Save original multi-reference payload strictly for Gemini
    gemini_refs = refs

    # For all legacy image engines, flatten the multi-reference array down to a single String URL
    # (Typically the first element, which is the Character Reference).

    image_engine_provider = image_engine.split("/")[0]

    multi_ref_support = ["gemini_nano_banana", "fal"]
    if image_engine_provider not in multi_ref_support and refs:
        flattened = []
        for r in refs:
            if isinstance(r, list) and len(r) > 0:
                first = r[0]
                flattened.append(first.get("url") if isinstance(first, dict) else first)
            else:
                flattened.append(r.get("url") if isinstance(r, dict) else r)
        refs = flattened

    if image_engine_provider == "gemini_nano_banana":
        gen_image_urls, errors = gemini.generate_images(
            gen_image_descriptors,
            gemini_refs,
            width=image_config.get("width"),
            height=image_config.get("height"),
            aspect_ratio=aspect_ratio,
            image_resolution=image_resolution,
        )

    elif image_engine_provider == "fal":
        gen_image_urls, errors = fal.generate_images(
            gen_image_descriptors,
            gemini_refs,
            width=image_config.get("width"),
            height=image_config.get("height"),
            aspect_ratio=aspect_ratio,
            image_resolution=image_resolution,
            image_engine=image_engine,
        )

    elif image_engine_provider == "goapi_flux1":
        gen_image_urls, errors = goapi_flux.generate_images(
            gen_image_descriptors,
            refs,
            width=image_config.get("width"),
            height=image_config.get("height"),
            negative_prompt=get_prompt_text("standard-negative-prompt-v2"),
        )

    elif image_engine.endswith("flux1"):
        gen_image_urls = getimg_flux1.generate_images(
            gen_image_descriptors,
            refs,
            height=image_config.get("height"),
            width=image_config.get("width"),
            image_engine=image_engine,
            negative_prompt=get_prompt_text("standard-negative-prompt-v2"),
        )

    elif image_engine_provider == "goapi_midjourney":
        (
            gen_image_urls,
            gen_image_prompts,
            errors,
            logs,
        ) = goapi_midjourney_generator.generate_images(
            list(zip(gen_image_descriptors, refs)),
            get_prompt_text("standard-negative-prompt-v2"),
            "/tmp/{}".format(out_path),
            chatbot,
        )

    elif image_engine.startswith("replicate"):
        gen_image_urls, errors = replicate_api.generate_images(
            gen_image_descriptors, refs
        )

    elif image_engine == "ideogram":
        gen_image_urls = ideogram.generate_images(gen_image_descriptors)

    try:
        for m in gen_image_urls:
            image_model_map[m] = image_engine
    except Exception:
        pass

    return gen_image_urls, gen_image_prompts, image_model_map, errors, logs


def judge_and_fix_image(
    chatbot, image_url, general_prompt, general_context="", character_details=""
):
    current_url = image_url
    judge_results = []

    specific_context = build_script_context(chatbot, general_prompt)
    context = (general_context or "") + "\n" + specific_context

    # Hardcoded max 1 retry (2 attempts total if first fails)
    for i in range(2):
        logger.info(f"Judging image (attempt {i+1}): {current_url}")

        judge_prompt_template = get_prompt_text("image-judge-fix")
        judge_prompt = judge_prompt_template.format(
            PROMPT=general_prompt, CONTEXT=context, CHARACTER=character_details
        )

        try:
            img_bytes_response = requests.get(current_url, timeout=30)
            img_bytes_response.raise_for_status()

            p_img = Img(_bytes=img_bytes_response.content, text=judge_prompt)
            response_text = chatbot.fetch_text(p_img)

            result = {"result": "FAIL", "reasoning": "Failed to parse judge response"}
            if response_text:
                # Try markdown_parse first
                text = markdown_parse(response_text)
                try:
                    result = json.loads(text or "{}")
                except Exception as json_err:
                    logger.error(f"JSON load failed: {json_err}. Text to parse: {text}")
                    logger.debug(f"Full LLM response: {response_text}")
                    # Final attempt: regex for status
                    text_str = str(text or "")
                    status_match = re.search(r'"result"\s*:\s*"(\w+)"', text_str)
                    reason_match = re.search(
                        r'"reasoning"\s*:\s*"(.*?)"', text_str, re.DOTALL
                    )
                    fix_match = re.search(
                        r'"fix_instruction"\s*:\s*"(.*?)"', text_str, re.DOTALL
                    )
                    if status_match:
                        result = {
                            "result": status_match.group(1),
                            "reasoning": reason_match.group(1) if reason_match else "",
                            "fix_instruction": fix_match.group(1) if fix_match else "",
                        }
        except Exception as e:
            logger.error(f"Failed to judge image: {e}")
            result = {
                "result": "FAIL",
                "reasoning": f"Error: {e}",
                "fix_instruction": "Regenerate image",
            }

        judge_results.append(result)

        if result.get("result") == "PASS":
            logger.info("Image passed judging.")
            return current_url, judge_results

        if i == 1:  # Already on second attempt, don't try again
            break

        fix_instruction = result.get("fix_instruction")
        logger.info(f"Image failed judging. Fix instruction: {fix_instruction}")

        refinement_prompt = get_prompt_text("image-refinement-v1").format(
            INSTRUCTIONS=fix_instruction
        )

        try:
            # Call existing gemini.generate_images (which uses existing logic)
            # gemini.generate_images does not take a chatbot argument in current version
            new_urls, _ = gemini.generate_images(
                [refinement_prompt],
                [[{"url": current_url, "type": "subject"}]],
            )
            if new_urls and new_urls[0]:
                current_url = new_urls[0]
            else:
                logger.error("Failed to generate refined image.")
                break
        except Exception as e:
            logger.error(f"Error during image refinement: {e}")
            break

    return current_url, judge_results


def judge_and_fix_images(
    chatbot, image_urls, prompts, context="", character_details=""
):
    def parallel_judge(url, prompt):
        return judge_and_fix_image(chatbot, url, prompt, context, character_details)

    with ThreadPoolExecutor(max_workers=2) as executor:
        # Use executor.map to maintain prompt/url alignment and result order
        results = list(executor.map(parallel_judge, image_urls, prompts))

    refined_urls = [r[0] for r in results]
    all_judge_results = [r[1] for r in results]

    return refined_urls, all_judge_results


@errors.log_ctx_errors
def create_image_layer(chatbot, local_path, img, aspect_ratio="9:16"):
    if not img:
        return None

    logging.info("downloading image")
    resp = requests.get(img)
    logging.info("image downloaded")
    ext = img.split(".")[-1]
    u = uuid4()
    filename = lambda x: f"{u}_{x}.{ext}"
    filepath = os.path.join(local_path, filename("asset"))
    outputpath = os.path.join(local_path, filename("layer"))
    with open(filepath, "wb") as f:
        f.write(resp.content)

    output = None

    def cb(v):
        nonlocal output
        pub_url = upload_image(outputpath)
        output = pub_url

    t = other_utils.threaded_task(
        "REMOVE_BG",
        # utils.remove_background_using_border,
        segment_image_layer,
        cb,
        chatbot,
        filepath,
        outputpath,
    )
    t.start()

    clean_bg_url, bg_err = gemini.generate_image(
        subject_removal_prompt,
        refs=[{"url": img, "type": "subject"}],
        aspect_ratio=aspect_ratio,
    )
    t.join()

    return (output, clean_bg_url)


def parse_user_provided_character(character_ref_url):
    character_map = {}
    try:
        if not isinstance(character_ref_url, dict):
            raise Exception("safe error, character ref not an object/dictionary")

        for ch in character_ref_url.keys():
            character_map[ch] = character_ref_url.get(ch)

        logger.debug("character ref map", character_map)

    except Exception as e:
        logger.error("character ref error : %s", e)

    return character_map


def get_prompt_character_ref_urls(
    chatbot,
    image_descriptors,
    user_characters,
    character_list,
    image_engine,
    styles,
    outdir,
):
    ref_urls = []
    prompts = []

    for (p, ch) in image_descriptors:
        ch_url = None
        character_data = match_character(ch, user_characters, character_list)

        if character_data != None:
            is_url, match_data = character_data

            if not is_url:
                # if is_url false then its the index of chracter_list
                character = character_list[match_data]
                desp = character["description"]
                fictional = character.get("fictional", False)
                search = character.get("search", ch)

                # gen
                urls = []

                if search and (not fictional or fictional == "false"):
                    search_out = multi_google_search(
                        chatbot, [search], outdir=outdir, animate=False
                    )

                    if len(search_out) > 0 and search_out[0] and search_out[0][0]:
                        ch_url = search_out[0][0]
                        character_list[match_data]["url"] = ch_url
                        logging.info(f"character ({ch}) ref searched : {ch_url}")

                if not ch_url:
                    logging.info(f"generating character image: {character.get('name')}")
                    urls, _, gen_map, errors, logs = image_gen(
                        [desp], [None], outdir, {"name": image_engine}, chatbot
                    )

                    if errors and len(errors) > 0 and errors[0]:
                        raise ExceptionWithLogs(
                            "Error while generating character images", logs
                        )

                    if urls == None or len(urls) < 1:
                        logging.error(f"error while generating character ({ch}) image!")
                    logging.info(f"character ({ch}) ref generated : {urls[0]}")

                    # caching
                    character_list[match_data]["url"] = urls[0]
                    character_list[match_data]["image_engine"] = gen_map[urls[0]]
                    ch_url = urls[0]

                logger.info("Using character reference url: %s", ch_url)
            elif match_data:

                if "baasha" not in match_data and "pataka" not in match_data:
                    # downloading to save user images in s3
                    character_image = download_file(
                        match_data,
                        f"{outdir}/character_{ch.strip().replace(' ', '')}",
                    )
                    ch_url = upload_image(character_image)

                else:
                    ch_url = match_data

        ref_urls.append(ch_url)
        prompts.append(p)
    chatbot.delete_conversation()

    return prompts, ref_urls


def generate_dummp_video_data(story, bgm, search_images, text_styling, content_type):
    story_length = len(story)

    return {
        "images": [],  # ["-1"] * story_length,
        "audios": [],  # [("-1", 0)] * story_length,
        "bgm": bgm,
        "text": story,
        "search_images": search_images,
        "text_styling": text_styling,
        "content_type": content_type,
    }


def narrator_avatar_gen(
    avatar_engine, text, audio, source_face, tts_toolkit, voice_name
):
    if avatar_engine.startswith("gooey"):
        tts_info = {"engine": tts_toolkit, "voice_id": voice_name}
        return (
            gooey_ai.lip_sync(source_face, text, tts_info),
            True,
        )

    elif (
        avatar_engine.startswith("replicate")
        or avatar_engine.startswith("omnihuman")
        or avatar_engine.startswith("lemon_slice")
    ):
        if not audio:
            logging.info("no audios in video data!")
            return None, None, False

        lip_sync_video = None

        if avatar_engine.startswith("omnihuman"):
            lip_sync_video = eachlabs_ai.lip_sync(source_face, audio)

        if avatar_engine.startswith("lemon_slice"):
            lip_sync_video = lemon_slice_ai.lip_sync(source_face, audio)

        else:
            lip_sync_video = replicate_api.lip_sync(
                avatar_engine, source_face, audio, upload=True
            )

        # try:
        #    (v1, v2) = replicate_api.remove_background(
        #        lip_sync_video, use_chroma_key=True, upload=True
        #    )
        #    return lip_sync_video, v2, False
        # except Exception as e:
        #    logging.error(f"error while pre-processing lip sync video: {e}")

        return lip_sync_video, None, True

    logging.info(f"invalid avatar engine! {avatar_engine}")
    return None, None, False


@errors.propogate_ctx_errors
def generate_video_data(
    story,
    content_type,
    image_urls,
    image_descriptors,
    character_list,
    character_ref_url,
    character_avatar_map,
    primary_voice_detail,
    character_voice_detail_map,
    bgm_name,
    image_config,
    search_images,
    out_dir,
    styles,
    data_dict,
    chatbot,
    style_reference_urls=None,
    stop_after_images=False,
):

    threads_store = {}
    data_store = {"image_gen": None, "avatar_gen": None, "search_images": None}
    data = data_dict
    vision_chatbot = None

    if not data.get("gen_stages"):
        data["gen_stages"] = []

    def is_stage_completed(st):
        return st in data["gen_stages"]

    def on_stage_complete(st):
        data["gen_stages"].append(st)

    def cb(key, store):
        def update(v):
            if isinstance(key, str) and isinstance(store, dict):
                store[key] = v

        return update

    story_lines = None

    if isinstance(story, list):
        if content_type == "conversation":
            story_lines = list(map(lambda x: x["text"], story))
        else:
            story_lines = story
    else:
        story_lines = story.strip().split(".")

    # text updated
    data["text"] = story if content_type == "conversation" else story_lines
    data["content_type"] = content_type
    on_stage_complete(AssetGenStages.TEXT)

    if image_urls and len(image_urls) > 0:
        data["images"] = image_urls

    elif not is_stage_completed(AssetGenStages.IMAGE):
        if len(image_descriptors) > 0:
            prompts, ref_urls = get_prompt_character_ref_urls(
                chatbot,
                image_descriptors,
                character_ref_url,
                character_list,
                image_config.get("name"),
                styles,
                out_dir,
            )

            if style_reference_urls:
                ref_urls = [
                    ([{"url": r, "type": "subject"}] if r else [])
                    + [
                        {
                            "url": s,
                            "type": "style",
                            "name": "COMPLETELY IGNORE any faces, identities, or characters in this image. Use it EXCLUSIVELY for lighting, color grading, and texture only.",
                        }
                        for s in style_reference_urls
                    ]
                    for r in ref_urls
                ]

            logging.info(f"starting image generation!")

            threads_store["image_gen"] = other_utils.threaded_task(
                "IMAGE_GEN",
                image_gen,
                cb("image_gen", data_store),
                prompts,
                ref_urls,
                out_dir,
                image_config,
                chatbot,
            )
            threads_store["image_gen"].start()

            logging.info("image generation queued")

    if not is_stage_completed(AssetGenStages.SEARCH) and search_images:
        vision_chatbot = BaashaChat.ChatInterface("gemini-2.0-flash")
        vision_chatbot.new_conversation()
        t = other_utils.threaded_task(
            "IMAGE_SEARCH",
            multi_google_search,
            cb("search_images", data_store),
            vision_chatbot,
            search_images,
            image_config.get("width"),
            image_config.get("height"),
            True,
            out_dir,
            True,
        )
        threads_store["search_images"] = t
        t.start()

    if not stop_after_images and not is_stage_completed(AssetGenStages.AUDIO):
        try:
            audios: list[tuple[str, float]] = []
            if content_type == "conversation":
                audio_timepoints = {}

                for s in story:
                    v = (
                        character_voice_detail_map.get(s["character"])
                        or primary_voice_detail
                    )
                    (auds, tpoints, _) = other_utils.text_to_speech(
                        [s["text"]],
                        v.id,
                        v.tts_toolkit,
                        voice_description=getattr(v, "description", None),
                    )
                    audios = audios + auds
                    audio_timepoints.update(tpoints)
            elif data.get("cinematic"):
                audio_timepoints = {}

                for idx, c in enumerate(data["cinematic"]):
                    if c["audio_type"] == "dialogue":
                        speaker = c.get("speaker")
                        text_line = story_lines[idx]

                        v = (
                            character_voice_detail_map.get(speaker)
                            if character_voice_detail_map and speaker
                            else None
                        ) or primary_voice_detail

                        (auds, tpoints, _) = other_utils.text_to_speech(
                            [text_line],
                            v.id,
                            v.tts_toolkit,
                            voice_description=getattr(v, "description", None),
                        )
                        audios = audios + auds
                        audio_timepoints.update(tpoints)
                    else:
                        silence_dur: float = c["duration"]
                        audios.append(("-1", silence_dur))
            else:
                (
                    audios,
                    audio_timepoints,
                    _,
                ) = other_utils.text_to_speech_as_single_audio(
                    story_lines,
                    primary_voice_detail.id,
                    primary_voice_detail.tts_toolkit,
                )

            # audio gen updated
            data["audios"] = audios
            data["timepoints_map"] = audio_timepoints
            data["is_word_timepoints"] = True

            on_stage_complete(AssetGenStages.AUDIO)
        except Exception as e:
            logging.info(f"audio TTS Error: {e}")

    if not stop_after_images and not is_stage_completed(AssetGenStages.AVATAR):
        narrator_avatar = character_ref_url.get("narrator_avatar")
        narrator_avatar_url = character_ref_url.get("narrator_avatar_url")

        if character_avatar_map:
            data["character_avatar_map"] = character_avatar_map

        if narrator_avatar:
            local_image = download_file(
                narrator_avatar,
                f"{out_dir}/character_narrator_avatar",
            )
            narrator_avatar = upload_image(local_image)

        if narrator_avatar_url:
            data["narrator_avatar"] = {
                "url": narrator_avatar_url,
                "url2": None,
                "has_audio": True,
            }
            on_stage_complete(AssetGenStages.AVATAR)

        elif not stop_after_images and narrator_avatar:
            threads_store["avatar_gen"] = other_utils.threaded_task(
                "AVATAR_GEN",
                narrator_avatar_gen,
                cb("avatar_gen", data_store),
                "lemon_slice",
                story_lines,
                audios[0][0],
                narrator_avatar,
                primary_voice_detail.tts_toolkit,
                primary_voice_detail.id,
            )
            threads_store["avatar_gen"].start()

    if not stop_after_images and not is_stage_completed(AssetGenStages.BGM):
        data["bgm"] = other_utils.get_bgm_from_name(bgm_name)
        on_stage_complete(AssetGenStages.BGM)

    if threads_store.get("image_gen"):
        try:
            threads_store["image_gen"].join()
            image_gen_result = data_store["image_gen"]
            if image_gen_result:
                (
                    image_urls,
                    image_prompts,
                    image_engine_map,
                    errors,
                    logs,
                ) = image_gen_result

                data["images"] = image_urls
                if image_urls and len(image_urls) > 0:
                    focus_directions = image_search_agent.find_image_focus_direction(
                        image_urls, chatbot
                    )
                    data["image_focus_directions"] = focus_directions

                # data["final_image_prompts"] = image_prompts
                # data["image_engine_map"] = image_engine_map
                data["image_gen_logs"] = logs

                error_map = {}
                if errors:
                    for (i, e) in enumerate(errors):
                        error_map[str(i)] = e
                data["image_gen_errors"] = error_map

                on_stage_complete(AssetGenStages.IMAGE)
        except Exception as e:
            logging.error(f"Error while processing images - {e}")
            pass

    if threads_store.get("avatar_gen"):
        try:
            threads_store["avatar_gen"].join()
            avatar_gen_result = data_store["avatar_gen"]
            if avatar_gen_result:
                output: str | None
                processed_output: str | None
                has_audio: bool
                output, processed_output, has_audio = avatar_gen_result
                if output:
                    data["narrator_avatar"] = {
                        "url": processed_output,
                        "url2": output,
                        "has_audio": has_audio,
                    }
                    on_stage_complete(AssetGenStages.AVATAR)
        except Exception as e:
            logging.error(f"Error while processing avatar - {e}")
            pass

    if threads_store.get("search_images"):
        threads_store["search_images"].join()

        data["search_images"] = data_store["search_images"]
        if vision_chatbot:
            vision_chatbot.delete_conversation()
        on_stage_complete(AssetGenStages.SEARCH)

    return data


def parse_backtick(a, lang="json"):
    try:
        s = a.find(f"```{lang}")
        if s != -1:
            e = a.find("```", s + len(lang) + 3)
            if e != -1:
                return a[s + len(lang) + 3 : e]

        return None
    except:
        return None


def edit_video_config(video_data, ai_edits):
    edited: Optional[str] = None
    if ai_edits:
        conf = other_utils.get_video_config(video_data)
        chatbot = BaashaChat.ChatInterface("gemini-2.5-flash-preview-05-20")
        chatbot.new_conversation()

        quest = get_prompt_text("edit-video-config").format(
            JSON=json.dumps(conf), QUERY=ai_edits
        )
        res = generate_data(chatbot, "ai_edit_video_config", quest)
        parsed = parse_backtick(res, lang="js") or parse_backtick(
            res, lang="javascript"
        )

        if parsed:
            edited = parsed

        chatbot.delete_conversation()

    return edited


def generate_remotion_video_config(video_data):
    conf = other_utils.get_video_config(video_data)

    return other_utils.get_video_config_url(conf)


def initialize_conversation(chatbot):
    conv_id = chatbot.new_conversation()
    logger.info("Starting conversation %s", str(conv_id))
    return conv_id


def fetch_and_upscale_images(idea_id, version, image_urls=None):
    out_dir = f"/tmp/{idea_id}.{version}"
    image_paths = []
    for image_url in image_urls:
        image_path = download_file(image_url, out_dir)
        if image_path:
            image_paths.append(image_path)
    urls = stability_generator.upscale_images(image_paths, out_dir)
    return urls


def download_file(url, directory, force_ext=None, prefix=""):
    os.makedirs(directory, exist_ok=True)
    filename = os.path.join(directory, prefix + str(uuid4()))
    response = requests.get(url)

    content_type = response.headers["content-type"]

    ext = force_ext or (
        content_type.split("/")[-1] if content_type else url.split(".")[-1]
    )
    if ext:
        ext = "." + ext

    filename = filename + ext

    if response.status_code == 200:
        with open(filename, "wb") as file:
            file.write(response.content)
        logger.info(f"Downloaded {url} to {filename}")
        return filename
    else:
        logger.error(f"Failed to download {url}. Status code: {response.status_code}")
        return None


def remove_line_endings(paragraph):
    """Remove all line endings from a given paragraph."""
    # Replace both '\n' and '\r' characters with an empty string
    no_newlines = paragraph.replace("\n", "").replace("\r", "")
    return no_newlines


def extract_json(text):
    # Find all JSON objects in the text
    matches = re.findall(r"\{.*?\}", remove_line_endings(text))
    # Parse each match as JSON and return if it's valid
    for match in matches:
        try:
            obj = json.loads(match)
            return obj
        except ValueError as ve:
            logger.error("Value error:", ve)
            continue


def get_search_queries_with_styling(chatbot, raw_sentences):
    quest = get_prompt_text("search-queries-and-styling").format(
        STORY="\n-".join(raw_sentences)
    )
    output = generate_data(chatbot, "search-images-and-styling", quest)

    res = markdown_parse(output, lang="json")
    j = json.loads(res)

    data: Dict[str, list] = {"text_styling": [], "search_image": []}

    for o in j:
        data["text_styling"].append(o["text_styling"])
        data["search_image"].append(o["search_query"])

    logging.info(f"search-and-styling: {data}")

    return data["text_styling"], data["search_image"]


def extract_style_from_references(chatbot, style_refs: list[str]) -> Optional[str]:
    if not style_refs:
        return None
    try:
        # Limit to a maximum of 3 images as requested
        target_urls = style_refs[:3]
        logging.info(
            f"Extracting shared visual style tags from {len(target_urls)} reference image(s): {target_urls}"
        )

        chat_parts = []
        for i, url in enumerate(target_urls):
            res = requests.get(url, timeout=10)
            res.raise_for_status()
            img_bytes = res.content

            # Inject prompt ONLY on the last part to avoid redundancy
            is_last = i == len(target_urls) - 1
            prompt = ""
            if is_last:
                prompt = (
                    "Analyze the shared artistic visual style across these reference images. "
                    "Describe their core photographic medium, aesthetic style, color temperature, "
                    "lighting warmth/coolness, and film grain in 3 to 7 highly descriptive, "
                    "comma-separated natural English terms (e.g., 'gritty documentary photograph, warm retro film tones, deep shadows, authentic analog grain'). "
                    "Return ONLY the comma-separated style terms. Do not add any introductory text, prefix, markdown, or punctuation outside the terms."
                )
            chat_parts.append(Img(_bytes=img_bytes, text=prompt))

        desc = chatbot.fetch_text(chat_parts)
        if desc:
            desc = desc.strip().replace('"', "").replace("`", "")
            logging.info(f"Extracted shared style description: '{desc}'")
            return desc
    except Exception as e:
        logging.error(f"Failed to extract style from references: {e}")
    return None


def split_text_into_sentences_with_styling(
    chatbot,
    raw_text,
    content_type,
    image_styles=None,
    character_names=None,
    style_refs=None,
    prompt_overrides=None,
):
    is_story = content_type == "reel"

    prompt_key = (
        "content-gen-split-and-styling" if not is_story else "story-split-and-styling"
    )
    quest = (
        get_prompt_text(prompt_key, overrides=prompt_overrides).format(
            CONTENT_TYPE=content_type, STORY=raw_text
        )
        if not is_story
        else get_prompt_text(prompt_key, overrides=prompt_overrides).format(
            STORY=raw_text
        )
    )

    image_prompt_spec = get_image_prompt_spec(is_styled=bool(style_refs)) or ""
    viral_spec = get_viral_story_spec() or ""
    quest = image_prompt_spec + "\n\n" + quest + "\n\n" if image_prompt_spec else quest
    quest = viral_spec + "\n\n" + quest if viral_spec else quest

    if character_names:
        char_instruction = (
            "\n\nCRITICAL CHARACTER CAST: You MUST explicitly use the following specific character names in your scene descriptions. Do not invent new character names or use pronouns for these subjects:\n"
            + str(character_names)
        )
        quest = quest + char_instruction

    if image_styles:
        style_text = (
            image_styles.to_text()
            if hasattr(image_styles, "to_text")
            else str(image_styles)
        )
        logging.info(f"image styles: {style_text}")
        quest += f"\n\nCRITICAL VISUAL CONSTRAINT: The user has explicitly requested the following visual styles, themes, and camera aesthetics: '{style_text}'. Ensure ALL generated image descriptions strictly align with this style request. If the requested style implies a non-realistic medium (e.g., Anime, Painting, Sketch), prioritize the requested medium over the 'realistic' default mentioned in the spec."

    output = generate_data(chatbot, prompt_key, quest)
    res = markdown_parse(output, lang="json")
    j = json.loads(res)

    data: Dict[str, list] = {
        "text": [],
        "text_styling": [],
        "search_image": [],
        "gen_images": [],
        "cinematic": [],
    }

    shots = j.get("shots", []) if isinstance(j, dict) and "shots" in j else j
    set_registry = j.get("set_registry", {}) if isinstance(j, dict) else {}

    location_last_panel: Dict[str, int] = {}
    previous_location_id = None

    for i, o in enumerate(shots):
        sentence = o.get("sentence", "")
        data["text"].append(sentence)
        data["text_styling"].append(o.get("text_styling") if is_story else None)

        src = o.get("image_source") if is_story else o.get("image_description")

        motion_prompt = o.get("motion_prompt")
        prev_motion = o.get("state_transition_prompt")

        if prev_motion and motion_prompt:
            motion_prompt = f"start: {prev_motion}, end: {motion_prompt}"

        if o.get("audio_type") == "dialogue" and motion_prompt:
            motion_prompt = f"{motion_prompt}, dialogue: {sentence}"

        # Capture cinematic metadata
        data["cinematic"].append(
            {
                "duration": o.get("duration"),
                "speaker": o.get("speaker"),
                "motion_prompt": motion_prompt,
                "shot_type": o.get("shot_type"),
                "audio_type": o.get("audio_type"),
                "transition": o.get("transition"),
                "location_id": o.get("location_id"),
                "relative_prior_shot_index": o.get("relative_prior_shot_index"),
                "state_transition_prompt": o.get("state_transition_prompt"),
            }
        )

        # Inject the forensic set description programmatically
        loc_id = o.get("location_id")
        loc_edits = o.get("location_edits", "")

        if isinstance(loc_edits, str):
            loc_edits = loc_edits.strip()

        if loc_id and loc_id in set_registry:
            set_desc = set_registry[loc_id]
            panel_num = i + 1
            edit_text = f" SET MODIFICATIONS: {loc_edits}" if loc_edits else ""

            if loc_id == previous_location_id:
                # Sequential continuation
                prefix = f"Continuing in the exact same location as the previous panel.{edit_text} "
            elif loc_id in location_last_panel:
                # Cross-cutting / Returning to a location from an earlier panel
                last_seen = location_last_panel[loc_id]
                prefix = f"Returning to the EXACT same spatial location and room geometry previously established in Panel {last_seen}.{edit_text} "
            else:
                # First time seeing this location
                prefix = f"Establishing Location: {set_desc}.{edit_text} "

            location_last_panel[loc_id] = panel_num
            previous_location_id = loc_id

            # Strip out "AI: " if the model still accidentally includes it
            if src.startswith("AI:"):
                src = src.replace("AI:", "", 1).strip()
            src = f"{prefix}{src}"

        data["search_image"].append(None)
        # Remove AI: prefix in case it's lingering but no loc_id was provided
        if src.startswith("AI:"):
            src = src.replace("AI:", "", 1).strip()
        data["gen_images"].append(src)

    logging.info(f"split-text-search-styling: {data}")

    return (
        data["text"],
        data["text_styling"],
        data["search_image"],
        data["gen_images"],
        data["cinematic"],
    )


def upload_image(local_path):
    return object_storage.upload_file(
        object_storage.ASSETS_IMG_BUCKET,
        local_path,
        os.path.basename(local_path),
        object_storage.ACL_PUBLIC,
    )


def upload_video(local_path):
    return object_storage.upload_file(
        object_storage.ASSETS_VIDEO_BUCKET,
        local_path,
        os.path.basename(local_path),
        object_storage.ACL_PUBLIC,
    )


def enhance_prompts(prompts, styles, image_config):
    if not styles:
        return prompts
    return list(map(lambda x: x + " " + styles.to_text(), prompts))

    # if image_config and not image_config.get("name").endswith("midjourney"):
    #    return prompts

    url = "http://172.235.150.194:8200/enhance/batch"
    headers = {"Content-Type": "application/json"}
    data: Dict[str, Any] = {"prompts": prompts}

    if styles:
        # Remove keys with empty values
        cleaned_dict = {k: v for k, v in asdict(styles).items() if v and len(v) > 0}
        data["style_preferences"] = cleaned_dict

    response = requests.post(url, headers=headers, json=data)

    if response.status_code == 200:
        resp = response.json()["enhanced_prompts"]
        new_prompts = list(map(lambda x: x["enhanced"], resp))

        logging.info(f"enhanced prompts: {new_prompts}")

        return new_prompts

    else:
        logging.error(f"error while prompt enhancement : {response.text}")
        return prompts


def multi_google_search(
    chatbot,
    queries,
    image_width=None,
    image_height=None,
    animate=True,
    outdir=None,
    upload=True,
):
    results: List[Optional[Tuple[str | None, str | None, str | None]]] = []

    for i, q in enumerate(queries):
        results.append(None)

        if not q:
            continue

        try:
            r = google_search_agent(q, chatbot)
            results[i] = r

            if not r or isinstance(r, Exception):
                continue

            if upload:
                local_image = download_file(
                    r[0],
                    f"{outdir}/search_images",
                )
                url = upload_image(local_image)

                if local_image and url:
                    results[i] = (url, r[1], None)

            # lottie_json = None

            # if results[i] and results[i][0]:
            #    lottie_json = motion_graphics_agent.create_lottie_animation(
            #        chatbot,
            #        q,
            #        results[i][0],
            #        image_width=image_width,
            #        image_height=image_height,
            #    )

            # if results[i]:
            #    results[i] = (results[i][0], results[i][1], lottie_json)
        except Exception as e:
            logging.error(
                f"error while searching asset => ${e}. This error won't affect other steps!"
            )

    return results


def get_img_crops(url, boxes, outdir, target_dim=1000):
    # 1. Fetch image from URL
    response = requests.get(url, stream=True)
    if response.status_code != 200:
        logging.info("Failed to grab image")
        return None

    # Convert the response bytes to a numpy array
    image_array = np.asarray(bytearray(response.content), dtype=np.uint8)

    # Decode the array into an OpenCV image
    img = cv2.imdecode(image_array, cv2.IMREAD_COLOR)

    # 3. Rescale full image to 1000x1000
    rescaled_img = cv2.resize(img, (target_dim, target_dim))

    x_ratio, y_ratio = 1, 1
    prefix = uuid4()
    crops = []

    for i, val in enumerate(boxes):
        box = val.get("box_2d")
        ymin = int(box[0])
        xmin = int(box[1])
        ymax = int(box[2])
        xmax = int(box[3])

        # 5. Crop from the rescaled image
        cropped_img = rescaled_img[ymin:ymax, xmin:xmax]
        p = os.path.join(outdir, f"{prefix}_crop_{i}.png")
        cv2.imwrite(p, cropped_img)
        crops.append(p)

    return crops


@errors.propogate_ctx_errors
def create_image_grid(
    prompts: List[str],
    image_config,
    chatbot,
    outdir,
    grid_guidance=None,
    character_refs=None,
    style_refs=None,
    image_styles: Optional[List[str]] = None,
    refine_grid_count=0,
    story_context: str = "",
    skip_splitting=False,
    prompt_overrides=None,
):
    """
    Generates a storyboard grid and optionally performs autonomous refinement passes.
    """
    prompts_desp = "\n".join(
        [f"Panel {index+1}: {item}" for index, item in enumerate(prompts)]
    )
    grid_prompt = get_prompt_text(
        "one-shot-image-grid", overrides=prompt_overrides
    ).format(COUNT=len(prompts), DESCRIPTIONS=prompts_desp)

    # Prepare references
    total_refs = []
    if character_refs:
        total_refs.extend(character_refs)

    if style_refs:
        total_refs.extend(style_refs)
        # Priority 1: Use Style Reference Grounding
        grid_prompt += "\nFollow the style reference for the visual art style, colors, lighting, and overall aesthetic of the provided style reference strictly across all panels."

        # Globally append the extracted visual style terms as a clean semantic anchor
        if image_styles:
            style_text = (
                image_styles.to_text()
                if hasattr(image_styles, "to_text")
                else (
                    ", ".join(image_styles)
                    if isinstance(image_styles, list)
                    else str(image_styles)
                )
            )
            grid_prompt += (
                f"\nGlobal Visual Style Constraint (Semantic Anchor): '{style_text}'"
            )
    elif image_styles:
        # Priority 2: Use generic text-based stylization only if no visual reference exists
        grid_prompt = stylize_image_prompts([grid_prompt], image_styles)[0]

    if grid_guidance:
        grid_prompt += grid_guidance

    logging.info(f"Final Grid Prompt (Ref Priority): {grid_prompt}")

    # Generate Initial Grid
    urls, _, _, _, _ = image_gen(
        [grid_prompt],
        [total_refs],
        outdir,
        image_config,
        chatbot,
    )

    if not urls or urls[0] is None:
        return None, "No image generated", [], grid_prompt

    url = urls[0]
    raw_grids = []

    # Perform Autonomous Refinement Passes if requested
    if refine_grid_count and refine_grid_count > 0:
        logging.info(
            f"Triggering {refine_grid_count} Autonomous Refinement Pass(es)..."
        )
        for i in range(refine_grid_count):
            refined_urls, report = refine_and_fix_grid(
                chatbot,
                url,
                style_refs,
                story_context,
                prompts,
                character_refs,
                image_config,
                grid_guidance,
                outdir,
                prompt_overrides=prompt_overrides,
            )
            if refined_urls and len(refined_urls) > 0:
                raw_grids.append(url)
                url = refined_urls
                logging.info(f"Refinement Pass {i+1} complete. URL : {url}")
            else:
                logging.info(f"Refinement Pass {i+1} resulted in no change or failed.")
                break

    if skip_splitting:
        return (url, None, raw_grids, grid_prompt)

    if len(prompts) == 1:
        return (url, None, raw_grids, grid_prompt)

    grid_panels_prompt = get_prompt_text("bbox-image-grid")
    res = requests.get(url)
    res.raise_for_status()

    grid_img = BaashaChat.Img(_bytes=res.content, text=grid_panels_prompt)
    output = chatbot.fetch_text(grid_img)

    try:
        grid_json = json.loads(markdown_parse(output))
    except Exception as e:
        logging.error(f"Failed to parse bbox json: {e} | Output: {output}")
        return (url, [], raw_grids, grid_prompt)

    crops = get_img_crops(url, grid_json, outdir, target_dim=1000)

    return (url, crops, raw_grids, grid_prompt)


def mk_chatbot_img_prompt(img_url, prompt, max_size=1024):
    res = requests.get(img_url)
    res.raise_for_status()

    img = Image.open(io.BytesIO(res.content))
    if max(img.size) > max_size:
        img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)

    img_byte_arr = io.BytesIO()

    img.convert("RGB").save(img_byte_arr, format="JPEG", quality=85)
    final_bytes = img_byte_arr.getvalue()

    return BaashaChat.Img(_bytes=final_bytes, text=prompt)


def judge_image_grid(
    grid_url,
    grid_refs,
    story_context,
    panel_descriptions,
    character_list,
    chatbot,
    prompt_overrides=None,
):
    """
    Acts as a 'Script Supervisor' using Vision LLM to audit a storyboard grid
    for character identity, wardrobe, and environmental consistency.
    """
    logging.info(f"Auditing grid consistency for: {grid_url}")

    panel_text = "current scene to be judged: \n" + "\n".join(
        [f"Panel {i+1}: {p}" for i, p in enumerate(panel_descriptions)]
    )
    char_text = json.dumps(character_list)

    prompt = get_prompt_text("holistic-grid-judge", overrides=prompt_overrides).format(
        STORY_CONTEXT=story_context or "Refer to the context provided for grounding",
        PANEL_DESCRIPTIONS=panel_text,
        CHARACTER_LIST=char_text,
    )

    prompts = []
    if grid_refs:
        for r in grid_refs:
            grid_ref = mk_chatbot_img_prompt(r["url"], r["desp"])
            prompts.append(grid_ref)

    grid_img = mk_chatbot_img_prompt(grid_url, prompt)
    prompts.append(grid_img)

    output = chatbot.fetch_text(prompts)

    try:
        try:
            report = json.loads(markdown_parse(output))
        except Exception:
            report = json.loads(output)

        logging.info(f"Grid Audit Complete. Score: {report.get('consistency_score')}")
        return report
    except Exception as e:
        logging.error(f"Failed to parse Judge report: {e} | Output: {output}")
        return {
            "consistency_score": 0,
            "holistic_critique": "Failed to parse judge output.",
            "error": str(e),
        }


def refine_and_fix_grid(
    chatbot,
    grid_url,
    grid_refs,
    story_context,
    panel_descriptions,
    character_list,
    image_config,
    prompt_guidance,
    outdir,
    prompt_overrides=None,
):
    """
    Consolidated Batch Refinement: Prompts all fixes together in a single pass.
    Uses the original grid as a subject reference to anchor the evolution.
    """
    grid_refinement_refs = list(
        map(lambda x: {"url": x["url"], "desp": x.get("name", "style ref")}, grid_refs)
    )
    report = judge_image_grid(
        grid_url,
        grid_refinement_refs,
        story_context,
        panel_descriptions,
        character_list,
        chatbot,
        prompt_overrides=prompt_overrides,
    )

    score = report.get("consistency_score", 0)
    if score >= 90:
        logging.info(f"Grid passed audit with score {score}. Skipping refinement.")
        return grid_url, report

    logging.info(
        f"Grid failed audit (Score: {score}). Starting Batch Refinement Pass..."
    )

    # 2. Consolidate ALL fixes into a Master List
    failed_panels = [p for p in report.get("panels", []) if p["status"] == "FAIL"]

    if not failed_panels:
        return grid_url, report

    fix_list_text = ""
    for fp in failed_panels:
        idx = fp["panel_index"]
        directive = fp["fix_directive"]
        unchanged = fp.get("unchanged_elements", "")
        fix_list_text += f"- Panel {idx}:\n  FIX: {directive}\n"
        if unchanged:
            fix_list_text += f"  DO NOT CHANGE: {unchanged}\n"

    # 3. Construct the Batch Refinement Prompt
    batch_refine_prompt = get_prompt_text("grid-refinement-v2").format(
        FIX_LIST=fix_list_text
    )

    logging.info(f"Consolidated Fixes:\n{fix_list_text}")

    # 4. Execute Refinement Pass (Single pas with original grid as reference)
    # We pass the grid URL directly in refs as requested
    total_refs = [
        {
            "type": "scene",
            "url": grid_url,
            "name": "current scene to be edited, fixed and re-created",
        }
    ]

    if grid_refs:
        total_refs.extend(grid_refs)

    if prompt_guidance:
        batch_refine_prompt += f"\n{prompt_guidance}"

    # Enforce style-agnostic preservation of original grid texture, lighting, and medium
    batch_refine_prompt += (
        "\nCRITICAL: The refined grid must perfectly inherit the exact visual medium, art style, "
        "texture details, detail density, lighting, and contrast of the provided reference grid [current scene to be edited, fixed and re-created]. "
        "Do NOT introduce digital over-sharpening, high local contrast, artificial specular highlights, or plasticy smoothing. "
        "Ensure all panel textures, backgrounds, and subjects feel organic and 100% style-consistent with the input reference."
    )

    if grid_refs:
        # Re-ground the style reference strictly to protect color/aesthetic alignment
        batch_refine_prompt += "\nFollow the style reference for the visual art style, colors, lighting, and overall aesthetic of the provided style reference strictly across all panels."

    logging.info(f"grid refine prompt : {batch_refine_prompt}")
    logging.info(f"grid refine refs : {total_refs}")

    urls, _, _, _, _ = image_gen(
        [batch_refine_prompt],
        [total_refs],
        outdir,
        image_config,
        chatbot,
    )

    if not urls or urls[0] is None:
        return grid_url, report

    return urls[0], report


def get_similar_video(text, data=None, blacklist=[]):
    if not data:
        with open("vid.json", "r") as f:
            data = json.loads(f.read())

    default_val = (0, None)
    maxx = 0.8

    for a in range(0, len(data), 20):
        to_compare = data[a : min(len(data), a + 20)]
        to_cmp_desp = list(map(lambda x: x["desp"], to_compare))

        res = text_embeddings.embedding_gemini_compare(text, to_cmp_desp)

        if res:
            for i, r in enumerate(res):
                if (
                    to_compare[i].get("video_link") in blacklist
                    or to_compare[i].get("desp") in blacklist
                ):
                    continue

                if r >= maxx:
                    return to_compare[i]

                elif r >= (maxx - 0.1) and r >= default_val[0]:
                    default_val = (r, to_compare[i])

    return default_val[1]


@errors.log_ctx_errors
def generate_moodboard(
    chatbot, topic: str, ctx: Optional[str], num_styles: int, outdir: str
) -> List[Dict[str, Any]]:
    """
    Brainstorms artistic styles and generates consistent image grids.
    Leverages internet-grounded context searching.
    """
    from concurrent.futures import ThreadPoolExecutor

    if ctx:
        # Natively cache the grounded context via Gemini Search
        build_and_set_script_context(chatbot, f"Topic: {topic}\nContext: {ctx}")

    p_text = get_prompt_text("moodboard-style-generation")
    p_text = p_text.replace("{num_styles}", str(num_styles))

    image_prompt_spec = ""  # get_image_prompt_spec() or ""
    q_text = image_prompt_spec + "\n\n" + p_text if image_prompt_spec else p_text
    q_text = q_text + f"\n\nUser Input:\nTopic: {topic}"
    res_str = generate_data(chatbot, "moodboard_gen", q_text)
    logging.info(f"moodboard_gen raw response: {res_str}")

    try:
        res = json.loads(markdown_parse(res_str, lang="json"))
        styles = res.get("styles", [])
    except Exception as e:
        logging.error(f"Failed to parse moodboard JSON: {e}")
        return []

    moodboard_results = []

    def process_style(st):
        style_name = st.get("style_name", "Unknown Style")
        reasoning = st.get("reasoning", "")
        panels = st.get("panels", [])

        if len(panels) > 0:
            # Create a unique directory for this style's assets
            local_out_dir = os.path.join(outdir, str(uuid4()))
            os.makedirs(local_out_dir, exist_ok=True)

            try:
                grid_url, _ = create_image_grid(
                    prompts=panels,
                    image_config={"name": "gemini_nano_banana", "aspect_ratio": "16:9"},
                    chatbot=chatbot,
                    outdir=local_out_dir,
                    skip_splitting=True,
                    image_styles=[style_name],
                    refine_grid_count=0,
                )
                return {
                    "style_name": style_name,
                    "reasoning": reasoning,
                    "grid_url": grid_url[0] if grid_url else None,
                    "panels": panels,  # Return the 8 text prompts for context
                }
            except Exception as e:
                logging.error(f"Failed to generate grid for style {style_name}: {e}")
                return None
        return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(process_style, styles))

    # Filter out None results from failed styles
    moodboard_results = [r for r in results if r is not None]

    return moodboard_results


def segment_image_layer(chatbot, image_path: str, output_path: str):
    """
    Downloads an image from image_url, uses Gemini 2.5 via ChatInterface to segment the subject
    highlighted with a border (e.g., yellow outline), applies a feathering to the mask,
    and saves the extracted subject with a transparent background to output_path.
    """

    with open(image_path, "rb") as f:
        img_bytes = f.read()

    im_original = Image.open(io.BytesIO(img_bytes))

    prompt = """Give the segmentation masks for the main subjects in the image. Output a JSON list of segmentation masks where each entry contains the 2D bounding box in the key "box_2d", the segmentation mask in key "mask", and the text label in the key "label". Use descriptive labels. If the mask is returned as polygon points, output them as a list of [y, x] coordinates in the 0-1000 range.
    """

    logging.info("Calling Gemini for segmentation mask...")
    p_img = BaashaChat.Img(_bytes=img_bytes, text=prompt)
    json_output = chatbot.fetch_text(p_img)

    if not json_output:
        raise ValueError("No response from Gemini segmentation")

    try:
        items = json.loads(markdown_parse(json_output, lang="json"))
        logging.info(f"segmentation-output: {items}")
    except Exception as e:
        logging.error(f"Failed to parse JSON from Gemini: {json_output}")
        raise e

    if not items or len(items) == 0:
        raise ValueError("No segmentation masks returned from Gemini")

    full_mask = np.zeros((im_original.size[1], im_original.size[0]), dtype=np.uint8)
    for item in items:
        print("item key", list(item.keys()))

        mask_data_raw = item.get("mask")
        if not mask_data_raw:
            raise ValueError("No mask data found in the response")

        if isinstance(mask_data_raw, list):
            # Mask is a list of polygon coordinates [y, x] in normalized 0-1000 scale
            pts = []
            for point in mask_data_raw:
                y_norm, x_norm = point
                y = int(y_norm / 1000 * im_original.size[1])
                x = int(x_norm / 1000 * im_original.size[0])
                pts.append([x, y])

            pts = np.array(pts, np.int32)
            pts = pts.reshape((-1, 1, 2))
            cv2.fillPoly(full_mask, [pts], 255)

        else:
            raise ValueError(f"Unexpected mask format: {type(mask_data_raw)}")

    # Feathering (Gaussian Blur k=7 as requested in specs)
    # full_mask = cv2.GaussianBlur(full_mask, (7, 7), 0)

    # Convert original to RGBA
    if im_original.mode != "RGBA":
        im_original = im_original.convert("RGBA")

    np_img = np.array(im_original)

    # Set alpha channel based on the full_mask
    np_img[:, :, 3] = full_mask

    p = output_path.split(".")
    p[-2] = p[-2] + "_temp"
    temp_output_path = ".".join(p)

    final_img = Image.fromarray(np_img)
    final_img.save(output_path, format="PNG")
    logging.info(f"Saved segmented image to {output_path}")

    # utils.remove_background_using_border(temp_output_path, output_path)
    return output_path


if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    a = """Let’s clear something up—automation is not the same as AI, and AI is not always as smart as you think.  \r\n\r\nBasic automation? That’s like giving a strict rulebook to a third grader. “If apple, pick red. If orange, pick orange.” No thinking, no creativity—just rules."""

    # b = split_text_into_sentences_with_styling(None, a, "story")
    # logging.info(b)
