from flask_restful import fields, reqparse
from numpy import require


def dict_or_str(value):
    if isinstance(value, dict) or isinstance(value, str):
        return value
    import json

    try:
        return json.loads(value)
    except:
        return str(value)


# Request parser for validation
idea_parser = reqparse.RequestParser()
idea_parser.add_argument(
    "prompt",
    type=str,
    required=True,
    help="Prompt is required and must be a string under 200 characters",
)
idea_parser.add_argument(
    "length",
    type=int,
    required=True,
    help="Length is required and must be a non-zero integer",
)
idea_parser.add_argument(
    "user_id",
    type=str,
    required=False,
    default="unregistered",
    help="User ID for the Idea",
)
idea_parser.add_argument(
    "is_series",
    type=bool,
    required=False,
    default=False,
    help="Is this idea for a series?",
)
idea_parser.add_argument(
    "episode_breakdown",
    type=list,
    location="json",
    required=False,
    help="Breakdown of episodes if is_series is True",
)

# Request parser for Draft validation
draft_parser = reqparse.RequestParser()
draft_parser.add_argument("idea_id", type=str, required=True, help="Idea of the draft")
draft_parser.add_argument(
    "version_id",
    type=int,
    required=False,
    help="Version of the draft for the given idea",
)
draft_parser.add_argument(
    "episode_index",
    type=int,
    required=False,
    help="Index of the episode in the series breakdown",
)
draft_parser.add_argument(
    "story",
    type=str,
    required=False,
    help="Story text for the draft for the given idea",
)
draft_parser.add_argument(
    "conversation",
    type=dict,
    action="append",
    required=False,
    help="turn based conversation with characters",
)
draft_parser.add_argument(
    "video_source",
    type=str,
    required=False,
    help="Use video link to fetch story",
)
draft_parser.add_argument(
    "title", type=str, required=False, help="Title for the draft for the given idea"
)
draft_parser.add_argument(
    "image_descriptors",
    type=list,
    required=False,
    help="Image descriptors for draft of the idea",
)
draft_parser.add_argument(
    "background_music_id",
    type=int,
    required=False,
    help="BGM for draft of the given idea",
)
draft_parser.add_argument(
    "voice_id", type=str, required=False, help="Voice id for draft of the given idea"
)
draft_parser.add_argument(
    "style_id", type=str, required=False, help="Style id for draft of the given idea"
)
draft_parser.add_argument(
    "guidance", type=str, required=False, help="Guidance for the draft creation"
)
draft_parser.add_argument(
    "image_count", type=int, required=False, help="Number of images to generate"
)
draft_parser.add_argument(
    "image_styles",
    type=dict,
    required=False,
    help="Append additional styles to images prompts",
)
draft_parser.add_argument(
    "image_prompts", type=str, action="append", required=False, help="Image Prompts"
)
draft_parser.add_argument(
    "image_urls", type=str, action="append", required=False, help="Generated Images!"
)
draft_parser.add_argument(
    "bgm_name", type=str, required=False, help="Background Music Name!"
)
draft_parser.add_argument(
    "upscale_image", type=bool, required=False, help="Upscale Images!"
)
draft_parser.add_argument(
    "gen_audio", type=str, action="append", required=False, help="Generate Audio!"
)
draft_parser.add_argument(
    "tts_toolkit", type=str, required=False, default="gtts", help="Change TTS Toolkit!"
)
draft_parser.add_argument(
    "text_to_speech",
    type=str,
    required=False,
    default=None,
    help="Add your story audio!",
)
draft_parser.add_argument(
    "image_engine", type=str, required=False, help="Image Gen Model!"
)
draft_parser.add_argument(
    "avatar_engine", type=str, required=False, help="Image Gen Model!"
)
draft_parser.add_argument(
    "video_engine", type=str, required=False, help="Video Gen Model!"
)
draft_parser.add_argument("gen_video", type=bool, required=False, help="Generate Video")
draft_parser.add_argument(
    "character_ref", type=dict, required=False, help="Image to be used as Reference!"
)
draft_parser.add_argument(
    "use_character_refs", type=bool, required=False, help="Enable character ref stage"
)
draft_parser.add_argument(
    "add_phrase_sounds", type=bool, required=False, help="Enable background sounds"
)
draft_parser.add_argument(
    "add_search_assets", type=bool, required=False, help="Enable Search"
)
draft_parser.add_argument(
    "make_image_layers",
    type=bool,
    required=False,
    help="Make image layers for forground and background",
)
draft_parser.add_argument(
    "use_image_grid",
    type=bool,
    required=False,
    help="Use image grid to create scenes references in one shot",
)
draft_parser.add_argument(
    "upscale_grid_crops",
    type=bool,
    required=False,
    help="Upscale grid crops using image-to-image or keep them as is",
)
draft_parser.add_argument(
    "content_type",
    type=str,
    required=False,
    help="Type of content - story|conversation",
)
draft_parser.add_argument(
    "voice_character_map",
    type=dict,
    required=False,
    help="Map voice for each character",
)
draft_parser.add_argument(
    "ui_order", type=dict, required=False, help="Change image+audio+text ordering!"
)
draft_parser.add_argument(
    "ai_edit_ui", type=str, required=False, help="Edit UI using natural language!"
)
draft_parser.add_argument(
    "toggle_ai_edit",
    type=bool,
    action="append",
    required=False,
    help="Toggle AI Edits!",
)
draft_parser.add_argument(
    "regen_images",
    type=int,
    action="append",
    required=False,
    help="re-gen image by position!",
)
draft_parser.add_argument(
    "regen_image_prompts",
    type=str,
    action="append",
    required=False,
    help="re-gen image prompt by position!",
)
draft_parser.add_argument(
    "edit_story_sentence", type=dict, required=False, help="Edit story sentence!"
)
draft_parser.add_argument(
    "stop_at_stage", type=int, required=False, help="Generation till stage"
)
draft_parser.add_argument(
    "edit_inplace", type=bool, required=False, help="Apply edits to current draft"
)
draft_parser.add_argument(
    "gen_video_conf", type=str, required=False, help="Re-create video config"
)
draft_parser.add_argument(
    "self_heal", type=bool, required=False, help="Heal broken assets"
)
draft_parser.add_argument(
    "convert_to_video",
    type=dict,
    action="append",
    required=False,
    help="Convert image to video",
)
draft_parser.add_argument(
    "send_webhook", type=bool, required=False, help="Update supabase task table"
)
draft_parser.add_argument(
    "ui_config", type=dict, required=False, help="UI Configuration for the draft"
)
draft_parser.add_argument(
    "episodic_memory",
    type=str,
    required=False,
    help="Provide episodic memory or global context for the LLM.",
)
draft_parser.add_argument(
    "style_reference_urls",
    type=str,
    action="append",
    required=False,
    help="URLs to use as exact style references.",
)
draft_parser.add_argument(
    "judge_images",
    type=bool,
    required=False,
    help="Enable LLM Judge and instruction-based fix",
)
draft_parser.add_argument(
    "judge_grids",
    type=bool,
    required=False,
    help="Enable LLM Judge and instruction-based grid fix",
)

draft_parser.add_argument(
    "prompt_overrides",
    type=dict_or_str,
    required=False,
    help="Custom prompt overrides for screenplay, grid, and judge",
)

# Request parser for Style validation
style_parser = reqparse.RequestParser()
style_parser.add_argument(
    "style_name", type=str, required=True, help="Style name is required"
)
style_parser.add_argument(
    "style_sample", type=str, required=True, help="Style sample is required"
)
style_parser.add_argument("tags", type=str, default=[])
style_parser.add_argument("description", type=str, default="")


# Request parser for Voice validation
voice_parser = reqparse.RequestParser()
voice_parser.add_argument(
    "voice_name", type=str, required=True, help="Voice name is required"
)
voice_parser.add_argument(
    "voice_sample", type=str, required=True, help="Voice sample is required"
)
voice_parser.add_argument(
    "tags", type=str, default="", required=False, help="Voice sample tags"
)
voice_parser.add_argument("description", type=str, default="")
voice_parser.add_argument("voice_id", type=str, required=True)
voice_parser.add_argument("tts_toolkit", type=str, required=True)
voice_parser.add_argument("clone_voice", type=str, required=False)
voice_parser.add_argument(
    "voice_clone",
    type=bool,
    default=False,
    help="Flag to indicate if this is a voice cloning request",
)

# Request parser for Background Music validation
bgm_parser = reqparse.RequestParser()
bgm_parser.add_argument(
    "music_name", type=str, required=True, help="Music name is required"
)
bgm_parser.add_argument(
    "music_sample", type=str, required=True, help="Music sample is required"
)
bgm_parser.add_argument("tags", type=str, default=[])
bgm_parser.add_argument("description", type=str, default="")
bgm_parser.add_argument("transition", type=bool, default=False)

# Fields for response serialization
bgm_resource_fields = {
    "id": fields.Integer,
    "music_name": fields.String,
    "music_sample": fields.String,
    "tags": fields.String,
    "description": fields.String,
    "transition": fields.Boolean,
}

# Fields for response serialization
style_resource_fields = {
    "id": fields.Integer,
    "style_name": fields.String,
    "style_sample": fields.String,
    "tags": fields.String,
    "description": fields.String,
}

# Fields for response serialization
voice_resource_fields = {
    "id": fields.String,
    "voice_name": fields.String,
    "voice_sample": fields.String,
    "tags": fields.String,
    "description": fields.String,
    "tts_toolkit": fields.String,
}

moodboard_parser = reqparse.RequestParser()
moodboard_parser.add_argument(
    "topic", type=str, required=True, location=["json", "args"]
)
moodboard_parser.add_argument(
    "ctx", type=str, required=False, default="", location=["json", "args"]
)
moodboard_parser.add_argument(
    "num_styles", type=int, required=False, default=3, location=["json", "args"]
)


image_layers_test_parser = reqparse.RequestParser()
image_layers_test_parser.add_argument("prompt", type=str, required=False)
image_layers_test_parser.add_argument("image_url", type=str, required=False)
image_layers_test_parser.add_argument("depth", type=int, required=False, default=1)
image_layers_test_parser.add_argument(
    "aspect_ratio", type=str, required=False, default="9:16"
)


viral_story_parser = reqparse.RequestParser()
viral_story_parser.add_argument("prompt", type=str, required=True)
viral_story_parser.add_argument("guidance", type=str, required=False, default="")

character_bible_parser = reqparse.RequestParser()
character_bible_parser.add_argument(
    "story", type=str, required=True, location=["json", "args"]
)
character_bible_parser.add_argument(
    "style_urls",
    type=str,
    action="append",
    required=False,
    default=[],
    location=["json", "args"],
)
