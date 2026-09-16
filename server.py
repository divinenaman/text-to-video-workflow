from baasha_pipeline import gemini
import certifi
import boto3
from pydantic import conbytes
import supabase as sb
from datetime import datetime, timedelta
from sqlalchemy.orm import make_transient
from sqlalchemy.exc import IntegrityError
from sqlalchemy import desc, inspect, func
from flask_restful import Resource, Api, marshal_with, abort
from flask import Flask, jsonify, send_from_directory, request
from elevenlabs.client import ElevenLabs
import requests
from flask_restful.reqparse import RequestParser
from flask_restful import reqparse
import time
import os
import multiprocessing
import uuid
import redis
import logging
import configparser

# Initialize Valkey (Redis) Client for Session Locks
valkey_client = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)

from datetime import datetime, date, timedelta

from models import (
    AssetGenStages,
    BackgroundMusic,
    Draft,
    Idea,
    Styles,
    Voice,
    db,
    DraftStages,
    create_new_db_session,
)
from parsers import (
    bgm_parser,
    idea_parser,
    draft_parser,
    style_parser,
    voice_parser,
    bgm_resource_fields,
    style_resource_fields,
    voice_resource_fields,
    moodboard_parser,
    image_layers_test_parser,
    viral_story_parser,
)
import supabase_middleware
from processor import (
    verify_subject_continuity,
    ExceptionWithLogs,
    build_and_set_script_context,
    create_image_grid,
    download_file,
    generate_dummp_video_data,
    generate_story_and_title,
    generate_image_prompts,
    generate_character_bible,
    generate_phrase_sound_effects,
    get_phrase_sound_effects,
    get_search_queries_with_styling,
    get_word_sound_effects,
    judge_image_grid,
    refine_and_fix_grid,
    narrator_avatar_gen,
    segment_image_layer,
    split_text_into_sentences_with_styling,
    stylize_image_prompts,
    generate_video_data,
    generate_remotion_video_config,
    edit_video_config,
    fetch_and_upscale_images,
    upload_video,
    upload_image,
    image_gen,
    get_prompt_character_ref_urls,
    judge_and_fix_images,
    generate_data,
    get_prompt_text,
    parse_user_provided_character,
    multi_google_search,
    get_similar_video,
    create_image_layer,
    test_story_gen,
    build_script_context,
    subject_removal_prompt,
    StyleData,
    to_style_data,
)
import test as T

import json
from baasha_pipeline.configs import app_config as baasha_pipeline_config
from baasha_pipeline.configs import remotion_ui_confs as ui_configs
import baasha_pipeline.other_utils as baasha_utils
import baasha_pipeline.utils as baasha_pipeline_utils

import baasha_pipeline.chatbot as BaashaChat
import baasha_pipeline.hugging_face.hug_chat as HugChat
import baasha_pipeline.open_whisper as OpenWhisper
import baasha_pipeline.insta_download as InstaDownload
import baasha_pipeline.vosk_toolkit as VoskToolkit
import baasha_pipeline.groq as Groq
from baasha_pipeline.prompts import splitters as PromptSplitters
from baasha_pipeline import (
    text_embeddings,
    image_search_agent,
    object_storage,
    build_scraper,
    errors,
    replicate_api,
    fal,
)
from baasha_pipeline import goapi_flux as GoAPI
from baasha_pipeline import gooey_ai as GooeyAPI

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any, Any

from functools import wraps
from logging.config import dictConfig


class CustomJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


app = Flask(__name__)
app.json_encoder = CustomJSONEncoder

api = Api(app)
config = configparser.ConfigParser()
config.read("config.ini")
logger = app.logger

local_cache = os.path.join(os.path.dirname(__file__), "tmp")
os.makedirs(local_cache, exist_ok=True)

supabase: Optional[sb.Client] = None
render_service_creds = None


def with_app_context(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        with app.app_context():
            return f(*args, **kwargs)

    return decorated_function


def load_prod_env(app):
    global supabase
    global render_service_creds

    env = config["ENV"]

    database_mode = os.getenv("DATABASE_MODE", None) or env["DATABASE-MODE"]

    # choose db using env-mode
    is_prod_db = database_mode == "PROD"
    is_staging = database_mode == "STAGING"

    db_config = (
        config["DATABASE-PROD"]
        if is_prod_db
        else (config["DATABASE-STAGING"] if is_staging else config["DATABASE-DEV"])
    )

    db_uri = "{engine}://{user}:{passwd}@{host}:{port}/{db}".format(
        engine=db_config["engine"],
        user=db_config["user"],
        passwd=db_config["passwd"],
        port=db_config["port"],
        db=db_config["database"],
        host=db_config["host"],
    )
    if is_prod_db or is_staging:
        db_uri = f"{db_uri}?sslmode=require&sslcompression=0"
    app.config["SQLALCHEMY_DATABASE_URI"] = db_uri
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_recycle": 60,
        "pool_pre_ping": True,
    }

    # load eleven_labs api-key
    eleven_labs_apikey = config["ELEVENLABS"]["API_KEY"]

    db.init_app(app)

    app.app_context().push()
    # Create tables if they don't exist
    db.create_all()

    # Supabase DB
    supa_url: str = config["SUPABASE"]["URL"]
    supa_key: str = config["SUPABASE"]["KEY"]
    supabase = sb.create_client(supa_url, supa_key)

    flare_service = config["FLARE"]
    tts_service = config["TTS"]

    # baasha-pipeline config
    #
    # 1. selecting log path, tts toolkit: gtts, eleven_labs, coqui
    baasha_pipeline_config.set(
        "log_path",
        config.get("LOGGING", "LOG_FILE", fallback="/tmp/baasha-service-api.log"),
    )
    baasha_pipeline_config.set("tts_toolkit", tts_service["TOOLKIT"])
    baasha_pipeline_config.set("coqui_server", tts_service["COQUI"])
    baasha_pipeline_config.set("primary_chatbot", config["PREFS"]["PRIMARY_CHATBOT"])

    # 2. setup local cache for audios/media download
    baasha_pipeline_config.set("tmp_path", local_cache)
    baasha_pipeline_config.set("chat_cache", local_cache)

    # 3. set tokens
    token_dir = os.path.join(os.path.dirname(__file__), "tokens")
    baasha_pipeline_auth_config = baasha_pipeline_config.get()["auth"]
    baasha_pipeline_auth_config["eleven_labs_key"] = eleven_labs_apikey
    baasha_pipeline_auth_config["sarvam_ai_key"] = config["SECRETS"]["SARVAM_AI"]

    # login to insta
    # InstaDownload.login()

    with open(os.path.join(token_dir, "linode_object_storage.json")) as f:
        baasha_pipeline_auth_config["object_storage"] = json.load(f)

    with open(os.path.join(token_dir, "aws_render.json")) as f:
        render_service_creds = json.load(f)

    baasha_pipeline_auth_config["playgroundAI_cookie"] = os.path.join(
        token_dir, "playgroundAI.json"
    )
    baasha_pipeline_auth_config["hugchat_cookie"] = os.path.join(
        token_dir, "hugchat.json"
    )
    baasha_pipeline_auth_config["stability_ai_key"] = config["SECRETS"][
        "STABILITY_AI_KEY"
    ]
    baasha_pipeline_auth_config["goapi_midjourney_key"] = config["SECRETS"][
        "GOAPI_MIDJOURNEY_KEY"
    ]
    baasha_pipeline_auth_config["ideogram_key"] = ""
    baasha_pipeline_auth_config["slack_token"] = config["SECRETS"]["SLACK_TOKEN"]
    baasha_pipeline_auth_config["google_genai_key"] = config["SECRETS"][
        "GOOGLE_GENAI_KEY"
    ].split(", ")
    baasha_pipeline_auth_config["google_genai_image_key"] = config["SECRETS"][
        "GOOGLE_IMAGE_GEN"
    ]
    baasha_pipeline_auth_config["groq_key"] = config["SECRETS"]["GROQ_KEY"].split(", ")
    baasha_pipeline_auth_config["replicate_token"] = config["SECRETS"][
        "REPLICATE_TOKEN"
    ]
    baasha_pipeline_auth_config["eachlabs_ai_token"] = config["SECRETS"][
        "EACHLABS_AI_TOKEN"
    ]
    baasha_pipeline_auth_config["lemon_slice_ai_token"] = config["SECRETS"][
        "LEMON_SLICE_AI_TOKEN"
    ]
    baasha_pipeline_auth_config["fal_token"] = config["SECRETS"]["FAL_KEY"]
    baasha_pipeline_auth_config["hf_token"] = config["SECRETS"]["HF_TOKEN"]

    baasha_pipeline_config.set("auth", baasha_pipeline_auth_config)

    global_ctx = """You are a viral short video content creator who have cracked the formula for platforms like instagram reels, youtube shorts. With your experience you are able to
    create a short form video out of a short script applying all the learnings from your exprience. You apply your learnings in videography, cinematography and directive skills. A student is asking your input on how they can think and create like you, he is asking you to help him complete few tasks with all yours experience to learn your thinking process. Complete those task with the best of your abilities, abstractly analyse each task and figure out what the student is trying to learn from you and ace it.
    """
    baasha_pipeline_config.set("global_chatbot_ctx", global_ctx)

    logger.info(baasha_pipeline_config.get())


def extract_and_upload_last_frame(video_url):
    import subprocess
    import requests
    import os
    from uuid import uuid4

    if (
        not video_url
        or not isinstance(video_url, str)
        or not video_url.startswith("http")
    ):
        return None

    logging.info(f"Extracting last frame from video URL: {video_url}")
    temp_dir = os.path.join(os.path.dirname(__file__), "tmp")
    os.makedirs(temp_dir, exist_ok=True)

    local_video_path = os.path.join(temp_dir, f"temp_{uuid4()}.mp4")
    extracted_image_path = os.path.join(temp_dir, f"last_frame_{uuid4()}.png")

    try:
        r = requests.get(video_url, timeout=30)
        if r.status_code != 200:
            logging.error(
                f"Failed to download video from {video_url}: status {r.status_code}"
            )
            return None
        with open(local_video_path, "wb") as f:
            f.write(r.content)

        cmd = [
            "ffmpeg",
            "-y",
            "-sseof",
            "-0.1",
            "-i",
            local_video_path,
            "-update",
            "1",
            "-q:v",
            "2",
            "-vframes",
            "1",
            extracted_image_path,
        ]

        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

        if not os.path.exists(extracted_image_path):
            logging.error(
                f"Failed to extract frame: {extracted_image_path} does not exist."
            )
            return None

        public_url = upload_image(extracted_image_path)
        logging.info(f"Successfully extracted and uploaded last frame: {public_url}")
        return public_url

    except Exception as e:
        logging.error(f"Error during last frame extraction: {e}")
        return None
    finally:
        if os.path.exists(local_video_path):
            try:
                os.remove(local_video_path)
            except Exception:
                pass
        if os.path.exists(extracted_image_path):
            try:
                os.remove(extracted_image_path)
            except Exception:
                pass


subject_outline_prompt = "Precisely and smoothly trace the outer edge of the primary subject in the foreground with a solid, opaque, uniform 3-pixel wide line in hex #b4b400. This yellow outline must be a perfectly continuous, unbroken closed loop with no jitter, aliasing, or variations in thickness, following every curve of the subject's body and clothing perfectly. The line should be flush against the subject with zero padding. The background should be completely desaturated to grayscale, while the subject remains in full realistic color. This yellow outline must be the only instance of #b4b400 in the frame. Ensure the subject is a sharp, fully rendered, realistic person. Do not include any rectangular frames, vignettes, or borders at the outermost edges of the image."


# Resource for /idea endpoint
class IdeaResource(Resource):
    @staticmethod
    @with_app_context
    def get(idea_id=None):
        user_id = request.args.get("user_id")
        if idea_id:
            idea = Idea.query.get(idea_id)
            if idea is None:
                return {"error": "Idea not found"}, 404
            return {
                "id": idea.id,
                "prompt": idea.prompt,
                "length": idea.length,
                "user_id": idea.user_id,
                "is_series": idea.is_series,
                "episode_breakdown": idea.episode_breakdown,
            }
        elif user_id:
            user_ideas = Idea.query.filter_by(user_id=user_id)
            response = []
            for ui in user_ideas:
                response.append(
                    {
                        "id": ui.id,
                        "prompt": ui.prompt,
                        "length": ui.length,
                        "user_id": ui.user_id,
                        "is_series": ui.is_series,
                        "episode_breakdown": ui.episode_breakdown,
                    }
                )
            return response, 200
        else:
            return {
                "error": "An idea_id in the request path or a user_id as a query param must be specified to fetch an Idea"
            }, 400

    @staticmethod
    @with_app_context
    def post():
        args = idea_parser.parse_args()
        prompt = args["prompt"]
        length = args["length"]
        user_id = args["user_id"]
        is_series = args.get("is_series", False)
        episode_breakdown = args.get("episode_breakdown")

        if not prompt or not length:
            abort(400, message="Both prompt and length are required")
        idea_id = str(uuid.uuid4())
        new_idea = Idea(
            idea_id=idea_id,
            prompt=prompt,
            length=length,
            user_id=user_id,
            is_series=is_series,
            episode_breakdown=episode_breakdown,
        )
        db.session.add(new_idea)
        db.session.commit()
        db.session.flush()

        return {"message": "Idea created successfully", "id": idea_id}, 201

    @staticmethod
    @with_app_context
    def delete(idea_id):
        idea = Idea.query.get(idea_id)
        if idea is None:
            abort(404, message="Idea not found")
        db.session.delete(idea)
        db.session.commit()
        db.session.flush()
        return None, 204


# Resource for /draft/{idea-id} endpoint
class DraftResource(Resource):
    @staticmethod
    @with_app_context
    def get(idea_id, version_id=None):
        if not version_id:
            version_id = 1
        draft = Draft.query.get((idea_id, version_id))
        if draft is None:
            return {"error": "Draft not found"}, 404
        return as_dict(draft)

    @staticmethod
    @with_app_context
    def get_draft(idea_id, version_id):
        if version_id is None:
            draft = (
                Draft.query.filter_by(idea_id=idea_id)
                .order_by(desc(Draft.version))
                .first()
            )
        else:
            draft = Draft.query.get((idea_id, version_id))
        if draft is None:
            if version_id is None:
                abort(404, message="No drafts found for idea {}".format(idea_id))
            abort(
                404,
                message="Draft version {} for idea {} not found".format(
                    version_id, idea_id
                ),
            )
        return draft

    @staticmethod
    def draft_update_callback(db_session, draft, asset_type):
        def live_patch(idx, value):
            if asset_type == "images":
                video_data = json.loads(draft.video_data) if draft.video_data else {}
                video_data["images"][idx] = value

                draft.video_data = json.dumps(video_data)

                db_session.commit()

            # TODO

        return live_patch

    @staticmethod
    @with_app_context
    def post():
        args = draft_parser.parse_args()

        if not args.idea_id:
            abort(404, message="idea_id not found")

        lock_key = f"lock:{args.idea_id}"
        if valkey_client.get(lock_key):
            return {
                "error": f"Project {args.idea_id} is currently locked by another process."
            }, 423
        valkey_client.setex(lock_key, 900, "processing")

        idea = Idea.query.get(args.idea_id)
        if not idea:
            # Auto-create the Idea on the fly if it does not exist to support clean testing
            idea = Idea(
                idea_id=args.idea_id,
                user_id="unregistered",
                prompt="Storyboarding",
                length=200,
                is_series=False,
            )
            db.session.add(idea)
            db.session.commit()
            logging.info(f"Auto-created missing Idea record: {args.idea_id}")

        if args.voice_id:
            voice = Voice.query.get(args.voice_id)
            if not voice:
                abort(404, message="voice_id not found")

        try:
            # intialize_conversation(chatbot)
            chatbot = BaashaChat.ChatInterface()
            chatbot.new_conversation()

        except Exception as e:
            logger.info(e)
            raise Exception(f"Error while creating chatbot instance, {e}")

        try:
            version = args.version_id
            action = "updated"

            if not version:
                last_draft = (
                    Draft.query.filter_by(idea_id=args.idea_id)
                    .order_by(desc(Draft.version))
                    .first()
                )
                version = last_draft.version + 1 if last_draft else 1

            draft = (
                Draft.query.filter_by(idea_id=args.idea_id)
                .filter_by(version=version)
                .first()
            )

            if not draft:
                new_draft = Draft(
                    args.idea_id,
                    version,
                    story="",
                    title="",
                    image_descriptions=args.get("image_descriptors"),
                    background_music_id=args.get("background_music_id"),
                    voice_id=args.get("voice_id"),
                    episode_index=args.get("episode_index"),
                    style_reference_urls=args.get("style_reference_urls"),
                )

                db.session.add(new_draft)
                db.session.commit()
                action = "created"

            background_process = multiprocessing.Process(
                target=DraftResource.draft_processing_task,
                args=(
                    args,
                    idea.prompt,
                    idea.length,
                    version,
                    chatbot,
                    app.config["SQLALCHEMY_DATABASE_URI"],
                ),
            )
            background_process.start()

            return {
                "message": "Draft version {} for idea {} {} successfully".format(
                    version, args.idea_id, action
                ),
                "id": "{}.{}".format(args.idea_id, version),
                "target_stage": args.get("stop_at_stage") or 0,
            }, 201
        except IntegrityError as ie:
            logger.error(ie)
            abort(
                400,
                message="Draft for idea {} could not be recorded, idea does not exist".format(
                    args.idea_id
                ),
            )

        except Exception as e:
            logger.error("Error processing draft ::", e)
            abort(400, message=f"Error : {e}")

        finally:
            db.session.flush()

    @staticmethod
    @with_app_context
    def patch():
        # TODO :
        # Save to DB
        # Allow more edits
        try:
            args = draft_parser.parse_args()
            lock_key = f"lock:{args.idea_id}"
            if valkey_client.get(lock_key):
                return {
                    "error": f"Project {args.idea_id} is currently locked by another process."
                }, 423
            valkey_client.setex(lock_key, 900, "processing")

            draft = Draft.query.get((args.idea_id, args.version_id))

            if not args.edit_inplace:
                last_draft = (
                    Draft.query.filter_by(idea_id=args.idea_id)
                    .order_by(desc(Draft.version))
                    .first()
                )

                try:
                    db.session.expunge(draft)
                except Exception:
                    logging.warn("expunge failed")

                make_transient(draft)

                draft.version = last_draft.version + 1
                draft.remotion_config = None
                draft.generated_video = None

                db.session.add(draft)

            # Put the draft continuously back to "processing" stage (-1) before launching patch task
            old_stage = draft.stage
            draft.stage = -1
            db.session.commit()

            patch_process = multiprocessing.Process(
                target=DraftResource.patch_task,
                args=(
                    args.idea_id,
                    draft.version,
                    old_stage,
                    args,
                    app.config["SQLALCHEMY_DATABASE_URI"],
                ),
            )
            patch_process.start()

            return {"version": draft.version, "target_stage": old_stage}
        except Exception as e:
            logger.error(f"Error during draft patch :: {e}")
            return abort(400, description="something went wrong")

    @staticmethod
    @with_app_context
    def patch_task(idea_id, version, old_stage, args: RequestParser, db_uri: str):
        log_dir = os.path.join(local_cache, "logs")
        os.makedirs(log_dir, exist_ok=True)
        log_file_path = os.path.join(log_dir, f"{idea_id}_{version}.log")

        file_handler = logging.FileHandler(log_file_path, mode="w", encoding="utf-8")
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        )
        file_handler.setLevel(logging.INFO)

        root_logger = logging.getLogger()
        root_logger.addHandler(file_handler)

        db_session = create_new_db_session(db_uri)

        try:
            draft = db_session.query(Draft).get((idea_id, version))

            has_patches = False
            patch_log = lambda x: logging.info(f"patch task - {x}")

            story = draft.story
            video_data = json.loads(draft.video_data)
            story_sentences = video_data["text"]
            content_type = video_data.get("content_type", "reel")

            if content_type == "conversation":
                story_sentences = list(map(lambda x: x["text"], story_sentences))
                story = "\n".join(story_sentences)

            image_engine = args.image_engine or video_data.get(
                "image_engine", "gemini_nano_banana"
            )
            new_voice_id = args.voice_id or video_data.get("voice_id", draft.voice_id)

            narrator_avatar_changed = None
            narrator_url_provided = False

            image_descriptors = draft.image_descriptions or []
            if len(image_descriptors) < len(story_sentences):
                for s in story_sentences[len(image_descriptors) :]:
                    image_descriptors.append((s, None))

                draft.image_descriptions = image_descriptors.copy()

            img_width, img_height = None, None
            try:
                dims = ui_configs.configs[args.gen_video_conf or "v4"].get_asset_sizes()
                (img_width, img_height) = dims.get("images")
            except Exception as e:
                pass

            global_style_desc = video_data.get("style_description")
            if global_style_desc:
                global_image_styles = to_style_data({"themes": [global_style_desc]})
            else:
                global_style_details = (
                    db_session.query(Styles).get(draft.style_id)
                    if draft.style_id
                    else None
                )
                global_image_styles = (
                    to_style_data({"themes": [global_style_details.style_name]})
                    if global_style_details
                    else to_style_data(getattr(args, "image_styles", None))
                ) or None

            image_config = {
                "name": image_engine,
                "width": img_width,
                "height": img_height,
                "resolution": config["PREFS"]["IMAGE_RESOLUTION"],
            }

            chatbot = BaashaChat.ChatInterface()
            chatbot.new_conversation()

            if video_data.get("story_context"):
                chatbot.set_global_ctx(video_data.get("story_context"))

            if args.self_heal:

                image_gen_errors = video_data.get("image_gen_errors", {})
                image_gen_patch_errors = video_data.get("image_gen_patch_errors", {})

                keys = list(
                    set(
                        list(image_gen_errors.keys())
                        + list(image_gen_patch_errors.keys())
                    )
                )

                for k in keys:
                    v1 = image_gen_errors.get(k)
                    v2 = image_gen_patch_errors.get(k)
                    if (v1 and v2 != False) or v2:
                        if not args.regen_images:
                            args.regen_images = []

                        if (int(k) + 1) not in args.regen_images:
                            args.regen_images.append(int(k) + 1)

                video_data["image_gen_errors"] = {}
                video_data["image_gen_patch_errors"] = {}

            if args.story and content_type != "conversation":
                has_patches = True
                patch_log("story")

                draft.story = args.story

                character_list = json.loads(draft.character_ref or "[]")
                character_names = [
                    c.get("name")
                    for c in character_list
                    if c.get("name")
                    and c.get("name") != "narrator_avatar"
                    and "grid" not in c.get("name")
                ]

                (
                    story,
                    text_styling,
                    search_images,
                    gen_images,
                    cinematic_data,
                ) = split_text_into_sentences_with_styling(
                    chatbot,
                    args.story,
                    content_type,
                    image_styles=global_image_styles,
                    character_names=character_names if character_names else None,
                    style_refs=draft.style_reference_urls,
                )

                video_data["text"] = story
                video_data["text_styling"] = text_styling
                video_data["search_image_queries"] = search_images
                video_data["cinematic"] = cinematic_data

                args.story = " ".join(story)

                if old_stage >= DraftStages.AUDIO_GEN_VIDEO_CONFIG_GEN:
                    args.gen_audio = list(range(len(story)))
            else:
                story = video_data["text"]

            if args.image_urls:
                video_data["images"] = args.image_urls

            if args.bgm_name:
                has_patches = True
                patch_log("change bgm")
                new_bgm = baasha_utils.get_bgm_from_name(args.bgm_name)

                if new_bgm:
                    video_data["bgm"] = new_bgm

            if args.style_id:
                patch_log("change style")
                style_details = Styles.query.get(args.style_id)
                draft.style_id = args.style_id
                desps = draft.image_descriptions.copy()
                new_desps = []
                if desps:
                    for d in desps:
                        new_desps.append([d[0] + " " + style_details.style_name, d[1]])
                draft.image_descriptions[:] = new_desps

            if args.add_search_assets:
                patch_log("change search assets")
                has_patches = True
                res = multi_google_search(
                    chatbot,
                    video_data["search_images_queries"],
                    img_width,
                    img_height,
                    local_cache,
                )
                video_data["search_images"] = res

            if args.character_ref:
                patch_log("change character")
                character_ref = draft.character_ref or None

                refs = json.loads(character_ref) if character_ref else []

                base_style_refs = []
                if draft.style_reference_urls:
                    base_style_refs = [
                        {
                            "url": s,
                            "type": "style",
                            "name": "reference for style, aesthetic, color palette, texture only",
                        }
                        for s in draft.style_reference_urls
                    ]

                for k in args.character_ref.keys():
                    idx = None
                    val = args.character_ref[k]

                    if k == "narrator_avatar":
                        narrator_avatar_changed = val
                        narrator_url_provided = False
                        continue

                    elif k == "narrator_avatar_url":
                        narrator_avatar_changed = val
                        narrator_url_provided = True
                        continue

                    for i, r in enumerate(refs):
                        if r["name"] == k:
                            idx = i
                            break

                    existing_url = refs[idx].get("url") if idx is not None else None

                    if val and not val.startswith("http"):
                        if val.startswith("search:"):
                            query = val.split("search:", 1)[1].strip()
                            patch_log(f"Searching web for character image: {query}")
                            res = multi_google_search(
                                chatbot, [query], img_width, img_height, local_cache
                            )
                            if res and res[0]:
                                val = res[0]
                                if idx is not None:
                                    refs[idx]["description"] = query
                            else:
                                patch_log("search failed")
                                continue
                        elif val.startswith("edit:"):
                            edit_instruction = val.split("edit:", 1)[1].strip()
                            patch_log(
                                f"Editing existing character {k} with: {edit_instruction}"
                            )
                            if existing_url:
                                style_desc = video_data.get("style_description")
                                style_prompt = (
                                    f" Maintain the visual aesthetic defined by: {style_desc}"
                                    if style_desc
                                    else ""
                                )
                                upscale = (
                                    f"HIGH FIDELITY CHARACTER EDIT.\n"
                                    f"Apply the following edit to the subject: {edit_instruction}\n"
                                    f"{style_prompt}\n"
                                    f"INSTRUCTIONS:\n"
                                    f"Retain the exact identity, facial structure, and core appearance of the provided character reference, but apply the requested changes."
                                )
                                ref_urls = [
                                    [
                                        {
                                            "url": existing_url,
                                            "type": "subject",
                                            "name": k,
                                        }
                                    ]
                                    + base_style_refs
                                ]
                                urls, _, _, _, _ = image_gen(
                                    [upscale],
                                    ref_urls,
                                    local_cache,
                                    image_config,
                                    chatbot,
                                )
                                if urls and urls[0]:
                                    val = urls[0]
                                    if idx is not None:
                                        refs[idx]["description"] = (
                                            refs[idx].get("description", "")
                                            + f" (Edit: {edit_instruction})"
                                        )
                                else:
                                    patch_log(f"Failed to edit character image for {k}")
                                    continue
                            else:
                                patch_log(
                                    f"Cannot edit character {k} as no existing image was found."
                                )
                                continue
                        else:
                            patch_log(
                                f"Generating new character image for {k} from prompt: {val}"
                            )
                            style_desc = video_data.get("style_description")
                            style_prompt = (
                                f" Maintain the visual aesthetic defined by: {style_desc}"
                                if style_desc
                                else ""
                            )
                            upscale = (
                                f"HIGH FIDELITY CHARACTER GENERATION.\n"
                                f"Subject Description: {val}\n"
                                f"{style_prompt}\n"
                                f"INSTRUCTIONS:\n"
                                f"Output a clean, high-quality, single-subject full frame portrait."
                            )
                            ref_urls = [base_style_refs] if base_style_refs else [[]]
                            urls, _, _, _, _ = image_gen(
                                [upscale], ref_urls, local_cache, image_config, chatbot
                            )
                            if urls and urls[0]:
                                val = urls[0]
                                if idx is not None:
                                    refs[idx]["description"] = val
                            else:
                                patch_log(f"Failed to generate character image for {k}")
                                continue

                    if idx != None:
                        refs[idx]["url"] = val
                    else:
                        refs.append(
                            {
                                "name": k,
                                "url": val,
                                "type": "character",
                                "description": val,
                            }
                        )

                draft.character_ref = json.dumps(refs)

            regen_img_pos = []

            if args.regen_image_prompts and args.regen_images:
                patch_log("regen image prompts")
                draft.stage = DraftStages.IMAGE_PROMPT_GEN
                db.session.commit()

                character_names = (
                    []
                    if not draft.character_ref
                    else list(
                        map(lambda x: x.get("name"), json.loads(draft.character_ref))
                    )
                )

                old_prompts = draft.image_descriptions
                if len(old_prompts) < len(story):
                    for i, s in enumerate(story):
                        if i >= len(old_prompts):
                            old_prompts.append((s, None))

                    draft.image_descriptions = old_prompts.copy()

                sentences = []
                new_prompts: List[Optional[List[str]]] = [None] * len(args.regen_images)
                regen_prompts_pos = []
                is_grid = "story-grid-0" in character_names

                for i, pos in enumerate(args.regen_images):
                    if is_grid:
                        new_prompts[i] = old_prompts[pos - 1]
                    elif (
                        len(args.regen_image_prompts) > i
                        and args.regen_image_prompts[i]
                    ):
                        new_prompts[i] = [
                            args.regen_image_prompts[i],
                            old_prompts[pos - 1][1],
                        ]

                    elif (pos - 1) < len(list(story)):
                        regen_prompts_pos.append(i)
                        sentences.append(list(story)[pos - 1])

                if len(sentences) > 0:

                    regenerated_prompts = generate_image_prompts(
                        "ner",
                        chatbot,
                        sentences,
                        scene_count=len(sentences),
                        characters=character_names,
                        image_styles=global_image_styles,
                        image_config=image_config,
                        callback=None,
                    )

                    for r, i in zip(regenerated_prompts, regen_prompts_pos):
                        new_prompts[i] = r

                image_regens = args.regen_images or []
                desps = draft.image_descriptions.copy()
                for i, pos in enumerate(image_regens):
                    if (pos - 1) < len(story):
                        promptz = new_prompts[i]
                        if promptz is not None:
                            desps[pos - 1] = tuple(promptz)

                if len(new_prompts) > 0:
                    # patch only unique indexes
                    draft.image_descriptions = desps
                    args.regen_images = list(set(image_regens))

                image_descriptors = draft.image_descriptions.copy()

            if args.regen_images:
                if old_stage >= DraftStages.IMAGE_GEN:
                    has_patches = True
                    patch_log("regen images")
                    regen_img_pos = args.regen_images

            images = video_data.get("images", [])

            patched_img = [None] * len(images)
            re_gen_idx = []
            for (i, m) in enumerate(images):
                if (i + 1) in list(regen_img_pos):
                    re_gen_idx.append(i)
                    continue
                patched_img[i] = m

            if len(re_gen_idx) > 0:
                image_descriptors = draft.image_descriptions or []
                if len(image_descriptors) < len(story):
                    for i, s in enumerate(story):
                        if i >= len(image_descriptors):
                            image_descriptors.append((s, None))

                    draft.image_descriptions = image_descriptors.copy()

                character_list = (
                    json.loads(draft.character_ref)
                    if draft.character_ref != None
                    else []
                )
                user_characters: Dict[str, str] = {}
                re_gen_prompts = list(map(lambda i: image_descriptors[i], re_gen_idx))

                out_dir = "{}.{}".format(draft.idea_id, draft.version)

                prompts, ref_urls = get_prompt_character_ref_urls(
                    chatbot,
                    re_gen_prompts,
                    user_characters,
                    character_list,
                    image_engine,
                    global_image_styles,
                    out_dir,
                )

                if args.style_reference_urls:
                    style_refs = [
                        {"url": s, "type": "style"} for s in args.style_reference_urls
                    ]
                    ref_urls = list(
                        map(
                            lambda x: style_refs + [{"type": "character", "url": x}],
                            ref_urls,
                        )
                    )
                    nudge = " Heavily apply the specific lighting, texture, and aesthetic vibe from the Style Reference to the character reference. NEVER replicate the grid layout of the Style Reference."
                    prompts = [p + nudge for p in prompts]

                width = None
                height = None

                try:
                    dims = ui_configs.configs[
                        args.gen_video_conf or "v4"
                    ].get_asset_sizes()
                    (width, height) = dims.get("images")
                except Exception as e:
                    pass

                if video_data.get("use_image_grid"):
                    patch_log("Using image grid logic for patch regeneration")
                    grid_image_config = {
                        "name": image_engine,
                        "width": width,
                        "height": height,
                        "aspect_ratio": "1:1",
                    }
                    chatbot_bbox = BaashaChat.ChatInterface()
                    chatbot_bbox.new_conversation()

                    char_refs_for_grid = []
                    for char in character_list:
                        if (
                            char.get("url")
                            and char.get("type") != "scene"
                            and not char.get("name", "").startswith("story-grid-")
                        ):
                            char_refs_for_grid.append(
                                {
                                    "url": char["url"],
                                    "type": "character",
                                    "name": f"use the exact face for the character named {char['name']} across the scenes",
                                }
                            )

                    style_refs_for_grid = []
                    style_str = (
                        (" Target Visual Style: " + global_image_styles.to_text())
                        if global_image_styles
                        else ""
                    )
                    if draft.style_reference_urls:
                        style_refs_for_grid = [
                            {
                                "url": s,
                                "type": "style",
                                "name": f"reference for style, aesthetic, color palette, texture only.{style_str}",
                            }
                            for s in draft.style_reference_urls
                        ]
                    if args.style_reference_urls:
                        style_refs_for_grid.extend(
                            [
                                {
                                    "url": s,
                                    "type": "style",
                                    "name": "reference for style, aesthetic, color palette, texture only",
                                }
                                for s in args.style_reference_urls
                            ]
                        )

                    regen_images = []
                    logs = []
                    errors = []

                    for i, idx in enumerate(re_gen_idx):
                        chunk_prompts = [prompts[i]]
                        current_style_refs = list(style_refs_for_grid)

                        previous_grid_url = None
                        for char in character_list:
                            if char.get("name", "").startswith("story-grid-"):
                                rng = char.get("range")
                                if rng and len(rng) == 2:
                                    if rng[1] == idx or (rng[0] <= idx < rng[1]):
                                        previous_grid_url = char.get("url")
                                        if rng[1] == idx:
                                            break

                        if previous_grid_url:
                            grid_desp = f"previous shot of scene {idx}"
                            current_style_refs.append(
                                {
                                    "url": previous_grid_url,
                                    "type": "scene",
                                    "name": grid_desp
                                    + " pay extra attention to characters, costumes, positions, location, styling to create next scene",
                                }
                            )

                        grid_guidance = " create a single frame only"

                        res, err = create_image_grid(
                            chunk_prompts,
                            grid_image_config,
                            chatbot_bbox,
                            local_cache,
                            grid_guidance=grid_guidance,
                            character_refs=char_refs_for_grid,
                            style_refs=current_style_refs,
                            image_styles=global_image_styles,
                            refine_grid_count=0,
                            story_context=draft.story,
                            prompt_overrides=None,
                        )

                        if res:
                            story_grid, grid_imgs, other_grids, grid_prompt = res
                            if grid_imgs and len(grid_imgs) > 0:
                                regen_images.append(grid_imgs[0])
                            elif story_grid:
                                regen_images.append(story_grid)
                            else:
                                regen_images.append(None)
                            logs.append(grid_prompt)
                        else:
                            regen_images.append(None)
                        if err:
                            errors.extend(err if isinstance(err, list) else [err])

                    regen_prompts = [prompts[i] for i in range(len(re_gen_idx))]

                    if video_data.get("upscale_grid_crops", True):
                        enhance_prompt = (
                            f"HIGH FIDELITY NATIVE 9:16 SCENE EXPANSION. "
                            f"Gracefully expand the scene into a native 9:16 aspect ratio. "
                            f"Ensure the generated image perfectly inherits the exact visual medium, art style, "
                            f"texture, detail level, color palette, and lighting of the provided reference crop. "
                            f"DO NOT add digital over-sharpening, high contrast overrides, artificial specular highlights, "
                            f"or synthetic textures that are not present in the crop. "
                            f"Preserve the original atmospheric mood and organic rendering quality of the reference crop completely."
                        )
                        upscale_prompts = [enhance_prompt] * len(regen_images)
                        upscale_ref_urls = [
                            [{"url": img, "type": "subject", "name": f"crop-{i}"}]
                            + style_refs_for_grid
                            for i, img in enumerate(regen_images)
                            if img
                        ]

                        if upscale_ref_urls:
                            chatbot_bbox.new_conversation()
                            upscaled_images, _, _, _, _ = image_gen(
                                upscale_prompts,
                                upscale_ref_urls,
                                out_dir,
                                {
                                    "name": image_engine,
                                    "width": width,
                                    "height": height,
                                },
                                chatbot_bbox,
                            )
                            patch_original_crops = list(regen_images)
                            for i, img in enumerate(upscaled_images):
                                if img:
                                    regen_images[i] = img

                    image_engine_map = {}
                else:
                    (
                        regen_images,
                        regen_prompts,
                        image_engine_map,
                        errors,
                        logs,
                    ) = image_gen(
                        prompts,
                        ref_urls,
                        out_dir,
                        {"name": image_engine, "width": width, "height": height},
                        chatbot,
                    )

                video_data["image_gen_patch_logs"] = logs
                error_map = {}

                image_descriptors = image_descriptors.copy()
                grid_crops = video_data.get("grid_crops", patched_img.copy())
                upscaled_images_arr = video_data.get(
                    "upscaled_images", patched_img.copy()
                )

                for (idx1, idx2) in enumerate(re_gen_idx):
                    if regen_images[idx1]:
                        patched_img[idx2] = regen_images[idx1]
                        image_descriptors[idx2] = regen_prompts[idx1]

                        if "patch_original_crops" in locals():
                            if idx2 < len(grid_crops):
                                grid_crops[idx2] = patch_original_crops[idx1]
                            if idx2 < len(upscaled_images_arr):
                                upscaled_images_arr[idx2] = regen_images[idx1]
                    else:
                        error_map[str(idx2)] = "new image is null"

                    if errors:
                        error_map[str(idx2)] = errors[idx1]

                video_data["image_gen_patch_errors"] = error_map

                draft.character_ref = json.dumps(character_list)
                old_image_engine_map = video_data.get("image_engine_map", {}) or {}
                old_image_engine_map.update(image_engine_map)
                video_data["image_engine_map"] = old_image_engine_map

                video_data["images"] = patched_img
                if "patch_original_crops" in locals():
                    video_data["grid_crops"] = grid_crops
                    video_data["upscaled_images"] = upscaled_images_arr
                focus_directions = image_search_agent.find_image_focus_direction(
                    patched_img, chatbot
                )
                video_data["image_focus_directions"] = focus_directions

            if args.judge_grids:
                if old_stage >= DraftStages.IMAGE_GEN:
                    patch_log("fixing image grids using LLM judge")
                has_patches = True
                raw_ch_refs = draft.character_ref or ""
                if raw_ch_refs:
                    character_ref = json.loads(raw_ch_refs)

                    grids = list(
                        filter(
                            lambda x: x["name"].startswith("story-grid"), character_ref
                        )
                    )

                    char_refs_for_grid = []
                    # for char in character_ref:
                    #     if (
                    #         char.get("url")
                    #         and char.get("type") != "scene"
                    #         and not char.get("name", "").startswith("story-grid-")
                    #     ):
                    #         char_refs_for_grid.append(
                    #             {
                    #                 "url": char["url"],
                    #                 "type": "character",
                    #                 "name": f"use the exact face for the character named {char['name']} across the scenes",
                    #             }
                    #         )

                    desps = []
                    prev_grids: list[Any] = []
                    grid_updates = {}
                    chunk_size = 4
                    start = 0

                    grid_config = image_config.copy()
                    grid_config["aspect_ratio"] = "1:1"

                    style_refs_for_judge = []
                    if draft.style_reference_urls:
                        style_str = (
                            (" Target Visual Style: " + global_image_styles.to_text())
                            if global_image_styles
                            else ""
                        )
                        style_refs_for_judge = [
                            {
                                "url": s,
                                "type": "style",
                                "name": f"reference for style, aesthetic, color palette, texture only.{style_str}",
                            }
                            for s in draft.style_reference_urls
                        ]

                    for g in grids:
                        prompt_guidance = None
                        if start + chunk_size <= len(draft.image_descriptions):
                            panel_prompts = draft.image_descriptions[
                                start : start + chunk_size
                            ]
                            desps = [
                                f"Scene {start + i + 1}: {x[0]}"
                                for i, x in enumerate(panel_prompts)
                            ]
                            chunk_label = (
                                f"Scenes from {start + 1} to {start + chunk_size}"
                            )
                            start += chunk_size
                            prompt_guidance = "Arrange the image as a strict 2x2 grid where each of the four panels is a vertically-oriented 9:16 frame, separated by thin black border"
                        else:
                            panel_prompts = draft.image_descriptions[start : start + 1]
                            desps = [
                                f"Scene {start + i + 1}: {x[0]}"
                                for i, x in enumerate(panel_prompts)
                            ]
                            chunk_label = f"Scene {start + 1}"
                            start += 1
                            prompt_guidance = "create a single frame only"

                        grid_url, _ = refine_and_fix_grid(
                            chatbot,
                            g["url"],
                            style_refs_for_judge + prev_grids,
                            draft.story,
                            desps,
                            [],  # char_refs_for_grid skipped for now
                            grid_config,
                            prompt_guidance,
                            local_cache,
                        )

                        prev_grids.append(
                            {
                                "url": grid_url,
                                "type": "scene",
                                "name": "scene descriptions: " + chunk_label,
                            }
                        )
                        grid_updates[g["name"]] = grid_url

                    if len(grid_updates.keys()) > 0:
                        for idx, g in enumerate(character_ref):
                            if grid_updates.get(g["name"]):
                                character_ref[idx]["url"] = grid_updates[g["name"]]

                        draft.character_ref = json.dumps(character_ref)

            if args.judge_images:
                if old_stage >= DraftStages.IMAGE_GEN:
                    patch_log("fixing images using LLM judge")
                    has_patches = True
                    context = build_script_context(chatbot, draft.story)
                    character_ref = draft.character_ref or ""

                    refined_urls, judge_results = judge_and_fix_images(
                        chatbot,
                        video_data.get("images", []),
                        list(map(lambda x: x[0], draft.image_descriptions)),
                        context=context,
                        character_details=character_ref,
                    )

                    video_data["image_gen_fix_results"] = judge_results
                    video_data["images"] = refined_urls

            if args.make_image_layers:
                if old_stage >= DraftStages.IMAGE_GEN:
                    has_patches = True
                    layers = list(
                        map(
                            lambda x: create_image_layer(
                                chatbot,
                                local_cache,
                                x,
                                image_config.get("aspect_ratio", "16:9"),
                            ),
                            video_data.get("images", []),
                        )
                    )
                    video_data["image_layers"] = layers

            if args.upscale_image:
                if old_stage >= DraftStages.IMAGE_GEN:
                    has_patches = True
                    patch_log("upscale images")
                    draft.stage = DraftStages.IMAGE_PROMPT_GEN
                    db.session.commit()
                    upscaled = fetch_and_upscale_images(
                        args.idea_id, args.version_id, video_data.get("images", [])
                    )
                    logger.info(f"Upscaled images : {upscaled}")

                    video_data["images"] = upscaled

            if args.convert_to_video:
                if old_stage >= DraftStages.IMAGE_GEN:
                    has_patches = True
                    patch_log("convert to video")

                engine = args.video_engine or "goapi_wanx"
                img_len = len(video_data.get("images", []))
                audio_len = len(video_data["audios"])

                total_gen = img_len
                if engine.startswith("stock_videos"):
                    # in case images are repeated
                    total_gen = audio_len

                selected_images, selected_desp, selected_pos, force_regen = (
                    [],
                    [],
                    [],
                    [],
                )
                result = {}
                output: List[Any] = []
                image_unified_style = video_data.get("style_description")

                for obj in args.convert_to_video:
                    cinematic_data = video_data.get("cinematic")
                    audios = video_data["text"]

                    if obj.get("pos") and obj.get("url") and obj["pos"] <= total_gen:
                        url = obj["url"]
                        result[str(obj["pos"])] = url

                    elif obj.get("pos") and obj["pos"] <= total_gen:

                        # use index as key
                        u = str(obj["pos"])

                        if img_len >= obj["pos"]:
                            # use url as key
                            u = video_data.get("images", [])[(obj["pos"] - 1)]

                        selected_images.append(u)

                        if obj.get("prompt"):
                            selected_desp.append(obj["prompt"])
                            selected_pos.append(obj["pos"] - 1)
                            force_regen.append(obj.get("regen"))

                        elif cinematic_data and len(cinematic_data) >= obj["pos"]:
                            c = cinematic_data[obj["pos"] - 1]
                            prompt_text = c.get("motion_prompt")

                            if not prompt_text:
                                prompt_text = (
                                    "The camera maintains a slow, steady, and visually stable dolly-in movement to enhance depth. "
                                    "Ensure absolute anatomical integrity. The background environment and room geometry remain "
                                    "completely static and locked in place. Do not animate any mouth or lip movement."
                                )

                            if (
                                image_unified_style
                                and image_unified_style not in prompt_text
                            ):
                                prompt_text = (
                                    prompt_text + " aesthetic: " + image_unified_style
                                )

                            selected_desp.append(prompt_text)
                            selected_pos.append(obj["pos"] - 1)
                            force_regen.append(obj.get("regen"))
                        else:
                            speech_text = video_data["text"][obj["pos"] - 1]
                            prompt_text = (
                                f"The camera maintains a slow, steady, and visually stable dolly-in movement to enhance depth, "
                                f"matching the emotional tone of the scene: '{speech_text}'. Ensure absolute anatomical integrity. "
                                f"The background environment and room geometry remain completely static and locked in place. "
                                f"Do not animate any mouth or lip movement."
                            )
                            if image_unified_style:
                                prompt_text = (
                                    prompt_text + " aesthetic: " + image_unified_style
                                )

                            selected_desp.append(prompt_text)
                            selected_pos.append(obj["pos"] - 1)
                            force_regen.append(obj.get("regen"))

                try:
                    if len(selected_images) < 1:
                        raise Exception("no images selected for video gen")

                    logging.info(
                        f"image to video descriptions : {selected_desp}, {selected_pos}"
                    )

                    if engine.startswith("start_end_framing"):
                        images = video_data.get("images", [])
                        existing_videos = video_data.get("image_to_videos", [])

                        selected_images = []
                        output = []
                        desp_idx = 0
                        audio_len = len(video_data["audios"])
                        for idx, a in enumerate(video_data["audios"]):

                            if idx not in selected_pos:
                                logging.info(f"skipping video gen for idx - {idx}")
                                continue

                            img_ref = images[idx] if idx < len(images) else None
                            if not img_ref:
                                continue

                            if (
                                not force_regen[desp_idx]
                                and existing_videos
                                and existing_videos.get(img_ref)
                            ):
                                if isinstance(existing_videos[img_ref], str):
                                    continue

                            c = (
                                cinematic_data[idx]
                                if (cinematic_data and idx < len(cinematic_data))
                                else None
                            )
                            prior_index = (
                                c.get("relative_prior_shot_index") if c else None
                            )

                            if (
                                prior_index
                                and isinstance(prior_index, int)
                                and 1 <= prior_index <= len(images)
                            ):
                                prior_img_ref = images[prior_index - 1]
                                prior_video_url = None

                                # 1. Check if we just generated it in this loop:
                                if (
                                    prior_index - 1 < len(output)
                                    and output[prior_index - 1]
                                ):
                                    prior_video_url = output[prior_index - 1]
                                # 2. Otherwise check existing_videos:
                                elif existing_videos and existing_videos.get(
                                    prior_img_ref
                                ):
                                    val = existing_videos[prior_img_ref]
                                    if isinstance(val, list) and len(val) > 0:
                                        prior_video_url = val[0]
                                    elif isinstance(val, str):
                                        prior_video_url = val

                                last_frame_url = None
                                if prior_video_url:
                                    try:
                                        last_frame_url = extract_and_upload_last_frame(
                                            prior_video_url
                                        )
                                    except Exception as ex:
                                        logging.error(
                                            f"Error calling last frame extractor: {ex}"
                                        )

                                if last_frame_url and verify_subject_continuity(
                                    last_frame_url, img_ref
                                ):
                                    logging.info(
                                        "Vision check PASSED: Subjects match. Using interpolation."
                                    )
                                    start_img_ref = last_frame_url
                                    end_img_ref = img_ref
                                else:
                                    logging.info(
                                        "Vision check FAILED or last frame missing: Subjects mismatch. Falling back to prior image ref."
                                    )
                                    start_img_ref = prior_img_ref
                                    end_img_ref = img_ref
                            else:
                                start_img_ref = img_ref
                                end_img_ref = None

                            video_prompt = selected_desp[desp_idx]
                            desp_idx += 1

                            o, err = fal.generate_video(
                                prompt=video_prompt,
                                ref=start_img_ref,
                                last_ref=end_img_ref,
                                duration_seconds=min(max(4, int(round(a[1]))), 12),
                                aspect_ratio="9:16",
                                resolution="480p",
                                generate_audio=True,
                                model="seedance",
                            )
                            selected_images.append(img_ref)
                            output.append(o if o else None)

                    elif engine.startswith("start_end_collage_framing"):
                        images = video_data["images"]
                        selected_images = []
                        output = []

                        audio_len = len(video_data["audios"])
                        for idx, a in enumerate(video_data["audios"]):
                            img_ref = images[idx] if idx < len(images) else None
                            if not img_ref:
                                continue

                            context = (
                                video_data["text"][idx]
                                if idx < len(video_data["text"])
                                else ""
                            )

                            if idx + 1 < len(images):
                                next_img_ref = images[idx + 1]
                                prompt = f"The attached reference is a wide panorama. The camera must START fully zoomed into the LEFT side so only the left scene is visible. Over the duration of the video, smoothly and naturally PAN THE CAMERA TO THE RIGHT until it stops completely zoomed into the RIGHT side. Make it look like a seamless cinematic tracking shot between these two locations. Do NOT zoom out to show the full image at once. Match the context: '{context}'."

                                import requests
                                from PIL import Image
                                import io

                                img1_res = requests.get(img_ref, timeout=30)
                                img2_res = requests.get(next_img_ref, timeout=30)

                                img1 = Image.open(io.BytesIO(img1_res.content))
                                img2 = Image.open(io.BytesIO(img2_res.content))

                                if img1.height != img2.height:
                                    aspect_ratio = img2.width / img2.height
                                    new_width = int(img1.height * aspect_ratio)
                                    img2 = img2.resize((new_width, img1.height))

                                total_width = img1.width + img2.width
                                max_height = img1.height
                                collage_raw = Image.new(
                                    "RGB", (total_width, max_height)
                                )
                                collage_raw.paste(img1, (0, 0))
                                collage_raw.paste(img2, (img1.width, 0))

                                # Enforce 9:16 aspect ratio for Veo so it doesn't pad with black bars
                                target_width = collage_raw.width
                                target_height = target_width * 16 // 9
                                if collage_raw.height < target_height:
                                    # Pad height
                                    collage = Image.new(
                                        "RGB", (target_width, target_height), (0, 0, 0)
                                    )
                                    collage.paste(
                                        collage_raw,
                                        (0, (target_height - collage_raw.height) // 2),
                                    )
                                elif collage_raw.height > target_height:
                                    # Crop height
                                    top = (collage_raw.height - target_height) // 2
                                    collage = collage_raw.crop(
                                        (0, top, target_width, top + target_height)
                                    )
                                else:
                                    collage = collage_raw

                                output_stream = io.BytesIO()
                                collage.save(output_stream, format="PNG")
                                collage_bytes = output_stream.getvalue()

                                o, err = gemini.generate_video(
                                    prompt,
                                    ref_bytes=collage_bytes,
                                )
                                selected_images.append(img_ref)
                                output.append(o if o else None)
                            else:
                                prompt = f"Subtle, natural cinematic motion matching the emotional tone and environment of the scene: '{context}'. The camera flows smoothly with high visual stability."
                                o, err = gemini.generate_video(prompt, ref=img_ref)
                                selected_images.append(img_ref)
                                output.append(o if o else None)

                    elif engine.startswith("goapi"):
                        output = GoAPI.convert_image_to_videos(
                            engine, selected_images, selected_desp
                        )

                    elif engine.startswith("gooey"):
                        output = GooeyAPI.convert_image_to_videos(
                            engine, selected_images, selected_desp
                        )

                    elif engine.startswith("veo"):
                        output = []
                        for (im, d) in zip(selected_images, selected_desp):
                            o, err = gemini.generate_video(d, ref=im)
                            if o:
                                output.append(o)

                    elif engine.startswith("fal"):
                        output = []
                        for (im, d) in zip(selected_images, selected_desp):
                            o = fal.image_to_video(d, im, upload=True)
                            if o:
                                output.append(o)

                    elif engine.startswith("stock_videos"):
                        output = []
                        blacklist_videos: List[Optional[str]] = list(
                            video_data.get("image_to_videos", {}).values()
                        )
                        orientation = "vertical"
                        if img_width and img_height and img_width > img_height:
                            orientation = "horizontal"

                        for desp in selected_desp:
                            link = mk_scrape_video_link(desp, orientation=orientation)
                            results = scrape_videos_from_link(link, False)

                            vid = (
                                get_similar_video(
                                    desp, data=results, blacklist=blacklist_videos
                                )
                                or {}
                            )

                            if not vid.get("video_link"):
                                continue

                            _, new_vid = store_scraped_vidoes([vid], link)

                            if new_vid[0].get("video_link"):
                                blacklist_videos.append(vid.get("video_link"))
                                blacklist_videos.append(new_vid[0].get("video_link"))
                                blacklist_videos.append(vid.get("desp", ""))

                            output.append(new_vid[0].get("video_link"))

                except Exception as e:
                    logging.error(e)
                    video_data["image_to_video_gen_logs"] = str(e)
                    output = []

                logging.info(f"converted_to_video : {output}")
                if not output:
                    output = []

                if output or len(result) > 0:
                    for i, o in enumerate(output):
                        result[selected_images[i]] = o

                    if not video_data.get("image_to_videos"):
                        video_data["image_to_videos"] = {}

                    video_data["image_to_videos"].update(result)

                    # min video len
                    if engine.startswith("start_end_framing"):
                        try:
                            for idx, img in enumerate(video_data["images"]):
                                if result.get(img):
                                    a = video_data["audios"][idx]
                                    video_data["audios"][idx] = (
                                        a[0],
                                        min(12, max(a[1], 4)),
                                    )
                        except Exception:
                            logging.info("audio min len patch failed")

            draft.video_data = json.dumps(video_data)
            db.session.commit()

            if args.edit_story_sentence or len(args.gen_audio or []) > 0:
                has_patches = True

                if args.edit_story_sentence:
                    patch_log("edit story sentence")
                if len(args.gen_audio or []) > 0:
                    patch_log("regen audio")

                text_len = len(video_data["audios"])
                regen_sentence = video_data["text"]
                sentence_pos = [i for i in range(text_len)]

                if args.edit_story_sentence:
                    for (k, v) in args.edit_story_sentence.items():
                        idx = int(k)
                        if idx < text_len:
                            old_sentence = regen_sentence[idx]
                            regen_sentence[idx] = v

                            # Opiniated Update: Propagate dialogue changes to cinematic motion prompt for accurate lip-syncing
                            cinematic = video_data.get("cinematic", [])
                            if cinematic and idx < len(cinematic):
                                if cinematic[idx].get("audio_type") == "dialogue":
                                    mp = cinematic[idx].get("motion_prompt", "")
                                    old_tag = f", dialogue: {old_sentence}"
                                    new_tag = f", dialogue: {v}"
                                    if old_tag in mp:
                                        cinematic[idx]["motion_prompt"] = mp.replace(
                                            old_tag, new_tag
                                        )
                                    else:
                                        # Fallback if exact match isn't found
                                        cinematic[idx][
                                            "motion_prompt"
                                        ] = f"{mp}{new_tag}"

                if len(regen_sentence) > 0:
                    video_data["text"] = regen_sentence
                    if old_stage >= DraftStages.AUDIO_GEN_VIDEO_CONFIG_GEN:
                        voice_details = db_session.query(Voice).get(new_voice_id)

                        (
                            audios,
                            timepoint_map,
                            is_word_timepoints,
                        ) = baasha_utils.text_to_speech_as_single_audio(
                            text=regen_sentence,
                            voice_key=new_voice_id,
                            tts_toolkit=voice_details.tts_toolkit
                            if voice_details
                            else args.tts_toolkit,
                        )

                        if voice_details:
                            draft.voice_id = new_voice_id

                        if len(audios) > len(video_data.get("audios", [])):
                            video_data["audios"] = audios

                        else:
                            count = 0
                            for sen, pos in zip(regen_sentence, sentence_pos):
                                video_data["text"][pos] = sen
                                if (
                                    "audios" in video_data
                                    and len(video_data["audios"]) > pos
                                ):
                                    video_data["audios"][pos] = audios[count]
                                count += 1

                        if video_data.get("timepoints_map"):
                            video_data["timepoints_map"].update(timepoint_map)
                        else:
                            video_data["timepoints_map"] = timepoint_map

                        video_data["is_word_timepoints"] = is_word_timepoints

            if args.add_phrase_sounds:
                if old_stage >= DraftStages.AUDIO_GEN_VIDEO_CONFIG_GEN:
                    patch_log("regen sound-map")
                    has_patches = True

                embeddings = text_embeddings.embedding_gemini(story, dims=384).tolist()
                sound_list = []
                for idx, embed in enumerate(embeddings or []):
                    res = BackgroundMusicResource.search(
                        transition=True, embedding=embed
                    )
                    for r in res:
                        sound_list.append({"name": r.music_name, "url": r.music_sample})

                sound_map = get_phrase_sound_effects(
                    chatbot,
                    sound_list,
                    video_data["audios"],
                    video_data["timepoints_map"],
                )

                if video_data.get("sound_map"):
                    # this should be update
                    video_data["sound_map"] = sound_map
                else:
                    video_data["sound_map"] = sound_map

            draft.video_data = json.dumps(video_data)
            db_session.commit()

            if narrator_avatar_changed:
                patch_log("change narrator avatar")
                has_patches = True

                if narrator_url_provided:
                    video_file = download_file(
                        narrator_avatar_changed, local_cache, force_ext="mp4"
                    )
                    audio_file = baasha_pipeline_utils.video_to_audio(video_file)
                    video_data["narrator_avatar"] = {
                        "url": narrator_avatar_changed,
                        "url2": None,
                        "has_audio": True,
                        "ref_url": narrator_avatar_changed,
                    }
                    public_audio_url = object_storage.upload_file(
                        object_storage.ASSETS_AUDIO_BUCKET,
                        audio_file,
                        os.path.basename(audio_file),
                        object_storage.ACL_PUBLIC,
                    )
                    args.text_to_speech = public_audio_url
                else:
                    voice_details = db_session.query(Voice).get(new_voice_id)
                    (output, processed_output, has_audio) = narrator_avatar_gen(
                        args.avatar_engine or "replicate_video_retalking",
                        " ".join(video_data["text"]),
                        video_data["audios"][0][0],
                        narrator_avatar_changed,
                        voice_details.tts_toolkit,
                        new_voice_id,
                    )
                    if output:
                        video_data["narrator_avatar"] = {
                            "url": processed_output,
                            "url2": output,
                            "has_audio": has_audio,
                            "ref_image": narrator_avatar_changed,
                        }

            draft.video_data = json.dumps(video_data)
            db_session.commit()

            if args.text_to_speech:
                if old_stage >= DraftStages.AUDIO_GEN_VIDEO_CONFIG_GEN:
                    patch_log("patch audio tts")
                    has_patches = True
                    output_file = download_file(
                        args.text_to_speech, local_cache, force_ext="wav"
                    )
                    if output_file:
                        timepoints = Groq.stt(output_file)
                        if not timepoints:
                            timepoints = VoskToolkit.get_audio_timepoints(output_file)

                        patched_timepoints = (
                            baasha_pipeline_utils.patch_timepoints_words_v2(
                                " ".join(video_data["text"]), timepoints
                            )
                        )

                        audio_splits = []
                        timepoint_map = {}
                        timepoint_map[args.text_to_speech] = patched_timepoints

                        # for i in range(len(video_data["text"])):
                        #    audio_splits.append((str(i), 0))
                        #    timepoint_map[str(i)] = []

                        # audio_splits[0] = (args.text_to_speech, patched_timepoints[-1][2])

                        (audio_splits, timepoint_map) = baasha_utils.make_audio_split(
                            video_data["text"], args.text_to_speech, timepoint_map
                        )

                        video_data["audios"] = audio_splits
                        video_data["timepoints_map"] = timepoint_map
                        video_data["is_word_timepoints"] = True

                    else:
                        logging.info("error while download args.text_to_speech")

            draft.video_data = json.dumps(video_data)
            db_session.commit()

            if args.ui_order:
                has_patches = True
                patch_log("change ui order")
                video_data = baasha_utils.edit_ui_order(video_data, args.ui_order)

            if args.ui_config:
                has_patches = True
                patch_log("update ui config")
                video_data["ui_config"] = args.ui_config

            if args.ai_edit_ui:
                patch_log("ai edit")
                has_patches = True
                edited_config = edit_video_config(video_data, args.ai_edit_ui)

                if video_data:
                    ai_edits = video_data.get("ai_edits")
                    if isinstance(ai_edits, list):
                        ai_edits.append(
                            {
                                "query": args.ai_edit_ui,
                                "edit": edited_config,
                                "enable": True,
                            }
                        )
                    else:
                        video_data["ai_edits"] = [
                            {
                                "query": args.ai_edit_ui,
                                "edit": edited_config,
                                "enable": True,
                            }
                        ]
                else:
                    pass

            if args.toggle_ai_edit:
                patch_log("toggle ai edit")
                has_patches = True
                ai_edits = video_data.get("ai_edits")

                if ai_edits:
                    for i, enable in enumerate(args.toggle_ai_edit):
                        if i < len(ai_edits):
                            ai_edits[i]["enable"] = enable

                    video_data["ai_edits"] = ai_edits

            if (
                has_patches or args.gen_video_conf
            ) and old_stage >= DraftStages.AUDIO_GEN_VIDEO_CONFIG_GEN:
                if args.gen_video_conf:
                    patch_log("update video conf version")
                    video_data["video_conf_version"] = args.gen_video_conf

                patch_log("regen video config")
                remotion_config_url = generate_remotion_video_config(video_data)
                draft.remotion_config = remotion_config_url
                draft.stage = DraftStages.AUDIO_GEN_VIDEO_CONFIG_GEN
                patch_log("video config generated")

            draft.stage = old_stage
            draft.video_data = json.dumps(video_data)
            db_session.commit()

            if args.gen_video:
                patch_log("render video")
                success, err = DraftResource.trigger_render(
                    args.idea_id, args.version_id, draft, request.url_root
                )
                if success:
                    draft.stage = DraftStages.VIDEO_GEN_STARTED
                else:
                    video_data["render_error"] = err
                    draft.video_data = json.dumps(video_data)
                    draft.stage = DraftStages.VIDEO_GEN_FAILED

                db_session.commit()
        except Exception as e:
            logging.error(f"patch-task error {e}")
        finally:
            valkey_client.delete(f"lock:{idea_id}")
            db_session.close()
            root_logger.removeHandler(file_handler)
            file_handler.close()

    def trigger_render(idea_id, version, draft, webhook_origin):
        webhook = f"{webhook_origin}video_gen_webhook/{idea_id}/{version}"
        client = boto3.client("lambda", **render_service_creds)

        try:
            response = client.invoke(
                FunctionName="pataka-remotion",
                InvocationType="Event",
                Payload=json.dumps(
                    {
                        "config": draft.remotion_config,
                        "uid": f"{idea_id}-{version}",
                        "webhook": webhook,
                    }
                ),
            )

            logging.info(
                "Asynchronous Lambda invocation successful (request received)!"
            )
            logging.info("Response from Lambda service:", response)

            if response["StatusCode"] == 202:
                logging.info(
                    "Lambda function payload accepted for asynchronous processing."
                )
                return True, None
            else:
                logging.info(
                    f"Unexpected status code for async invocation: {response['StatusCode']}"
                )
                error_message = (
                    "render task not queued!"
                    if not response
                    else f"render task error : {response.text}"
                )
                return False, error_message
        except Exception as e:
            logging.exception("Exception while triggering render")
            return False, str(e)

    @staticmethod
    def _handle_video_upload_error(e):
        logger.error("Error during video upload ::", exc_info=True)
        return abort(400, message="something went wrong")

    @staticmethod
    def store_generated_video(
        idea_id, version_id, err, processing, msg, video_link, video_path, db_uri
    ):
        db_session = create_new_db_session(db_uri)
        try:
            draft = db_session.query(Draft).get((idea_id, version_id))
            video_data = json.loads(draft.video_data) if draft.video_data else {}

            if err:
                draft.stage = DraftStages.VIDEO_GEN_FAILED
                if msg:
                    video_data["render_error"] = msg

            if processing:
                draft.stage = DraftStages.VIDEO_GEN_PROCESSING
                video_data["render_processing"] = time.time()

            if video_link:
                draft.generated_video = video_link
                draft.stage = DraftStages.VIDEO_GENERATED
                video_data["render_finish"] = time.time()

            elif video_path:
                link = upload_video(video_path)
                draft.generated_video = link
                draft.stage = DraftStages.VIDEO_GENERATED
                video_data["render_finish"] = time.time()

            draft.video_data = json.dumps(video_data)
            db_session.commit()

            if video_data.get("send_webhook") and supabase:
                supabase_middleware.update_task_status(
                    supabase, draft.idea_id, draft.version, draft.stage
                )

            return {"status": "success"}
        except Exception as e:
            return DraftResource._handle_video_upload_error(e)
        finally:
            db_session.close()

    # Runs the background job that updates the given draft with supplied data or generated fields
    @staticmethod
    def draft_processing_task(
        data, idea_prompt, idea_length, target_draft_version, chatbot, db_uri
    ):
        with app.app_context():
            log_dir = os.path.join(local_cache, "logs")
            os.makedirs(log_dir, exist_ok=True)
            log_file_path = os.path.join(
                log_dir, f"{data['idea_id']}_{target_draft_version}.log"
            )

            file_handler = logging.FileHandler(
                log_file_path, mode="w", encoding="utf-8"
            )
            file_handler.setFormatter(
                logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
            )
            file_handler.setLevel(logging.INFO)

            root_logger = logging.getLogger()
            root_logger.addHandler(file_handler)

            target_draft = None
            db_session = create_new_db_session(db_uri)
            story: list[Any] = []
            character_list: list[Any] = []

            try:
                # Do some time-consuming task here
                logger.info(f"Background task processing draft: {data}")

                target_draft = (
                    db_session.query(Draft)
                    .filter_by(idea_id=data["idea_id"])
                    .filter_by(version=target_draft_version)
                    .first()
                )

                # --- Configuration Persistence Cache ---
                # We save all incoming parameters into video_data on the first run,
                # and retrieve them on subsequent (patched) runs if missing.
                video_data_cache = json.loads(target_draft.video_data or "{}")
                for key in [
                    "content_type",
                    "voice_id",
                    "style_id",
                    "background_music_id",
                    "image_engine",
                ]:
                    if data.get(key):
                        video_data_cache[key] = data.get(key)

                target_draft.video_data = json.dumps(video_data_cache)
                db_session.commit()
                # ----------------------------------------

                story_provided = data["story"]
                conversation_provided = data["conversation"]
                bgm_id = data.get("background_music_id") or video_data_cache.get(
                    "background_music_id"
                )

                content_type = data.get("content_type") or video_data_cache.get(
                    "content_type", "viral social media reel"
                )
                logging.info(f"content-type: {content_type}")

                voice_id = data.get("voice_id") or video_data_cache.get("voice_id")
                voice_character_map = data["voice_character_map"]
                style_id = data.get("style_id") or video_data_cache.get("style_id")
                style_ref_urls = data["style_reference_urls"]

                primary_voice_details = None
                if voice_id:
                    primary_voice_details = db_session.query(Voice).get(voice_id)

                style_details = db_session.query(Styles).get(style_id)

                image_styles = (
                    to_style_data({"themes": [style_details.style_name]})
                    if style_details
                    else to_style_data(data["image_styles"])
                ) or None

                if data.make_image_layers:
                    if image_styles:
                        image_styles.themes.append(subject_outline_prompt)
                    else:
                        image_styles = to_style_data(
                            {"themes": [subject_outline_prompt]}
                        )

                image_urls = data["image_urls"]
                image_prompts = data["image_prompts"]
                image_count = data["image_count"] if data["image_count"] else 10
                bgm_name = data["bgm_name"]
                title_provided = data["title"]
                guidance = data.get("guidance", "")
                video_source = data["video_source"]

                image_engine = data.get("image_engine") or video_data_cache.get(
                    "image_engine"
                )

                character_reference = data["character_ref"] or None
                character_reference = parse_user_provided_character(character_reference)
                character_avatar_map: Dict[str, Any] = {}

                stop_at_stage = (
                    DraftStages.VIDEO_GENERATED
                    if data["gen_video"] == True
                    else (
                        data["stop_at_stage"]
                        if data["stop_at_stage"] != None
                        else DraftStages.AUDIO_GEN_VIDEO_CONFIG_GEN
                    )
                )
                latency: Dict[str, float] = {}

                img_width, img_height = None, None
                try:
                    dims = ui_configs.configs[
                        data.gen_video_conf or "v4"
                    ].get_asset_sizes()
                    (img_width, img_height) = dims.get("images")
                except Exception as e:
                    pass

                image_config = {
                    "name": image_engine,
                    "width": img_width,
                    "height": img_height,
                    "aspect_ratio": "9:16",
                    "resolution": config["PREFS"]["IMAGE_RESOLUTION"],
                }

                if bgm_id and not bgm_name:
                    music = (
                        db_session.query(BackgroundMusic).filter_by(id=bgm_id).first()
                    )
                    if music and music.music_sample:
                        bgm_name = music.music_sample

                def stop_gen(stage):
                    logger.info("Deleting the chatbot conversation")
                    chatbot.delete_conversation()

                    video_data = None

                    if target_draft.video_data:
                        video_data = json.loads(target_draft.video_data)

                        if video_data.get("latency"):
                            video_data["latency"][stage] = latency
                        else:
                            video_data["latency"] = latency
                    else:
                        video_data = {"latency": [latency]}

                    target_draft.video_data = json.dumps(video_data)
                    db_session.commit()
                    db_session.close()

                    return None

                start_time = time.time()

                def on_stage_complete(stage):
                    nonlocal start_time
                    t = time.time()
                    latency[stage] = t - start_time
                    start_time = t

                    if data.send_webhook and supabase:
                        supabase_middleware.update_task_status(
                            supabase, target_draft.idea_id, target_draft.version, stage
                        )

                    logging.info(f"stage completed : {stage}")

                if target_draft.stage == None:
                    target_draft.stage = -1

                if isinstance(stop_at_stage, int):
                    target_draft.target_stage = stop_at_stage

                if bgm_id:
                    target_draft.background_music_id = bgm_id

                if voice_id:
                    target_draft.voice_id = voice_id

                if style_id:
                    target_draft.style_id = style_id

                if style_ref_urls:
                    target_draft.style_reference_urls = style_ref_urls

                image_descriptors = target_draft.image_descriptions.copy()

                video_data = json.loads(target_draft.video_data or "{}")

                # Retrieve or save prompt overrides
                prompt_overrides = video_data.get("prompt_overrides") or data.get(
                    "prompt_overrides"
                )
                if data.get("prompt_overrides") and not video_data.get(
                    "prompt_overrides"
                ):
                    video_data["prompt_overrides"] = data.get("prompt_overrides")
                    target_draft.video_data = json.dumps(video_data)
                    db_session.commit()

                # Persistent, once-off visual style reference extraction (analyzed once, reused across all grids and stages)
                if style_ref_urls:
                    style_desc = video_data.get("style_description")
                    if not style_desc:
                        from processor import extract_style_from_references

                        style_desc = extract_style_from_references(
                            chatbot, style_ref_urls
                        )
                        if style_desc:
                            video_data["style_description"] = style_desc
                            target_draft.video_data = json.dumps(video_data)
                            db_session.commit()

                    if style_desc:
                        # Override any existing text-based image_styles when a definitive style_ref is present
                        image_styles = to_style_data({"themes": [style_desc]})

                title = target_draft.title

                story_raw = target_draft.story
                gen_images = None

                if content_type == "slides":
                    if not guidance:
                        guidance = ""

                    guidance = (
                        "The task is to create a professional powerpoint presentation, images will be used entirely slides. "
                        + guidance
                    )

                if target_draft.stage < DraftStages.STORY_GEN:

                    if video_source:
                        if "instagram" in video_source and "reel" in video_source:
                            video_file = InstaDownload.download_reel(video_source)
                            audio_file = baasha_pipeline_utils.video_to_audio(
                                video_file
                            )
                            logging.info(
                                "video-source: converted to audio -> " + audio_file
                            )
                            story_raw_1 = OpenWhisper.stt(audio_file)

                            timepoints = VoskToolkit.get_audio_timepoints(audio_file)
                            story_raw_1 = " ".join(
                                list(map(lambda x: x[0], timepoints))
                            )

                            story_quest = get_prompt_text("fix-grammar").format(
                                TEXT=story_raw_1
                            )
                            s = generate_data(chatbot, "fix-story-grammar", story_quest)
                            logger.info("story: %s", s)

                            parsed_story = PromptSplitters.json_splitter(
                                {"json_keys": ["text"], "join": True}
                            )(s)
                            story_raw = parsed_story[0]

                    elif content_type != "conversation":
                        story_raw, title = DraftResource.get_story_and_title(
                            chatbot,
                            idea_prompt,
                            idea_length,
                            story_provided,
                            title_provided,
                            guidance,
                        )

                    if "images" not in video_data:
                        video_data.update(
                            generate_dummp_video_data(
                                "", None, None, None, content_type
                            )
                        )

                    if content_type == "conversation":
                        story_sentences: list[Any] = []
                        if conversation_provided:
                            story_sentences = list(
                                map(lambda x: x["text"], conversation_provided)
                            )

                        build_and_set_script_context(chatbot, " ".join(story_sentences))

                        (text_styling, search_images) = get_search_queries_with_styling(
                            chatbot, story_sentences
                        )
                        story = conversation_provided
                    else:
                        build_and_set_script_context(chatbot, story_raw)

                        (
                            story,
                            text_styling,
                            search_images,
                            gen_images,
                            cinematic_data,
                        ) = split_text_into_sentences_with_styling(
                            chatbot,
                            story_raw,
                            content_type,
                            image_styles=image_styles,
                            character_names=list(character_reference.keys())
                            if character_reference
                            else None,
                            style_refs=target_draft.style_reference_urls,
                            prompt_overrides=prompt_overrides,
                        )
                        video_data["cinematic"] = cinematic_data

                    if title:
                        target_draft.title = title

                    story_sentences = story
                    if content_type == "conversation":
                        story_sentences = list(map(lambda x: x["text"], story))

                    video_data["text"] = story
                    video_data["text_styling"] = text_styling
                    video_data["search_image_queries"] = search_images

                    if data.get("ui_config"):
                        video_data["ui_config"] = data["ui_config"]

                    if gen_images:
                        image_descriptors = list(map(lambda x: (x, None), gen_images))
                        target_draft.image_descriptions = image_descriptors

                    video_data["use_image_grid"] = data.use_image_grid
                    target_draft.video_data = json.dumps(video_data)

                    db_session.commit()
                else:
                    video_data = json.loads(target_draft.video_data)

                    if video_data.get("content_type", content_type) == "conversation":
                        story = json.loads(story_raw)
                    else:
                        story = video_data["text"]

                    search_images = video_data.get("search_images", [])
                    text_styling = video_data.get("text_styling", [])

                if not story or len(story) < 1:
                    raise Exception("story is empty!")
                elif content_type == "conversation":
                    target_draft.story = json.dumps(story)
                elif content_type != "reel":
                    target_draft.story = " ".join(story)
                else:
                    target_draft.story = story_raw

                if target_draft.stage < DraftStages.STORY_GEN:
                    target_draft.stage = DraftStages.STORY_GEN
                    on_stage_complete(target_draft.stage)

                if stop_at_stage == target_draft.stage:
                    return stop_gen(target_draft.stage)

                if target_draft.stage < DraftStages.CHARACTER_REF_GEN:
                    if data.use_character_refs:
                        out_dir = "{}.{}".format(data["idea_id"], target_draft_version)
                        character_list = generate_character_bible(
                            chatbot,
                            story,
                            image_styles,
                            image_config,
                            out_dir,
                            style_reference_urls=target_draft.style_reference_urls,
                            user_characters=character_reference,
                            cinematic_data=video_data.get("cinematic"),
                            prompt_overrides=prompt_overrides,
                        )
                        target_draft.character_ref = json.dumps(character_list)

                    if content_type == "conversation":
                        conv_characters = list(map(lambda x: x["character"], story))

                        for c in conv_characters:
                            if character_avatar_map.get(c):
                                continue

                            ref = (
                                character_reference.get(c)
                                if character_reference
                                else None
                            )
                            if ref:
                                character_avatar_map[c] = ref

                    target_draft.stage = DraftStages.CHARACTER_REF_GEN
                    on_stage_complete(target_draft.stage)
                    db_session.commit()
                else:
                    character_list = json.loads(target_draft.character_ref or "[]")

                if stop_at_stage == target_draft.stage:
                    return stop_gen(target_draft.stage)

                if target_draft.stage < DraftStages.IMAGE_PROMPT_GEN:
                    if not image_urls and not image_descriptors:
                        logging.info("Character List: %s", character_list)

                        provided_character_names = (
                            list(character_reference.keys())
                            if character_reference
                            else []
                        )
                        identified_characters = list(
                            map(lambda x: x.get("name"), character_list)
                        )

                        character_names = list(
                            filter(
                                lambda x: x != "narrator_avatar",
                                provided_character_names + identified_characters,
                            )
                        )

                        image_descriptors = DraftResource.get_image_descriptors(
                            chatbot,
                            story
                            if content_type != "conversation"
                            else list(map(lambda x: x["text"], story)),
                            image_prompts,
                            image_count,
                            character_names,
                            image_styles,
                            image_config,
                            guidance,
                            DraftResource.draft_update_callback(
                                db_session, target_draft, "images_prompts"
                            ),
                        )

                    if image_descriptors:
                        target_draft.image_descriptions = image_descriptors

                    target_draft.stage = DraftStages.IMAGE_PROMPT_GEN
                    on_stage_complete(target_draft.stage)
                    db_session.commit()

                    if stop_at_stage == target_draft.stage:
                        return stop_gen(target_draft.stage)

                if data.use_image_grid and target_draft.stage < DraftStages.IMAGE_GEN:
                    chatbot_bbox = BaashaChat.ChatInterface()
                    chatbot_bbox.new_conversation()

                    # Force the grid to be generated at a wider/higher aspect ratio
                    # so the individual panels have more resolution
                    grid_image_config = image_config.copy()
                    grid_image_config["aspect_ratio"] = "1:1"
                    # if image_config.get("width"):
                    #    grid_image_config["width"] = 2048
                    # if image_config.get("height"):
                    #    grid_image_config["height"] = 2048

                    char_refs_for_grid = []
                    for char in character_list:
                        if char.get("url"):
                            char_refs_for_grid.append(
                                {
                                    "url": char["url"],
                                    "type": "character",
                                    "name": f"use the exact face for the character named "
                                    + char["name"]
                                    + " across the scenes",
                                }
                            )

                    style_refs_for_grid = []
                    style_urls = target_draft.style_reference_urls
                    style_str = (
                        (" Target Visual Style: " + image_styles.to_text())
                        if image_styles
                        else ""
                    )
                    if style_urls:
                        style_refs_for_grid = [
                            {
                                "url": s,
                                "type": "style",
                                "name": f"reference for style, aesthetic, color palette, texture only.{style_str}",
                            }
                            for s in style_urls
                        ]

                    # Process images in chunks of 4 to maintain grid quality
                    # and ensure continuity by passing the previous grid as style reference
                    chunk_size = 4
                    all_crops = []
                    all_grids = []
                    all_other_grids = []

                    # Original prompt collection
                    all_prompts = list(
                        map(lambda x: x[0], target_draft.image_descriptions)
                    )
                    previous_grid_url = None
                    chunk_count = len(all_prompts) // chunk_size
                    remainder_chunk = len(all_prompts) % chunk_size
                    prev_chunk_size = chunk_size
                    chunk_idx = 0
                    current_style_refs = []
                    for chunk_num in range(0, chunk_count + remainder_chunk):

                        if chunk_num >= chunk_count:
                            chunk_size = 1

                        chunk_prompts = all_prompts[chunk_idx : chunk_idx + chunk_size]

                        # Use previous grid as style reference if it exists
                        if previous_grid_url:
                            grid_desp = (
                                f"previous shot of scene {chunk_idx}"
                                if chunk_size == 1
                                else f"previous shots from scene {chunk_idx - prev_chunk_size + 1} to {chunk_idx}"
                            )
                            current_style_refs.append(
                                {
                                    "url": previous_grid_url,
                                    "type": "scene",
                                    "name": grid_desp
                                    + " pay extra attention to characters, costumes, positions, location, styling to create next scene",
                                }
                            )

                            if len(current_style_refs) + len(char_refs_for_grid) > 10:
                                style_len = len(style_refs_for_grid)
                                # skip grid from starting
                                current_style_refs = (
                                    list(style_refs_for_grid)
                                    + current_style_refs[style_len + 1 :]
                                )

                        else:
                            current_style_refs = list(style_refs_for_grid)

                        grid_guidance = ""

                        # Add prompt modifier for continuity on subsequent chunks
                        if chunk_idx > 0:
                            grid_guidance = f" This grid will consists of scenes from {chunk_idx + 1} to {chunk_idx + chunk_size} and is a direct continuation of the previous scenes. Refer to location, lighting, and characters as established in the references."

                        # Prompt layout info
                        if chunk_size == 4:
                            grid_guidance += " Arrange the image as a strict 2x2 grid where each of the four panels is a vertically-oriented 9:16 frame, separated by thin black border"
                        elif chunk_size == 1:
                            grid_guidance += " create a single frame only"

                        retries = 2
                        retry_count = 0
                        while retry_count < retries:
                            retry_count += 1

                            res, err = create_image_grid(
                                chunk_prompts,
                                grid_image_config,
                                chatbot_bbox,
                                local_cache,
                                grid_guidance=grid_guidance,
                                character_refs=char_refs_for_grid,
                                style_refs=current_style_refs,
                                image_styles=image_styles,
                                refine_grid_count=1 if data.judge_grids else 0,
                                story_context=target_draft.story,
                                prompt_overrides=prompt_overrides,
                            )

                            if res:
                                story_grid, grid_imgs, other_grids, grid_prompt = res

                                crop_count = (
                                    len(grid_imgs)
                                    if grid_imgs
                                    else (1 if story_grid else 0)
                                )  # for chunk size 1, story grid also counted
                                if not story_grid or len(chunk_prompts) != crop_count:
                                    if retry_count < retries:
                                        logging.info(
                                            f"retrying grid gen, current grid : {story_grid} \n crops : {grid_imgs}"
                                        )
                                        continue
                                retries = -1

                                if story_grid:
                                    previous_grid_url = story_grid
                                    all_grids.append(
                                        (
                                            story_grid,
                                            [chunk_idx, chunk_idx + chunk_size],
                                        )
                                    )

                                all_other_grids.extend(other_grids)

                                if grid_imgs:
                                    all_crops.extend(grid_imgs)
                                elif story_grid:
                                    all_crops.append(story_grid)
                            else:
                                logging.error(
                                    f"Image grid failed for chunk {chunk_idx}: {err}"
                                )
                                grid_prompt = None

                            prev_chunk_size = chunk_size
                            chunk_idx += chunk_size
                            time.sleep(10)

                            break

                    chatbot_bbox.delete_conversation()

                    # Handle accumulated results
                    if all_grids:
                        for idx, grid_data in enumerate(all_grids):
                            grid_url = (
                                grid_data[0]
                                if isinstance(grid_data, tuple)
                                else grid_data
                            )
                            grid_range = (
                                grid_data[1] if isinstance(grid_data, tuple) else None
                            )
                            character_list.append(
                                {
                                    "name": f"story-grid-{idx}",
                                    "url": grid_url,
                                    "range": grid_range,
                                }
                            )

                        if (
                            "grid_prompt" not in video_data
                        ):  # only save the first prompt or a generic one
                            video_data["grid_prompt"] = grid_prompt
                        target_draft.video_data = json.dumps(video_data)
                        db_session.commit()

                    for idx, gd in enumerate(all_other_grids):
                        character_list.append({"name": f"other-grid-{idx}", "url": gd})

                    target_draft.character_ref = json.dumps(character_list)

                    if all_crops:
                        uploaded_crop_urls = []
                        for i, gi in enumerate(all_crops):
                            if i < len(image_descriptors):
                                crop_url = (
                                    upload_image(gi)
                                    if not gi.startswith("http")
                                    else gi
                                )
                                uploaded_crop_urls.append(crop_url)
                                n = f"crop-{i}"
                                character_list.append({"name": n, "url": crop_url})

                        if not isinstance(video_data, dict):
                            video_data = {}

                        video_data["grid_crops"] = uploaded_crop_urls
                        video_data["images"] = uploaded_crop_urls

                        target_draft.character_ref = json.dumps(character_list)
                        target_draft.video_data = json.dumps(video_data)

                if target_draft.stage < DraftStages.IMAGE_GEN:
                    target_draft.stage = DraftStages.IMAGE_GEN
                    on_stage_complete(target_draft.stage)
                    db_session.commit()

                if stop_at_stage == DraftStages.IMAGE_GEN:
                    return stop_gen(target_draft.stage)

                if target_draft.stage < DraftStages.IMAGE_UPSCALE:
                    if getattr(data, "upscale_grid_crops", True) and video_data.get(
                        "use_image_grid"
                    ):
                        grid_crops = video_data.get("grid_crops", [])
                        if grid_crops:
                            enhance_prompt = (
                                f"HIGH FIDELITY NATIVE 9:16 SCENE EXPANSION. "
                                f"Gracefully expand the scene into a native 9:16 aspect ratio. "
                                f"Ensure the generated image perfectly inherits the exact visual medium, art style, "
                                f"texture, detail level, color palette, and lighting of the provided reference crop. "
                                f"DO NOT add digital over-sharpening, high contrast overrides, artificial specular highlights, "
                                f"or synthetic textures that are not present in the crop. "
                                f"Preserve the original atmospheric mood and organic rendering quality of the reference crop completely."
                            )
                            upscale_prompts = [enhance_prompt] * len(grid_crops)

                            base_style_refs = []
                            if target_draft.style_reference_urls:
                                base_style_refs = [
                                    {
                                        "url": s,
                                        "type": "style",
                                        "name": "reference for style, aesthetic, color palette, texture only",
                                    }
                                    for s in target_draft.style_reference_urls
                                ]

                            upscale_ref_urls = [
                                [{"url": crop, "type": "subject", "name": f"crop-{i}"}]
                                + base_style_refs
                                for i, crop in enumerate(grid_crops)
                            ]

                            chatbot_bbox = BaashaChat.ChatInterface()
                            chatbot_bbox.new_conversation()

                            upscaled_images, _, _, _, logs = image_gen(
                                upscale_prompts,
                                upscale_ref_urls,
                                "{}.{}".format(data["idea_id"], target_draft_version),
                                {
                                    "name": image_engine,
                                    "width": image_config.get("width"),
                                    "height": image_config.get("height"),
                                },
                                chatbot_bbox,
                            )
                            video_data["upscaled_images"] = upscaled_images
                            video_data["images"] = upscaled_images
                            target_draft.video_data = json.dumps(video_data)

                    target_draft.stage = DraftStages.IMAGE_UPSCALE
                    on_stage_complete(target_draft.stage)
                    db_session.commit()

                if stop_at_stage == DraftStages.IMAGE_UPSCALE:
                    return stop_gen(target_draft.stage)

                image_urls = video_data.get("upscaled_images") or video_data.get(
                    "images"
                )

                if target_draft.stage < DraftStages.AUDIO_GEN_VIDEO_CONFIG_GEN:

                    validated_voices: Dict[str, Voice] = {}

                    # 1. Resolve manual user mapped voices from database
                    if voice_character_map:
                        for ch in voice_character_map:
                            vid = voice_character_map[ch]
                            if validated_voices.get(ch):
                                continue
                            voice_details = Voice.query.get(vid)
                            if voice_details:
                                validated_voices[ch] = voice_details

                    # 2. Resolve characters with voice descriptions from character bible
                    character_list = (
                        json.loads(target_draft.character_ref)
                        if target_draft.character_ref
                        else []
                    )
                    for char in character_list:
                        ch_name = char.get("name")
                        voice_desc = char.get("voice_description")
                        if ch_name and voice_desc:
                            if ch_name not in validated_voices:
                                validated_voices[ch_name] = Voice(
                                    voice_id="Fenrir",
                                    voice_name="Fenrir",
                                    voice_sample="",
                                    tts_toolkit="gemini",
                                    description=voice_desc,
                                )

                    voice_character_map = validated_voices

                    out_dir = "{}.{}".format(data["idea_id"], target_draft_version)

                    image_dims = (None, None)
                    try:
                        dims = ui_configs.configs[
                            data.gen_video_conf or "v4"
                        ].get_asset_sizes()
                        image_dims = dims.get("images")
                    except Exception as e:
                        pass

                    if not isinstance(video_data, dict):
                        video_data = {}

                    # updated video_data dict inplace
                    # if no errors returned use new dict
                    # if errors then use old dict (updated in place)
                    (new_video_data, errs) = generate_video_data(
                        story,
                        content_type,
                        image_urls,
                        image_descriptors,
                        character_list,
                        character_reference,
                        character_avatar_map,
                        primary_voice_details,
                        voice_character_map,
                        bgm_name,
                        image_config,
                        search_images if data.add_search_assets else None,
                        out_dir,
                        image_styles,
                        video_data,
                        chatbot,
                        style_reference_urls=None
                        if data.use_image_grid
                        else target_draft.style_reference_urls,
                        stop_after_images=(stop_at_stage == DraftStages.IMAGE_GEN),
                    )

                    if not errs:
                        video_data = new_video_data

                    target_draft.character_ref = json.dumps(character_list)

                    if data.send_webhook:
                        video_data["send_webhook"] = True

                    if text_styling:
                        video_data["text_styling"] = text_styling

                    if search_images:
                        video_data["search_images_queries"] = search_images

                    video_data["video_conf_version"] = data.gen_video_conf or "v4"
                    target_draft.video_data = json.dumps(video_data)
                    db_session.commit()

                    if (
                        not errs
                        and data.make_image_layers
                        and video_data.get("image_layers") == None
                    ):
                        layers = list(
                            map(
                                lambda x: create_image_layer(
                                    chatbot,
                                    local_cache,
                                    x,
                                    image_config.get("aspect_ratio", "16:9"),
                                ),
                                video_data["images"],
                            )
                        )
                        video_data["image_layers"] = layers

                        target_draft.video_data = json.dumps(video_data)
                        db_session.commit()

                    if target_draft.stage < DraftStages.IMAGE_GEN:
                        target_draft.stage = DraftStages.IMAGE_GEN
                        on_stage_complete(target_draft.stage)
                        db_session.commit()

                    if stop_at_stage == DraftStages.IMAGE_GEN:
                        return stop_gen(target_draft.stage)

                    if (
                        not errs
                        and data.add_phrase_sounds
                        and AssetGenStages.SOUNDS
                        not in video_data.get("gen_stages", [])
                    ):
                        embeddings = text_embeddings.embedding_gemini(
                            story, dims=384
                        ).tolist()

                        sound_list = []
                        for _, em in enumerate(embeddings or []):
                            res = BackgroundMusicResource.search(
                                transition=True, embedding=em
                            )
                            for r in res:
                                sound_list.append(
                                    {"name": r.music_name, "url": r.music_sample}
                                )

                        video_data["sound_map"] = get_phrase_sound_effects(
                            chatbot,
                            sound_list,
                            video_data["audios"],
                            video_data["timepoints_map"],
                        )
                        video_data["gen_stages"].append(AssetGenStages.SOUNDS)

                        target_draft.video_data = json.dumps(video_data)
                        db_session.commit()

                    remotion_config_url = generate_remotion_video_config(video_data)

                    if remotion_config_url:
                        target_draft.remotion_config = remotion_config_url

                    target_draft.stage = DraftStages.AUDIO_GEN_VIDEO_CONFIG_GEN
                    on_stage_complete(target_draft.stage)

                    db_session.commit()

                logger.info("All draft data generated!")

                if stop_at_stage <= target_draft.stage or not data.get("gen_video"):
                    return stop_gen(target_draft.stage)

                if data.gen_video:
                    logging.info("rendering video")
                    success, err = DraftResource.trigger_render(
                        target_draft.idea_id,
                        target_draft.version,
                        target_draft,
                        request.url_root,
                    )
                    if success:
                        target_draft.stage = DraftStages.VIDEO_GEN_STARTED
                    else:
                        video_data = json.loads(target_draft.video_data)
                        video_data["render_error"] = err
                        target_draft.video_data = json.dumps(video_data)
                        target_draft.stage = DraftStages.VIDEO_GEN_FAILED

                    db_session.commit()
                    on_stage_complete(target_draft.stage)

                return stop_gen(target_draft.stage)

            except Exception as e:
                logging.error("Error during draft processing", exc_info=True)
                if target_draft:
                    if target_draft.video_data:
                        video_data = json.loads(target_draft.video_data)

                    video_data[
                        "draft_create_error"
                    ] = f"An unexpected error occurred - {e}"
                    target_draft.video_data = json.dumps(video_data)

                    db_session.commit()
            finally:
                valkey_client.delete(f"lock:{data['idea_id']}")
                db_session.close()
                root_logger.removeHandler(file_handler)
                file_handler.close()

    @staticmethod
    @with_app_context
    def handle_pending_drafts():
        db_uri = app.config["SQLALCHEMY_DATABASE_URI"]
        db_session = create_new_db_session(db_uri)
        try:
            eight_mins = datetime.utcnow() - timedelta(minutes=8)
            fifteen_mins = datetime.utcnow() - timedelta(minutes=15)
            drafts = (
                db_session.query(Draft)
                .filter(
                    Draft.stage < Draft.target_stage,
                    Draft.stage_updated_at <= eight_mins,
                    Draft.stage_updated_at > fifteen_mins,
                )
                .limit(5)
                .all()
            )

            for q in drafts:
                req_url = f"{request.url_root}/draft"
                method = None

                if (
                    q.stage < DraftStages.AUDIO_GEN_VIDEO_CONFIG_GEN
                    and q.target_stage >= DraftStages.AUDIO_GEN_VIDEO_CONFIG_GEN
                ):
                    method = "POST"

                elif (
                    q.stage >= DraftStages.AUDIO_GEN_VIDEO_CONFIG_GEN
                    and q.target_stage >= DraftStages.VIDEO_GENERATED
                ):
                    method = "PATCH"

                if method:
                    is_updated = (
                        db_session.query(Draft)
                        .filter(
                            Draft.idea_id == q.idea_id,
                            Draft.version == q.version,
                            Draft.stage_updated_at == q.stage_updated_at,
                        )
                        .update({Draft.stage_updated_at: datetime.utcnow()})
                    )

                    if is_updated > 0:
                        requests.request(
                            method,
                            req_url,
                            json={
                                "self_heal": True,
                                "gen_video": True,
                                "idea_id": q.idea_id,
                                "version_id": q.version,
                            },
                        )
                        logging.info(f"HANDLE-PENDING-DRAFT: {q.idea_id}/{q.version}")

        except Exception as e:
            logging.error(f"HANDLE-PENDING-DRAFT-ERROR: {e}")
            pass

        return {"status": "ok"}

    @staticmethod
    @with_app_context
    def handle_failed_drafts():
        db_uri = app.config["SQLALCHEMY_DATABASE_URI"]
        db_session = create_new_db_session(db_uri)
        try:
            fifteen_mins = datetime.utcnow() - timedelta(minutes=15)
            update_count = (
                db_session.query(Draft)
                .filter(
                    Draft.stage < Draft.target_stage,
                    Draft.stage_updated_at <= fifteen_mins,
                )
                .update(
                    {Draft.stage: DraftStages.DRAFT_FAILED}, synchronize_session="auto"
                )
            )

            logging.info(f"failed draft count: {update_count}")
        except Exception as e:
            logging.error(f"HANDLE-FAILED-DRAFT-ERROR: {e}")
            pass

        return {"status": "ok"}

    @staticmethod
    def get_story_and_title(
        chatbot, prompt, length, story_provided, title_provided, guidance
    ):
        suggested_story, suggested_title = None, None
        if not story_provided:
            suggested_story, suggested_title = generate_story_and_title(
                chatbot, prompt, length, guidance
            )
            logger.info("Created a title and story")
        title = title_provided if title_provided else suggested_title
        story = story_provided if story_provided else suggested_story
        return story, title

    @staticmethod
    def get_image_descriptors(
        chatbot,
        story_provided,
        provided_image_descriptors,
        scene_count=10,
        characters="",
        image_styles=None,
        image_config=None,
        guidance=None,
        callback=None,
    ):
        suggested_image_descriptors = []
        if provided_image_descriptors and len(provided_image_descriptors) > 0:
            suggested_image_descriptors = stylize_image_prompts(
                provided_image_descriptors, image_styles
            )
            scene_count = scene_count - len(provided_image_descriptors)

        if scene_count > 0:
            new_scenes = generate_image_prompts(
                "ner",
                chatbot,
                story_provided,
                scene_count=scene_count,
                characters=characters,
                image_styles=image_styles,
                image_config=image_config,
                guidance=guidance,
                callback=callback,
            )
            suggested_image_descriptors = suggested_image_descriptors + new_scenes

        logger.info("Created image descriptions for scenes")
        return suggested_image_descriptors


class DraftSearchResource(Resource):
    @staticmethod
    @with_app_context
    def get():
        idea_id = request.args.get("idea_id")
        episode_index = request.args.get("episode_index")

        if not idea_id:
            return {"error": "idea_id is required"}, 400

        query = Draft.query.filter_by(idea_id=idea_id)
        if episode_index is not None and episode_index != "":
            query = query.filter_by(episode_index=int(episode_index))

        # Order by stage DESC, then version DESC to get the "best" and "latest" draft
        draft = query.order_by(desc(Draft.stage), desc(Draft.version)).first()

        if not draft:
            return {"error": "No drafts found"}, 404

        return as_dict(draft), 200


class VoiceResource(Resource):
    @marshal_with(voice_resource_fields)
    @with_app_context
    def get(self, voice_id=None):
        if voice_id:
            voice = Voice.query.get(voice_id)
            if voice is None:
                abort(404, message="Voice sample not found")
            return voice
        else:
            voices = Voice.query.all()
            result = [
                {
                    "id": voice.id,
                    "voice_name": voice.voice_name,
                    "tags": voice.tags,
                    "voice_sample": voice.voice_sample,
                    "description": voice.description,
                    "tts_toolkit": voice.tts_toolkit,
                }
                for voice in voices
            ]
            return result, 200

    @with_app_context
    @marshal_with(voice_resource_fields)
    def post(self):
        try:
            args = voice_parser.parse_args()
            voice_id = args["voice_id"]
            voice_name = args["voice_name"]
            voice_sample = args["voice_sample"]
            tags = args["tags"]
            description = args["description"]
            tts_toolkit = args["tts_toolkit"]
            voice_clone = args["clone_voice"]

            new_voice = None

            if voice_clone:
                clone_output = None
                err = None
                if tts_toolkit.startswith("replicate"):
                    (clone_output, err) = replicate_api.voice_cloning(voice_sample)

                else:
                    raise Exception("invalid tts toolkit for voice cloning")

                if clone_output:
                    new_voice = Voice(
                        voice_id=clone_output[0],
                        voice_name=voice_name,
                        voice_sample=clone_output[1],
                        tts_toolkit=tts_toolkit,
                        tags=tags,
                        description=description,
                    )
                else:
                    raise Exception(f"voice cloning failed with error - {err}")

            else:
                new_voice = Voice(
                    voice_id=voice_id,
                    voice_name=voice_name,
                    voice_sample=voice_sample,
                    tts_toolkit=tts_toolkit,
                    tags=tags,
                    description=description,
                )

            db.session.add(new_voice)
            db.session.commit()
            db.session.refresh(new_voice)

            return as_dict(new_voice), 201
        except IntegrityError:
            db.session.rollback()
            abort(
                400,
                message="Voice '{}' could not be added as it already exists".format(
                    voice_name
                ),
            )
        except Exception as e:
            db.session.rollback()
            abort(500, message=str(e))

    @staticmethod
    @with_app_context
    def delete(voice_id):
        voice = Voice.query.get(voice_id)
        if voice is None:
            abort(404, message="Voice sample not found")

        db.session.delete(voice)
        db.session.commit()
        return {"message": "Voice sample deleted successfully"}

    @staticmethod
    @with_app_context
    def preload_voices():
        client = ElevenLabs(
            api_key=config["ELEVENLABS"]["API_KEY"],
        )
        elevenlabs_voices = client.voices.get_all().voices

        voice_names = []
        for voice in elevenlabs_voices:
            if voice.name in voice_names:
                voice_names.append("%s_2" % voice.name)
            else:
                voice_names.append(voice.name)
        try:
            for voice_name, voice in zip(voice_names, elevenlabs_voices):
                voice_desc = voice.description
                if not voice_desc:
                    voice_desc = "no description"  # get_voice_description(voice.labels)

                db_voice = Voice.query.get(voice.voice_id)
                if db_voice:
                    # TODO: update preloaded voice
                    continue

                new_voice = Voice(
                    voice_id=voice.voice_id,
                    voice_name=voice_name,
                    voice_sample=voice.preview_url,
                    tts_toolkit="eleven_labs",
                    tags=voice.labels,
                    description=voice_desc,
                )
                db.session.add(new_voice)
            db.session.commit()
            db.session.flush()
        except Exception as e:
            logger.info(f"Preload voice error : {e}")
        finally:
            db.session.flush()

        logger.info("Preloaded elevenlabs voices %d", len(elevenlabs_voices))


def get_voice_description(labels):
    nl = {k.strip().replace(" ", ""): v for k, v in labels.items()}
    article_for = lambda value: "an" if value and value[0] in "aeiou" else "a"
    voice_desc = "{} {} voice in {} {} accent of a {} {}, {}".format(
        article_for(nl.get("description")),
        nl.get("description"),
        article_for(nl.get("accent")),
        nl.get("accent"),
        nl["age"],
        nl["gender"],
        "ideal for %s." % nl["use_case"] if nl["use_case"] else "",
    )
    return voice_desc


class BackgroundMusicResource(Resource):
    @marshal_with(bgm_resource_fields)
    @with_app_context
    def get(self, bgm_id=None):
        if bgm_id:
            bgm = BackgroundMusic.query.get(bgm_id)
            if bgm is None:
                abort(404, message="Background music sample not found")
            return bgm
        else:
            is_transition = request.args.get("transition", "false")

            bgm_tracks = BackgroundMusic.query.filter(
                BackgroundMusic.transition == (is_transition == "true")
            ).all()
            result = [
                {
                    "id": bgm.id,
                    "music_name": bgm.music_name,
                    "music_sample": bgm.music_sample,
                    "tags": bgm.tags,
                    "description": bgm.description,
                    "transition": bgm.transition,
                }
                for bgm in bgm_tracks
            ]
            return result, 200

    @marshal_with(bgm_resource_fields)
    @with_app_context
    def post(self):
        try:
            args = bgm_parser.parse_args()
            bgm_name = args["music_name"]
            bgm_sample = args["music_sample"]
            tags = args["tags"]
            description = args["description"]
            transition = args["transition"]

            embeddings = text_embeddings.embedding_gemini(
                [description], dims=384
            ).tolist()

            if not embeddings:
                raise Exception("music embedding failed")

            new_bgm = BackgroundMusic(
                music_name=bgm_name,
                music_sample=bgm_sample,
                transition=transition or False,
                tags=tags,
                description=description,
                embedding=embeddings[0] if len(embeddings) == 384 else None,
            )
            db.session.add(new_bgm)
            db.session.commit()
            return new_bgm, 201
        except IntegrityError:
            abort(
                400, message=f"Background music could not be added as it already exists"
            )

        except Exception as e:
            abort(
                500, message=f"Background music could not be added due to error : {e}"
            )
        finally:
            db.session.flush()

    @staticmethod
    @with_app_context
    def search(transition=False, embedding=None):
        try:
            bgms = BackgroundMusic.query.filter(
                BackgroundMusic.transition == transition
            )
            limit = 15
            if embedding is not None and len(embedding) == 384:
                bgms = bgms.order_by(
                    BackgroundMusic.embedding.cosine_distance(embedding)
                )
                limit = 5
            bgms = bgms.limit(limit).all()
            return bgms
        except Exception as e:
            logging.error(f"error while bgm search: {e}")
            return []

    @staticmethod
    @with_app_context
    def delete(bgm_id):
        bgm = BackgroundMusic.query.get(bgm_id)
        if bgm is None:
            abort(404, message="Background music sample not found")

        db.session.delete(bgm)
        db.session.commit()
        db.session.flush()
        return {"message": f"Background music id {bgm_id} deleted successfully"}


class StylesResource(Resource):
    @marshal_with(style_resource_fields)
    @with_app_context
    def get(self, style_id=None):
        if style_id:
            style = Styles.query.get(style_id)
            if style is None:
                abort(404, message="Image stylesample not found")
            return style
        else:
            style_types = Styles.query.all()
            result = [
                {
                    "id": style.id,
                    "style_name": style.style_name,
                    "style_sample": style.style_sample,
                    "tags": style.tags,
                    "description": style.description,
                }
                for style in style_types
            ]
            return result, 200

    @marshal_with(style_resource_fields)
    @with_app_context
    def post(self):
        try:
            args = style_parser.parse_args()
            style_name = args["style_name"]
            style_sample = args["style_sample"]
            tags = args["tags"]
            description = args["description"]

            new_style = Styles(
                style_name=style_name,
                style_sample=style_sample,
                tags=tags,
                description=description,
            )
            db.session.add(new_style)
            db.session.commit()
            return new_style, 201
        except IntegrityError:
            abort(400, message=f"Image style could not be added as it already exists")
        finally:
            db.session.flush()

    @staticmethod
    @with_app_context
    def delete(style_id):
        style = Styles.query.get(style_id)
        if style is None:
            abort(404, message="Image style sample not found")

        db.session.delete(style)
        db.session.commit()
        db.session.flush()
        return {"message": f"Image style id {style_id} deleted successfully"}


# Resource for /preview/{idea-id} endpoint
class PreviewResource(Resource):
    @staticmethod
    @with_app_context
    def get(idea_id, version_id=None):
        draft = DraftResource.get_draft(idea_id, version_id)

        if not draft.processed:
            version = "latest" if not version_id else version_id
            return {
                "message": "Draft version {} for idea {} is not ready for preview".format(
                    version, idea_id
                )
            }, 202
        if draft is None:
            return {"error": "Draft not found"}, 404
        return as_dict(draft)


class MoodboardResource(Resource):
    def post(self):
        from parsers import moodboard_parser
        from processor import generate_moodboard

        args = moodboard_parser.parse_args()
        topic = args.topic
        ctx = args.ctx
        num_styles = args.num_styles

        try:
            chatbot = BaashaChat.ChatInterface()
            chatbot.new_conversation()

            moodboard_results = generate_moodboard(
                chatbot, topic, ctx, num_styles, local_cache
            )

            return {"topic": topic, "ctx": ctx, "moodboard": moodboard_results}, 200

        except Exception as e:
            logging.error(f"Moodboard generation failed: {e}")
            return {"error": str(e)}, 500

            return {"topic": topic, "ctx": ctx, "moodboard": moodboard_results}, 200

        except Exception as e:
            logging.error(f"Error in MoodboardResource: {e}")
            return {"error": str(e)}, 500


class CharacterBibleResource(Resource):
    def post(self):
        from parsers import character_bible_parser
        from processor import generate_character_bible
        import os

        args = character_bible_parser.parse_args()
        story = args.story
        style_urls = args.style_urls or []

        try:
            chatbot = BaashaChat.ChatInterface()
            chatbot.new_conversation()

            image_config = {"name": "gemini_nano_banana"}
            outdir = "static/tmp"
            if not os.path.exists(outdir):
                os.makedirs(outdir)

            characters = generate_character_bible(
                chatbot=chatbot,
                story=story,
                image_styles=None,
                image_config=image_config,
                outdir=outdir,
                style_reference_urls=style_urls,
            )

            return {"story": story, "characters": characters}, 200

        except Exception as e:
            logging.error(f"Character Bible generation failed: {e}")
            return {"error": str(e)}, 500


class ImageLayersResource(Resource):
    def post(self):
        args = image_layers_test_parser.parse_args()
        prompt = args.get("prompt")
        image_url = args.get("image_url")
        depth = args.get("depth", 1)
        aspect_ratio = args.get("aspect_ratio", "9:16")
        err = None

        try:
            chatbot = BaashaChat.ChatInterface()
            chatbot.new_conversation()

            # Initial Image
            if not image_url and prompt:
                image_url, err = gemini.generate_image(
                    prompt, aspect_ratio=aspect_ratio
                )
            elif not image_url and not prompt:
                return {"error": "Either prompt or image_url is required"}, 400

            if not image_url:
                return {f"error": "Image gen failed {err}"}, 500

            results = {"base_image": image_url, "steps": []}
            current_image = image_url

            for i in range(1, depth + 1):
                outlined_url, err = gemini.generate_image(
                    subject_outline_prompt,
                    refs=[{"url": current_image, "type": "subject"}],
                    aspect_ratio=aspect_ratio,
                )

                if not outlined_url or err:
                    continue

                layer_url, clean_bg_url = create_image_layer(
                    chatbot, local_cache, outlined_url, aspect_ratio
                )

                results["steps"].append(
                    {
                        "depth": i,
                        "outlined": outlined_url,
                        "background": clean_bg_url,
                        "layer": layer_url,
                    }
                )

                current_image = outlined_url  # Recursive

            return results, 200

        except Exception as e:
            logging.error(f"Image layering test failed: {e}")
            return {"error": str(e)}, 500


class ViralStoryResource(Resource):
    def post(self):
        args = viral_story_parser.parse_args()
        prompt = args.get("prompt")
        guidance = args.get("guidance", "")

        try:
            chatbot = BaashaChat.ChatInterface()
            chatbot.new_conversation()

            # Using the unified flow in test_story_gen
            (
                text,
                styling,
                search_images,
                gen_images,
            ) = test_story_gen(chatbot, prompt, guidance=guidance)

            results = []
            for i in range(len(text)):
                results.append(
                    {
                        "scene": i + 1,
                        "text": text[i],
                        "styling": styling[i],
                        "search_query": search_images[i],
                        "image_prompt": gen_images[i],
                    }
                )

            return {"story": results}, 200

        except Exception as e:
            logging.error(f"Viral story generation failed: {e}")
            return {"error": str(e)}, 500


class SimilarIdeaResource(Resource):
    @with_app_context
    def post(self):
        """Find top 3 similar ideas from the last month that reachable Stage 4+."""
        try:
            data = request.get_json()
            query = data.get("query")
            if not query:
                return {"error": "query required"}, 400

            one_month_ago = datetime.utcnow() - timedelta(days=30)

            # Optimized Query: Find the 100 most recent unique prompts
            # 1. Subquery to find the latest creation timestamp for each unique prompt
            prompt_latest = (
                db.session.query(
                    Idea.prompt, func.max(Draft.created_at).label("latest")
                )
                .join(Draft, Idea.id == Draft.idea_id)
                .filter(Draft.stage >= DraftStages.IMAGE_GEN)
                .group_by(Idea.prompt)
                .subquery()
            )

            # 2. Subquery to get exactly one Idea.id for each of those prompts (ordered by recency)
            unique_idea_ids = (
                db.session.query(
                    func.max(Idea.id).label("target_idea_id"),
                    func.max(Draft.created_at).label("max_created"),
                )
                .join(Draft, Idea.id == Draft.idea_id)
                .join(
                    prompt_latest,
                    (Idea.prompt == prompt_latest.c.prompt)
                    & (Draft.created_at == prompt_latest.c.latest),
                )
                .group_by(Idea.prompt)
                .order_by(desc("max_created"))
                .limit(10)
                .subquery()
            )

            # 3. Final query to fetch the Idea objects
            successful_ideas = (
                Idea.query.join(
                    unique_idea_ids, Idea.id == unique_idea_ids.c.target_idea_id
                )
                .order_by(unique_idea_ids.c.max_created.desc())
                .all()
            )

            if not successful_ideas:
                return [], 200

            prompts = [i.prompt for i in successful_ideas]
            similarities = text_embeddings.embedding_gemini_compare(query, prompts)

            if similarities is None:
                logging.error(
                    "Similarity search returned None (likely API error). Falling back to recency."
                )
                # Fallback: Return top 3 most recent instead of failing
                return [
                    {"id": i.id, "prompt": i.prompt, "similarity": 0.0}
                    for i in successful_ideas[:3]
                ], 200

            scored_ideas = sorted(
                zip(successful_ideas, similarities), key=lambda x: x[1], reverse=True
            )

            results = []
            for idea, score in scored_ideas[:3]:
                results.append(
                    {
                        "id": idea.id,
                        "prompt": idea.prompt,
                        "similarity": round(float(score), 4),
                    }
                )

            return results, 200
        except Exception as e:
            logging.error(f"Similar idea search failed: {e}")
            return {"error": str(e)}, 500


# Define API routes
api.add_resource(IdeaResource, "/idea", "/idea/<string:idea_id>")
api.add_resource(
    DraftResource,
    "/draft",
    "/draft/<string:idea_id>",
    "/draft/<string:idea_id>/<int:version_id>",
)
api.add_resource(DraftSearchResource, "/draft/search")
api.add_resource(
    PreviewResource,
    "/preview/<string:idea_id>",
    "/preview/<string:idea_id>/<int:version_id>",
)
api.add_resource(VoiceResource, "/voices", "/voices/<string:voice_id>")
api.add_resource(BackgroundMusicResource, "/bgm", "/bgm/<string:bgm_id>")
api.add_resource(StylesResource, "/styles", "/styles/<string:style_id>")
api.add_resource(MoodboardResource, "/api/moodboard")
api.add_resource(CharacterBibleResource, "/api/character_bible")
api.add_resource(ImageLayersResource, "/api/test/image-layers")
api.add_resource(ViralStoryResource, "/api/test/viral-story")
api.add_resource(SimilarIdeaResource, "/idea/similar")


@app.route("/video_gen_webhook/<string:idea>/<int:version>", methods=["GET"])
@with_app_context
def video_gen_webhook(idea, version):
    try:
        p = request.args.get("path")
        u = request.args.get("link")
        e = request.args.get("error")
        l = request.args.get("processing")
        m = request.args.get("msg")

        db_uri = app.config["SQLALCHEMY_DATABASE_URI"]
        if "akamaidb.net" in db_uri and "sslmode=require" not in db_uri:
            if "?" in db_uri:
                db_uri += "&sslmode=require&sslcompression=0"
            else:
                db_uri += "?sslmode=require&sslcompression=0"

        DraftResource.store_generated_video(idea, version, e, l, m, u, p, db_uri)
        return {"status": "success"}
    except Exception as e:
        logger.error(f"video_gen_hook_error ::: {e}")
        return {"status": "error"}


# Define a health check endpoint
@app.route("/cleanup", methods=["GET"])
@with_app_context
def cleanup():
    DraftResource.handle_pending_drafts()
    DraftResource.handle_failed_drafts()

    return jsonify({"status": "ok"})


# Define a health check endpoint
@app.route("/health", methods=["GET"])
@with_app_context
def health_check():
    # You can add more sophisticated checks here if needed
    # For a basic health check, simply return a success message
    return jsonify({"status": "healthy"})


@app.route("/hugchat", methods=["DELETE"])
@with_app_context
def del_hugchat_conv():
    # del conv
    bot = HugChat.get_chatbot()

    bot.delete_all_conversations()

    return jsonify({"status": "success"})


@app.route("/scrape/videos", methods=["GET"])
def get_scraped_videos():
    try:
        if os.path.exists("vid.json"):
            with open("vid.json", "r") as f:
                data = json.loads(f.read())
                return {"result": data}
    except Exception as e:
        logger.error(f"Error reading vid.json: {e}")

    return {"result": []}


@app.route("/scrape/videos", methods=["POST"])
def scrape_videos():
    data = request.get_json()
    l = data.get("link") if data else None
    s = data.get("store") if data else None  # Option to store video data (result)
    store_scraper_info = data.get(
        "store_scraper", False
    )  # Option to store scraper info

    if not l:
        return {"error": "Link is required in the request body"}, 400

    results = scrape_videos_from_link(l, store_scraper_info)

    if results and s:
        results = store_scraped_vidoes(results, l)

    return {"result": results}, 200


def mk_scrape_video_link(topic, orientation="horizontal"):
    t = "+".join(topic.split(" "))
    return f"https://www.freepik.com/search?format=search&last_filter=query&last_value={t}&query={t}&selection=1&type=video&videoOrientation={orientation}"


@errors.log_ctx_errors
def scrape_videos_from_link(l, store_scraper=False):
    origin = l.replace("https://", "").replace("http://", "").split("/")[0]
    scrapers_file = "scrapers.json"
    existing_scrapers = []
    if os.path.exists(scrapers_file):
        try:
            with open(scrapers_file, "r") as f:
                existing_scrapers = json.load(f)
        except json.JSONDecodeError:
            logger.warning(f"Could not decode {scrapers_file}, starting fresh.")
            existing_scrapers = []
        except Exception as e:
            logger.error(f"Error reading {scrapers_file}: {e}")
            # Continue, but don't use potentially corrupted data

    old_scraper_info = None
    result: list[Any] = []
    raw_results: list[Any] = []
    scraper_info = None

    for scraper_entry in existing_scrapers:
        if scraper_entry.get("origin") == origin:
            old_scraper_info = scraper_entry.get("scraper")
            break

    # Check if origin already exists
    if old_scraper_info:
        logger.info(f"Origin {origin} already exists in {scrapers_file}.")
        raw_results = build_scraper.run_scraper(l, old_scraper_info, 1)

    else:
        t = "fetch all the playable video links and descriptions of the displayed videos. Fetch links directly from HTML video tags src / source attributes and keep links which are downloadable and have a valid video extensions like mp4, mkv, webm. Format the result as JSON array with keys video_link and desp. Both the keys are required, do not add missing / default values."

        try:
            raw_results, scraper_info = build_scraper.build_and_run_generic_scraper(
                t, l, pages=1
            )

            logger.info(f"Scraping of {l} completed.")
        except Exception as e:
            logger.error(f"Error during scraping {l}: {e}")
            return {"error": f"Scraping failed: {e}", "result": []}, 500

    for page in raw_results:
        if isinstance(page, list):
            result = result + page

        elif isinstance(page, str):
            try:
                parsed = json.loads(page)
                if isinstance(parsed, list):
                    result = result + parsed
            except Exception:
                logging.warn(
                    f"Error 1 while parsing page result, page type - {type(page)}"
                )
        else:
            logging.warn(f"Error 2 while parsing page result, page type - {type(page)}")

    if len(raw_results) > 0:
        if store_scraper and scraper_info and not old_scraper_info:
            current_scrapers = []
            if os.path.exists(scrapers_file):
                try:
                    with open(scrapers_file, "r") as f:
                        current_scrapers = json.load(f)
                except json.JSONDecodeError:
                    logger.warning(f"Could not decode {scrapers_file} again.")
                    current_scrapers = []
                except Exception as e:
                    logger.error(f"Error reading {scrapers_file} again: {e}")

            if not any(
                scraper_entry.get("origin") == origin
                for scraper_entry in current_scrapers
            ):
                current_scrapers.append({"origin": origin, "scraper": scraper_info})
                try:
                    with open(scrapers_file, "w") as f:
                        json.dump(current_scrapers, f, indent=4)
                        logging.info(
                            f"Scraper info for {l} stored successfully in {scrapers_file}"
                        )
                except Exception as e:
                    logger.error(f"Error writing to {scrapers_file}: {e}")
            else:
                logger.warning(
                    f"Origin {l} found in {scrapers_file} during second check, not re-adding."
                )

    return result


@errors.log_ctx_errors
def store_scraped_vidoes(result, link):
    all_data = []
    new_data = []

    if result and len(result) > 0:
        uploaded_results = []
        for r in result:
            url = r["video_link"]
            local_file = download_file(
                url,
                os.path.join(local_cache, "stock_videos"),
                prefix="stock_video_",
            )

            if local_file:
                pub_link = upload_video(local_file)

            if pub_link:
                uploaded_results.append(
                    {"desp": r["desp"], "video_link": pub_link, "page_url": link}
                )

        result = uploaded_results
        vid_file = "vid.json"
        old_data = []
        if os.path.exists(vid_file):
            try:
                with open(vid_file, "r") as f:
                    old_data = json.loads(f.read())
            except json.JSONDecodeError:
                logger.warning(
                    f"Could not decode {vid_file}, starting fresh for video data."
                )
                old_data = []
            except Exception as e:
                logger.error(f"Error reading {vid_file}: {e}")

        # Append new video data, potentially adding a link to the origin
        # For now, just appending results directly
        all_data = old_data + uploaded_results
        new_data = uploaded_results

        try:
            with open(vid_file, "w") as f:
                json.dump(new_data, f, indent=4)
                logging.info("videos store success")
        except Exception as e:
            logger.error(f"Error writing to {vid_file}: {e}")

    return all_data, new_data


@app.route("/test/all", methods=["GET"])
@with_app_context
def test():
    logger.info("testing")
    chatbot = BaashaChat.ChatInterface("hugchat")

    chatbot.new_conversation()

    try:
        T.regress_prompt(chatbot)

    except Exception as e:
        logging.error(f"error while running test/all: \n {e}")

    finally:
        chatbot.delete_conversation()

    return {"status": "test ended, check stdout"}


@app.route("/test/image/<string:engine>")
@with_app_context
def test_img_gen(engine):
    T.test_image_gen(engine)

    return {"status": "check stdout"}


@app.route("/test/image-prompts/<string:engine>")
@with_app_context
def test_img_prompt(engine):
    chatbot = BaashaChat.ChatInterface()
    new_scenes = generate_image_prompts(
        "ner",
        chatbot,
        ["I am superman", "save ghotham city", "say my name, walter white"],
        scene_count=3,
        characters=[],
        image_styles=to_style_data(
            {"themes": ["Minimalistic, monotone, aesthetic, super clear, HD"]}
        ),
        image_config={
            "name": engine,
            "width": 1080,
            "height": 1920,
        },
        guidance="",
        callback=None,
    )

    return {"prompts": new_scenes}


@app.route("/test/video-search", methods=["POST"])
def test_video_search():
    data = request.get_json()
    search = data.get("search") if data else None

    vid = get_similar_video(search, data=None)

    return {"result": vid}


@app.route("/test/image-search", methods=["POST"])
@with_app_context
def test_image_search():
    data = request.get_json()
    search = data.get("search") if data else None

    if not search:
        return {"error": True}

    chatbot = BaashaChat.ChatInterface("groq")
    chatbot.new_conversation()

    out = multi_google_search(chatbot, [search], None, None, None, False)

    chatbot.delete_conversation()

    return {"result": out}


@app.route("/test/sound-search", methods=["POST"])
@with_app_context
def test_sound_search():
    data = request.get_json()
    story = data.get("story") if data else None

    if not story:
        return {"error": True}

    chatbot = BaashaChat.ChatInterface()
    chatbot.new_conversation()

    (
        sentences,
        text_styling,
        _,
        _,
        cinematic_data,
    ) = split_text_into_sentences_with_styling(chatbot, story, "story")

    embeddings = text_embeddings.embedding_gemini(sentences, dims=384).tolist()
    sound_list = []
    visited = []
    for idx, e in enumerate(embeddings or []):
        res = BackgroundMusicResource.search(transition=True, embedding=e)
        for r in res:
            if r.music_name not in visited:
                sound_list.append({"name": r.music_name, "url": r.music_sample})
                visited.append(r.music_name)

    sound_map = generate_phrase_sound_effects(chatbot, sound_list, story)
    chatbot.delete_conversation()

    return {"sound_list": sound_list, "sound_map": sound_map}


# Video Display
@app.route("/videos", methods=["GET"])
def stock_videos():
    return send_from_directory("static", "vids.html")


@app.route("/", methods=["GET"])
def frontend():
    return send_from_directory("static", "frontend.html")


@app.route("/layers", methods=["GET"])
def serve_layers():
    return send_from_directory("static", "layers.html")


@app.route("/moodboard", methods=["GET"])
def serve_moodboard():
    return send_from_directory("static/moodboard", "index.html")


@app.route("/stories", methods=["GET"])
def serve_stories():
    return send_from_directory("static", "stories.html")


@app.route("/stages", methods=["GET"])
def serve_stages():
    return send_from_directory("static", "stages.html")


@app.route("/create", methods=["GET"])
def serve_create():
    return send_from_directory("static", "create.html")


@app.route("/create/override/<override_name>", methods=["GET"])
def serve_create_override(override_name):
    return send_from_directory("static", "create.html")


@app.route("/draft/logs/<string:idea_id>/<int:version_id>", methods=["GET"])
def get_draft_logs(idea_id, version_id):
    log_dir = os.path.join(local_cache, "logs")
    log_file_path = os.path.join(log_dir, f"{idea_id}_{version_id}.log")
    if os.path.exists(log_file_path):
        try:
            with open(log_file_path, "r", encoding="utf-8") as f:
                logs = f.read()
            return jsonify({"status": "success", "logs": logs})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500
    else:
        return (
            jsonify(
                {"status": "not_found", "logs": "No logs recorded yet for this draft."}
            ),
            200,
        )


@app.route("/moodboard/<path:path>")
def serve_moodboard_assets(path):
    return send_from_directory("static/moodboard", path)


@app.route("/character-bible", methods=["GET"])
def serve_character_bible():
    return send_from_directory("static/character_bible", "index.html")


@app.route("/character-bible/<path:path>")
def serve_character_bible_assets(path):
    return send_from_directory("static/character_bible", path)


def as_dict(obj):
    result = {}
    for c in inspect(obj).mapper.column_attrs:
        value = getattr(obj, c.key)
        if isinstance(value, datetime):
            result[c.key] = value.isoformat()
        else:
            result[c.key] = value
    return result


@app.route("/api/judge_grid", methods=["POST"])
def api_judge_grid():
    data = request.json
    grid_url = data.get("grid_url")
    story_context = data.get("story_context", "")
    panel_descriptions = data.get("panel_descriptions", [])
    character_list = data.get("character_list", [])

    if not grid_url:
        return jsonify({"error": "grid_url is required"}), 400

    chatbot = BaashaChat.ChatInterface()
    chatbot.new_conversation()

    report = judge_image_grid(
        grid_url, None, story_context, panel_descriptions, character_list, chatbot
    )

    return jsonify(report)


@app.route("/api/refine_grid", methods=["POST"])
def api_refine_grid():
    data = request.json
    grid_url = data.get("grid_url")
    story_context = data.get("story_context", "")
    panel_descriptions = data.get("panel_descriptions", [])
    character_list = data.get("character_list", [])
    image_config = data.get(
        "image_config", {"name": "gemini_nano_banana", "aspect_ratio": "1:1"}
    )
    outdir = local_cache

    # Handle Optional Refs
    character_refs = data.get("character_refs")
    style_refs = data.get("style_refs")
    image_styles = data.get("image_styles")

    chatbot = BaashaChat.ChatInterface()
    chatbot.new_conversation()

    new_grid_url, report = refine_and_fix_grid(
        chatbot,
        grid_url,
        style_refs,
        story_context,
        panel_descriptions,
        character_list,
        image_config,
        None,
        outdir,
    )

    return jsonify(
        {
            "original_grid_url": grid_url,
            "refined_grid_url": new_grid_url,
            "audit_report": report,
        }
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
