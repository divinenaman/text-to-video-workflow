import os
import json
import base64
import logging
import configparser
import httpx
from typing import List, Optional, Dict, Any, Tuple
from fastmcp import FastMCP
from mcp.types import CallToolResult, ImageContent, TextContent
import requests
import time
import io
from PIL import Image as PilImage

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("baasha-mcp")

BAASHA_DIRECTOR_HANDBOOK = """
# The Baasha Creative Director's Handbook

## PROTOCOL: The Continuity & Lineage Protocol (MANDATORY)
A series is only as strong as its consistency. Before starting ANY project, you must check for precursors.

### Step 1: Discovery
Call `get_similar_creative_ideas(idea_text=...)`.
- If you find a match with `similarity > 0.8` or a matching title, YOU ARE IN A SERIES.

### Step 2: User Consent
STOP and ask the user:
> "Director's Note: I've found a strong match for this idea in our archives ([ID]). Should I link this project for Series Continuity, or start a completely fresh narrative?"

### Step 3: Strategic Asset Ingestion
If the user approves, CALL `get_episodic_memory(idea_id=...)`.
- Review the returned **Character Bible**, **Visual Style Guide**, and **Audio Profiles**.
- **Action**: You must strategically reuse these assets in your next tool call to ensure continuity.
- **Character Mapping**: Extract character names and their visual references (`image_urls`) and pass them into the `character_ref` parameter of `start_draft_pipeline`.
- **Style Continuity**: Use the previous `style_id` to lock the aesthetic.
- **Narrative Threading**: Read the previous story versions to ensure the next episode's script follows the established lore.

### Phase 1: The Screenplay Negotiation (MANDATORY)
The user's initial query is NEVER consent to start building the video. It is merely a starting point.
You are a Director. You must collaboratively co-author a structured cinematic blueprint BEFORE running any tools to build the video. The entire visual and audio fidelity of the final production rests solely on the quality of this screenplay.
- **Drafting**: You MUST call the `format_screenplay_blueprint` tool to generate the Markdown blueprint based on the user's initial request.
- **Negotiation**: Present the exact markdown output from the tool to the user and explicitly ask for their suggestions and tweaks. DO NOT run the pipeline yet!
- **Explicit Consent Check**: You must ask: "Do you approve this screenplay, or should we make changes before I build the video?"
- ONLY call `start_draft_pipeline` AFTER the user explicitly answers "yes", "looks good", or otherwise gives unmistakable consent to proceed with building the video.

### Phase 2: Iterative Sculpting (Draft -> Critique -> Patch)
Build the video layer by layer. Never skip to the end.
- **Script & Pre-Viz (Stage 0 & 2)**: The pipeline will generate the final JSON representation based on your Blueprint.
- **Polling (MANDATORY)**: After triggering a draft or a refinement, the system places a 5-minute lock on the project to prevent parallel overwrites. You MUST use `wait_for_draft_stage` to poll until the lock clears and the stage completes.
- **The Visual Audit (Stage 3)**: The pipeline will pause automatically. You will receive a `review_dashboard_link`. This is the most critical checkpoint. Provide the link to the user and ask for their professional critique of the composition and continuity. Ask for permission to move forward.

## Directing the Soundscape
A video's soul is its audio. Browse available assets to set the tone:
- **Voices**: Use `list_voices()` to find a narrator with the right energy.
- **Music**: Use `list_bgm()` for the background rhythm.

## Visual Signature
Use `image_styles` to impose your aesthetic. Don't settle for defaults. Use `lighting: ["Chiaroscuro"]` or `themes: ["Indie Film"]` to break away from generic AI looks.

## Your Production Workflow (Strict Exec-Review-Refine)
CRITICAL INSTRUCTION: You CANNOT work in an autonomous way. You MUST work in tandem with the user's approvals, reviews, and suggestions.
The workflow is a strict state machine:
1. Ask what the user needs.
2. Build/Call the tool to execute the stage.
3. Pause and ask the user for a review of the generated assets.
4. Incorporate any changes (using `refine_draft`), but ONLY for the assets of the current stage.
5. Once the user approves, proceed to the next stage by calling `advance_draft_stage` with the next `target_stage` (up to 4 for UPSCALE).
You CANNOT refine characters if the pipeline has already moved to the Visuals stage. The inputs of the refine tools will be rejected if the draft is not at the correct state.
"""

BAASHA_PRODUCTION_SPEC = """
# Baasha Production Specification: The Director's Control Levers

This document details the high-impact parameters you can leverage to command the production. Use these strategically to move beyond "defaults" and achieve state-of-the-art results.

## 1. Parameters & Strategic Impact

### STOP: stop_at_stage (The Checkpoint System)
*   **Plain Description**: Pauses the pipeline at a specific index.
*   **Creative Leverage**:
    - **Stage 0 (STORY)**: Use this for **Script-Locking**. STOP here to audit the AI's narrative. If it's weak, rewrite it using `refine_draft` before any heavy image rendering begins.
    - **Stage 2 (PROMPTS)**: Use this for **Visual Pre-Viz**. Audit the prompts to ensure they align with your `image_styles`.
    - **Stage 3 (IMAGES)**: Use this for **Visual QA**. STOP here to check for subject consistency or "AI artifacts." Re-render bad scenes before committing to final video assembly.


### AESTHETICS: image_styles (The Aesthetic DNA)
*   **Plain Description**: A dictionary of visual tags.
*   **Creative Leverage**: Use this to create a **Unique Visual Brand**.
    - Leverage `lighting` (e.g., "Rembrandt Lighting") and `camera_lens` (e.g., "Anamorphic") to move away from a "generated" look toward a "filmed" look.
    - Locking `color_palettes` across versions ensures that even if you regen the story, the "Vibe" remains consistent.

### PIVOT: rewrite_scene_dialogue (Narrative Pivoting)
*   **Plain Description**: Replaces specific dialogue lines or voiceover in the story.
*   **Creative Leverage**: Use this for **Surgical Storytelling**. If a 10-scene draft is perfect except for the "hook" (Scene 0) or the "climax" (Scene 8), use this to pivot those specific moments. This automatically updates the lip-sync prompts for the video engine. Do NOT use this to rewrite the entire script; if the foundational narrative is wrong, use `start_draft_pipeline` to create a fresh version.

### BLUEPRINT: screenplay (The Blueprint)
*   **Plain Description**: A highly detailed, structured cinematic outline co-authored with the user.
*   **Creative Leverage**: You are PROHIBITED from accepting vague, one-sentence prompts. Before submitting any draft to the pipeline, you MUST negotiate a detailed screenplay with the user outlining the exact locations, actions, and dialogue. This locks in the narrative structure and prevents the backend LLM from making creative guesses. The depth, precision, and atmospheric quality of this screenplay DIRECTLY dictate the quality of all generated assets (characters, scenes, motion). A weak screenplay will yield generic, disjointed, poor-quality visual garbage.

### HEAL: re_render_scene_visuals & override_scene_prompts (Visual Healing)
*   **Plain Description**: Re-renders specific scenes.
*   **Creative Leverage**: Use this for **Shot Refinement**. If Scene 4 is a "hallucination," don't trash the whole project. Pass `re_render_scene_visuals: [4]` along with a highly specific `override_scene_prompts: ["Extreme close up of hands holding a golden key, bokeh background"]` to surgically fix the visual weak point.

### CAST: override_character_prompts (Cast Replacement)
*   **Plain Description**: Re-generates or swaps a character's face/reference image.
*   **Creative Leverage**: If a character looks inconsistent or wrong, pass a dictionary mapping the character's exact name to a new visual description (e.g., {"Detective Miller": "A gritty detective wearing a blue fedora, neon lighting"}) or a direct image URL.

### LINEAGE: Semantic Lineage (`get_similar_creative_ideas`)
*   **Plain Description**: Finds previous ideas that match the current topic.
*   **Creative Leverage**: Use this for **Series Continuation**. If the user asks for "Episode 2" or a "follow-up," use this tool to find the original Idea ID from Episode 1. Instead of starting a fresh project, you can continue the lineage by creating a new version of the existing idea. This ensures the engine inherits stylistic threads and previous production settings!
*   **PROTOCOL**: If you find a matching precursor, you MUST ask the user: "Director's Note: I've identified a matching precursor (ID: [uuid]). Do you want me to continue this project as a follow-up to the existing series (maintaining continuity) or start a completely fresh Idea?"

## 2. Expected Outputs & Formats

### create_idea
- **Output**: `{"idea_id": "string-uuid", "message": "..."}`
- **Verification**: Save the `idea_id`. Note that subsequent pipeline tools like `start_draft_pipeline` will return a composite `id` in the format `idea_id.version` (e.g., `uuid.1`). You can use this composite string as the `idea_id` for all other tools (`get_draft`, `refine_draft`, `wait_for_draft_stage`).

### get_draft
- **Args**: Accepts `idea_id` (uuid or uuid.version) and a mandatory `version` number.
- **Format**:
  ```json
  {
    "stage": 0,
    "version": 1,
    "title": "Neon Nights",
    "story": ["Sentence 1", "Sentence 2"],
    "images": ["url1", "url2"],
    "video_data": {"scenes": [...]},
    "character_ref": {"character_name": "url"}
  }
  ```
- **Verification**: Use this to check if `stage` matches your `stop_at_stage`. If `stage == 100`, the production task failed.

### refine_draft
- **Output**: `{"version": 1, "message": "Refinement started..."}`
- **Verification**: Call `wait_for_draft_stage` immediately after to track the patch application.

## 3. The Verification Loop
1. **Tool Invocation**: Trigger a state-mutating tool (`start_draft_pipeline`, `refine_draft`, `advance_draft_stage`).
2. **Identification**: Note the `id` (composite format `uuid.version`) AND the `target_stage` returned in the JSON response by these tools!
3. **Polling (CRITICAL)**: You MUST call `wait_for_draft_stage` using the EXACT `target_stage` returned in the previous tool's response. Do NOT guess the stage. If `start_draft_pipeline` returns `"target_stage": 0`, you MUST poll for stage 0.
4. **Inspection**: Call `get_draft` with the `idea_id` and the specific `version`.
    - **Check `story`**: Is the text exactly what you intended?
    - **Check `images`**: Does the count of images match the expected scene count?
    - **Visual Audit**: Call `get_stages_view_link` to provide the user with a dashboard to audit the story, characters, image prompts, and rendered visuals. This is mandatory before committing to further production.
    - **Check `video_data`**: Is it populated? (Required for Stage 4).
"""

# Initialize FastMCP
mcp = FastMCP(
    "Baasha",
    instructions=BAASHA_DIRECTOR_HANDBOOK + "\n\n" + BAASHA_PRODUCTION_SPEC,
)

import processor
import baasha_pipeline.chatbot as BaashaChat
from baasha_pipeline.configs import app_config as baasha_pipeline_config
from baasha_pipeline.gemini import gemini_search
from baasha_pipeline import text_embeddings
import redis

# Initialize Valkey (Redis) Client
# Make sure Valkey is running locally via Docker on port 6379
valkey_client = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)


def init_baasha():
    """Initialize Baasha environment similar to server.py:load_prod_env"""
    config = configparser.ConfigParser()
    config.read("config.ini")

    # Load secrets and configs into baasha_pipeline_config
    if "ENV" in config:
        baasha_pipeline_config.set("tts_toolkit", config["TTS"]["TOOLKIT"])
        baasha_pipeline_config.set("coqui_server", config["TTS"]["COQUI"])
        baasha_pipeline_config.set(
            "primary_chatbot", config["PREFS"]["PRIMARY_CHATBOT"]
        )

    # Setup local cache
    local_cache = os.path.join(os.path.dirname(__file__), "tmp")
    os.makedirs(local_cache, exist_ok=True)

    baasha_pipeline_config.set("tmp_path", local_cache)
    baasha_pipeline_config.set("chat_cache", local_cache)

    # Set tokens
    baasha_pipeline_auth_config = baasha_pipeline_config.get()["auth"]
    if "ELEVENLABS" in config:
        baasha_pipeline_auth_config["eleven_labs_key"] = config["ELEVENLABS"]["API_KEY"]
    if "SECRETS" in config:
        baasha_pipeline_auth_config["sarvam_ai_key"] = config["SECRETS"].get(
            "SARVAM_AI", ""
        )
        baasha_pipeline_auth_config["stability_ai_key"] = config["SECRETS"].get(
            "STABILITY_AI_KEY", ""
        )
        baasha_pipeline_auth_config["goapi_midjourney_key"] = config["SECRETS"].get(
            "GOAPI_MIDJOURNEY_KEY", ""
        )
        baasha_pipeline_auth_config["google_genai_key"] = (
            config["SECRETS"].get("GOOGLE_GENAI_KEY", "").split(", ")
        )
        baasha_pipeline_auth_config["groq_key"] = (
            config["SECRETS"].get("GROQ_KEY", "").split(", ")
        )
        baasha_pipeline_auth_config["replicate_token"] = config["SECRETS"].get(
            "REPLICATE_TOKEN", ""
        )
        baasha_pipeline_auth_config["eachlabs_ai_token"] = config["SECRETS"].get(
            "EACHLABS_AI_TOKEN", ""
        )
        baasha_pipeline_auth_config["lemon_slice_ai_token"] = config["SECRETS"].get(
            "LEMON_SLICE_AI_TOKEN", ""
        )
        baasha_pipeline_auth_config["fal_token"] = config["SECRETS"].get("FAL_KEY", "")
        baasha_pipeline_auth_config["hf_token"] = config["SECRETS"].get("HF_TOKEN", "")

    baasha_pipeline_config.set("auth", baasha_pipeline_auth_config)

    global_ctx = """You are a viral short video content creator who have cracked the formula for platforms like instagram reels, youtube shorts. With your experience you are able to
    create a short form video out of a short script applying all the learnings from your exprience. You apply your learnings in videography, cinematography and directive skills. A student is asking your input on how they can think and create like you, he is asking you to help him complete few tasks with all yours experience to learn your thinking process. Complete those task with the best of your abilities, abstractly analyse each task and figure out what the student is trying to learn from you and ace it.
    """
    baasha_pipeline_config.set("global_chatbot_ctx", global_ctx)
    logger.info("Baasha environment initialized")


# Default API URL
BAASHA_API_BASE = os.getenv("BAASHA_API_URL", "http://localhost:5000")

# Initialize on module load
init_baasha()


@mcp.tool()
def get_similar_creative_ideas(query: str) -> str:
    """
    Finds the top 3 semantically similar creative ideas from the last month that have successfully reached production.
    Use this to pull architectural inspiration or stylistic threads from recent successful productions.
    """
    try:
        response = requests.post(
            f"{BAASHA_API_BASE}/idea/similar", json={"query": query}
        )
        if response.status_code != 200:
            return f"Error from Baasha API: {response.text}"

        matches = response.json()
        if not matches:
            return "No similar successful ideas found in the last 30 days."

        res = ["### Top Similar Recent Successful Ideas (Last 30 Days):"]
        for m in matches:
            res.append(f"- **ID**: {m['id']} (Similarity: {m['similarity']})")
            res.append(f"  **Prompt**: {m['prompt']}")

        return "\n".join(res)
    except Exception as e:
        logger.error(f"Failed to fetch similar ideas from API: {e}")
        return f"Failed to connect to Baasha API at {BAASHA_API_BASE}. Error: {e}"


@mcp.tool()
async def get_episodic_memory(idea_id: str) -> str:
    """
    Retrieves the production memory of a project.
    - For series: Fetches the latest completed draft for each episode to maintain long-term continuity.
    - For single projects: Fetches the first successfully completed draft (Stage 8).
    """
    try:
        all_memories = []
        series_context = ""
        is_series = False
        breakdown: list[Any] = []

        async with httpx.AsyncClient() as client:
            # 1. Fetch Idea details to determine series status
            idea_resp = await client.get(f"{BAASHA_API_BASE}/idea/{idea_id}")
            if idea_resp.status_code == 200:
                idea_data = idea_resp.json()
                is_series = idea_data.get("is_series", False)
                breakdown = idea_data.get("episode_breakdown") or []

                if is_series:
                    series_context = (
                        f"### [SERIES] Series Context: {idea_data.get('prompt')}\n"
                    )
                    series_context += "**Episode Breakdown:**\n"
                    for i, ep in enumerate(breakdown):
                        series_context += (
                            f"{i+1}. **{ep.get('topic')}**: {ep.get('content')}\n"
                        )
                    series_context += "\n"

            def format_memory(d):
                title = d.get("title", "Untitled")
                story = d.get("story", "No story text")
                char_ref = d.get("character_ref", "No character references")
                img_desc = d.get("image_descriptions", [])
                ep_idx = d.get("episode_index")
                version = d.get("version")
                stage = d.get("stage", -1)

                ep_tag = f" [Episode {ep_idx+1}]" if ep_idx is not None else ""
                style_refs = d.get("style_reference_urls") or []

                # Safely format visuals and style refs
                visual_text = (
                    ", ".join(str(v) for v in img_desc) if img_desc else "None"
                )
                style_ref_text = (
                    ", ".join(str(s) for s in style_refs) if style_refs else "None"
                )

                return (
                    f"--- Version {version}{ep_tag}: {title} (Stage: {stage}) ---\n"
                    f"**Narrative**: {story}\n"
                    f"**Character References**: {char_ref}\n"
                    f"**Planned Visuals**: {visual_text}\n"
                    f"**Style/Audio**: Voice: {d.get('voice_id')}, Style: {d.get('style_id')}, Style Ref: {style_ref_text}\n"
                )

            if is_series:
                # Concurrent fetch for each episode's best draft
                import asyncio

                async def fetch_ep_draft(idx):
                    try:
                        resp = await client.get(
                            f"{BAASHA_API_BASE}/draft/search",
                            params={"idea_id": idea_id, "episode_index": idx},
                        )
                        if resp.status_code == 200:
                            data = resp.json()
                            # If API returned a list (old behavior), take the first item
                            if isinstance(data, list):
                                return data[0] if data else None
                            return data
                    except Exception as e:
                        logger.error(f"Error fetching ep draft {idx}: {e}")
                    return None

                # Create tasks for all episodes in breakdown
                tasks = [fetch_ep_draft(i) for i in range(len(breakdown))]
                results = await asyncio.gather(*tasks)

                for draft in results:
                    if isinstance(draft, dict):
                        mem = format_memory(draft)
                        if isinstance(mem, str):
                            all_memories.append(mem)
                        else:
                            logger.error(
                                f"format_memory returned non-string: {type(mem)}"
                            )
            else:
                # For single projects, fetch the best overall draft
                try:
                    search_resp = await client.get(
                        f"{BAASHA_API_BASE}/draft/search", params={"idea_id": idea_id}
                    )
                    if search_resp.status_code == 200:
                        data = search_resp.json()
                        if isinstance(data, list):
                            draft = data[0] if data else None
                        else:
                            draft = data

                        if isinstance(draft, dict):
                            mem = format_memory(draft)
                            if isinstance(mem, str):
                                all_memories.append(mem)
                except Exception as e:
                    logger.error(f"Error fetching project draft: {e}")

        if not all_memories and not series_context:
            return f"No completed episodic memory or series context found for Idea ID: {idea_id}"

        # Final safety check before join
        safe_memories = [str(m) for m in all_memories if m is not None]
        content = "\n\n".join(safe_memories)

        header = f"### [MEMORY] {'Series' if is_series else 'Project'} Episodic Memory: {idea_id}\n\n"

        return (
            f"{header}"
            f"{series_context}"
            "This memory contains the foundational structure and successful assets from previous work. "
            "Use it to maintain consistency and narrative flow.\n\n"
            f"{content}"
        )

    except Exception as e:
        logger.error(f"Failed to fetch simplified episodic memory: {e}")
        return f"Error retrieving memory for {idea_id}: {e}"


@mcp.tool()
def design_audio(
    sounds_list: List[Dict], audios: List[Any], timepoints: Any
) -> List[Any]:
    """Calculates optimal timing for sound effects and voiceovers.
    Use this once scenes and text are finalized to create the sound-map.
    """
    chatbot = BaashaChat.ChatInterface()
    chatbot.new_conversation()
    return processor.get_phrase_sound_effects(chatbot, sounds_list, audios, timepoints)


@mcp.tool()
async def search_web(query: str) -> str:
    """Performs a web search to look up real-world facts, current events, or specific context before creating a story.
    Returns synthesized search results from high-quality web sources.
    """
    import asyncio

    try:
        # res, err = gemini_search(query)
        # if err:
        #     return f"Search error: {err}"
        # return res

        # Initialize a temporary chatbot for the search context
        chatbot = BaashaChat.ChatInterface()
        chatbot.new_conversation()

        # Construct search link
        link = f"https://duckduckgo.com/?q={query.replace(' ', '+')}&ia=web"

        # Import summarize_page from the pipeline agent
        from baasha_pipeline.image_search_agent import summarize_page

        logger.info(f"Performing manual search-and-summarize for: {query}")

        # Offload the synchronous Playwright call to a separate thread to avoid asyncio loop conflicts
        res = await asyncio.to_thread(summarize_page, chatbot, link, query)

        return res
    except Exception as e:
        logger.error(f"Search tool failed: {e}")
        return f"Search failed: {str(e)}"


@mcp.tool()
def create_idea(
    prompt: str,
    length: int,
    user_id: str = "agent-mcp",
    is_series: bool = False,
    episode_breakdown: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """Initializes a new creative project.
    Use this first to lock your high-level conceptual pitch. Returns the `idea_id` which acts as your 'Production ID'.
    If `is_series` is True, you can provide an `episode_breakdown` which is a list of objects with 'topic' and 'content' keys.
    CRITICAL INSTRUCTION: The `prompt` and any other text inputs MUST NOT contain emojis. Emojis cause severe rendering pipeline crashes.
    """
    payload = {
        "prompt": prompt,
        "length": length,
        "user_id": user_id,
        "is_series": is_series,
    }
    if episode_breakdown:
        payload["episode_breakdown"] = episode_breakdown

    resp = requests.post(
        f"{BAASHA_API_BASE}/idea",
        json=payload,
    )
    return resp.json()


@mcp.tool()
def get_draft(idea_id: str, version: int) -> Dict[str, Any]:
    """Retrieves the full state of a specific draft version (Story, Prompts, Assets).
    Use this to inspect the production state.
    MANDATORY: You MUST call `get_stages_view_link` to provide a dashboard where the user can visually verify consistency and quality before proceeding to Stage 4.

    Args:
        idea_id: The UUID (e.g. '8e851926-...') or the composite ID.
        version: The version number to retrieve. Mandatory.
    """
    actual_idea_id = idea_id.split(".")[0] if "." in idea_id else idea_id

    url = f"{BAASHA_API_BASE}/draft/{actual_idea_id}/{version}"
    resp = requests.get(url)
    return resp.json()


@mcp.tool()
def list_voices() -> List[Dict[str, Any]]:
    """Lists all available AI voices for narration.
    Use this to pick a `voice_id` for the pipeline.
    """
    resp = requests.get(f"{BAASHA_API_BASE}/voices").json()
    filtered = list(filter(lambda x: x["tts_toolkit"] == "gemini", resp))
    return filtered


@mcp.tool()
def list_bgm(is_transition: bool = False) -> List[Dict[str, Any]]:
    """Lists available background music tracks.

    Args:
        is_transition: If True, lists tracks suitable for scene transitions.
    """
    resp = requests.get(
        f"{BAASHA_API_BASE}/bgm", params={"transition": str(is_transition).lower()}
    )
    return resp.json()


# @mcp.tool()
# def generate_moodboard(
#     topic: str, context: Optional[str] = None, num_styles: int = 3
# ) -> Dict[str, Any]:
#     """Generates a list of possible visual directions (Moodboards) for a topic.
#     Returns style suggestions and 'grid_url' mocks.
#     MANDATORY: You MUST call `get_stages_view_link` to provide the user with a dashboard to visually compare the mockups before selecting a direction.
#
#     Args:
#         topic: The broad subject of the project (e.g., 'Cyberpunk City').
#         context: Optional background info or creative constraints.
#         num_styles: Number of distinct visual directions to generate.
#     """
#     payload = {"topic": topic, "ctx": context, "num_styles": num_styles}
#     resp = requests.post(f"{BAASHA_API_BASE}/api/moodboard", json=payload)
#     return resp.json()


@mcp.tool()
def format_screenplay_blueprint(
    title: str, cast_descriptions: List[str], cinematic_sequence: List[str]
) -> str:
    """CRITICAL FIRST STEP: You MUST call this tool to formulate the Screenplay Blueprint BEFORE you ever call start_draft_pipeline.
    This tool correctly structures the screenplay into markdown so you can present it to the user for negotiation.

    Args:
        title: The working title of the video.
        cast_descriptions: List of precise descriptions for each character.
        cinematic_sequence: The scene-by-scene script. Write this in a raw, directorial flow format. Example:
            'location local biriyani shop
            Surya - avanga nagaya kudukmaru (when hes talking show the old man as well)
            camera crash zooms into his eyes.
            *eet music plays*
            cut to medium shot where we see the girl smiling'

    CRITICAL INSTRUCTION: Do NOT include any emojis in `title`, `cast_descriptions`, or `cinematic_sequence`. Emojis crash the rendering engine.
    """
    blueprint = f"# 🎬 Screenplay Blueprint: {title}\n\n"

    blueprint += "### 🎭 Cast & Costumes\n"
    for cast in cast_descriptions:
        blueprint += f"- {cast}\n"

    blueprint += "\n### 🎥 Cinematic Sequence\n"
    for i, scene in enumerate(cinematic_sequence):
        blueprint += f"**Scene {i+1}**: {scene}\n\n"

    blueprint += "---\n"
    blueprint += "🚨 **AGENT INTERNAL INSTRUCTION**: Present this EXACT markdown block to the user. Ask them: 'Do you approve this screenplay, or should we make changes before I build the video?' DO NOT proceed until they explicitly consent."

    return blueprint


@mcp.tool()
def start_draft_pipeline(
    idea_id: str,
    version_id: int,
    voice_id: str,
    screenplay: str,
    user_consent_proof: str,
    character_ref: Optional[Dict] = None,
    episode_index: Optional[int] = None,
) -> Dict[str, Any]:
    """Executes the video generation pipeline to establish the foundational draft.
    As the Creative Director, use this to bring your vision to life.
    If this is part of a series, specify the `episode_index`.
    CRITICAL: This applies a project lock. You MUST call `wait_for_draft_stage` immediately after to poll for completion.
    CRITICAL: You are NOT autonomous. You must work in a strict exec-review-refine loop with the user. You CANNOT advance stages without explicit user approval of the current stage's assets.
    CRITICAL INSTRUCTION: The `screenplay` and other text fields MUST NOT contain emojis. Emojis cause severe rendering crashes.

    Args:
        idea_id: Either the UUID or the composite 'idea_id.version'.
        version_id: Mandatory version tracking (e.g., 1 for your first cut).
        screenplay: A highly detailed, structured cinematic blueprint co-authored with the user.
            MUST be a multi-line text block. Do NOT pass a single generic sentence.
            Write it in a raw, directorial flow format. Example:
            'location local biriyani shop
            Surya - avanga nagaya kudukmaru (when hes talking show the old man as well)
            camera crash zooms into his eyes.
            *eet music plays*
            cut to medium shot where we see the girl smiling'
        user_consent_proof: Quote the exact text where the user explicitly approved starting this draft.
        voice_id: Pick an audial tone from `list_voices()`.
        use_image_grid: Enable for high visual consistency.
        make_image_layers: Enable for 3D Parallax effect.
        image_styles: Define granular aesthetics (e.g., {"lighting": ["Neon Noir"], "camera_lens": ["Anamorphic"]}).
    """
    actual_idea_id = idea_id.split(".")[0] if "." in idea_id else idea_id

    # Map new inputs to legacy API parameters
    api_content_type = "cinematic micro-drama"
    api_story = screenplay

    # map defaults removed from input
    stop_at_stage = 0
    background_music_id = None
    bgm_name = None
    use_image_grid = True
    make_image_layers = False
    use_character_refs = True
    judge_images = False
    gen_video = False
    add_phrase_sounds = False
    add_search_assets = False
    image_styles = None
    conversation = None
    image_prompts = None
    image_urls = None
    style_reference_urls = [
        "https://tempp.us-east-1.linodeobjects.com/Screenshot%20from%202026-04-30%2004-59-08.png"
    ]

    # Extract all local variables to build the payload
    # We remove parameters that are handled specially or aren't part of the direct API payload
    local_vars = locals().copy()
    for k in [
        "payload",
        "idea_id",
        "version_id",
        "screenplay",
        "user_consent_proof",
        "actual_idea_id",
        "api_content_type",
        "api_story",
        "local_vars",
    ]:
        local_vars.pop(k, None)

    payload = {k: v for k, v in local_vars.items() if v is not None}

    payload["idea_id"] = actual_idea_id
    payload["version_id"] = version_id
    payload["content_type"] = api_content_type
    payload["story"] = api_story

    # Directorial Defaults
    payload.setdefault("image_engine", "fal/gpt")
    payload.setdefault("video_engine", "start_end_collage_framing")
    payload.setdefault("avatar_engine", "lemon_slice")
    payload.setdefault("tts_toolkit", "eleven_labs")
    payload.setdefault("prompt_overrides", "director_cut")

    resp = requests.post(f"{BAASHA_API_BASE}/draft", json=payload)
    if resp.status_code == 423:
        return {
            "error": f"Project {actual_idea_id} is currently locked by the API processing a previous request. You MUST poll using `wait_for_draft_stage` until the lock clears."
        }

    resp_data = resp.json()
    resp_data["review_dashboard_link"] = get_stages_view_link(
        actual_idea_id, version_id
    )
    return resp_data


@mcp.tool()
def refine_draft(
    idea_id: str,
    version_id: int,
    user_consent_proof: str,
    rewrite_scene_dialogue: Optional[Dict[str, str]] = None,
    re_render_scene_visuals: Optional[List[int]] = None,
    override_scene_prompts: Optional[List[str]] = None,
    override_character_prompts: Optional[Dict[str, str]] = None,
    self_heal: bool = False,
    voice_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Surgically patches a specific draft version.
    Use this to incorporate user review changes before advancing to the next stage.
    CRITICAL: You can ONLY refine assets that correspond to the current stage of the draft.
    - Characters can ONLY be edited when the draft is paused at Stage 1 (Cast).
    - Grid Visuals can ONLY be re-rendered when the draft is paused at Stage 3 (Visuals).
    CRITICAL: This applies a project lock. You MUST call `wait_for_draft_stage` immediately after to poll for completion.
    CRITICAL INSTRUCTION: Text inputs (dialogue, prompts) MUST NOT contain emojis. Emojis cause severe rendering pipeline crashes.

    Args:
        idea_id: Either the UUID or the composite 'idea_id.version'.
        version_id: The version you are fixing.
        user_consent_proof: Quote the exact text where the user approved these specific refinements.
        rewrite_scene_dialogue: Dictionary mapping scene index to new voiceover/dialogue (e.g., {"0": "New hook line"}).
        re_render_scene_visuals: List of scene numbers to re-render (e.g., [4, 7] to fix bad shots).
        override_scene_prompts: Explicit new prompts for the scenes you are re-rendering.
        override_character_prompts: Dictionary mapping a character's exact name to a text description to re-generate them.
        self_heal: Command the engine to auto-fix visually flagged or failed assets.
        voice_id: Pivot the narrator voice mid-production.
    """
    actual_idea_id = idea_id.split(".")[0] if "." in idea_id else idea_id

    # Validation & Stage Determinism Checks
    draft_status_resp = requests.get(
        f"{BAASHA_API_BASE}/draft/{actual_idea_id}/{version_id}"
    )
    if draft_status_resp.status_code == 200:
        current_stage = draft_status_resp.json().get("stage", -1)
        if override_character_prompts and current_stage != 1:
            return {
                "error": f"Refinement Rejected: You can only edit characters when the draft is paused at Stage 1 (Cast). The draft is currently at Stage {current_stage}."
            }
        if (re_render_scene_visuals or override_scene_prompts) and current_stage != 3:
            return {
                "error": f"Refinement Rejected: You can only re-render grid visuals when the draft is paused at Stage 3 (Visuals). The draft is currently at Stage {current_stage}."
            }
    if re_render_scene_visuals and override_scene_prompts:
        if len(re_render_scene_visuals) != len(override_scene_prompts):
            return {
                "error": f"Validation Failed: re_render_scene_visuals has {len(re_render_scene_visuals)} items, but override_scene_prompts has {len(override_scene_prompts)}. They must match exactly."
            }

    # Map defaults removed from input
    edit_inplace = True
    convert_to_video = None
    bgm_name = None
    gen_video = False

    # Map creator-friendly keys back to internal API schema
    edit_story_sentence = rewrite_scene_dialogue
    regen_images = re_render_scene_visuals
    regen_image_prompts = override_scene_prompts
    character_ref = override_character_prompts

    payload = {
        k: v
        for k, v in locals().items()
        if v is not None
        and k
        not in [
            "payload",
            "idea_id",
            "version_id",
            "actual_idea_id",
            "rewrite_scene_dialogue",
            "re_render_scene_visuals",
            "override_scene_prompts",
            "override_character_prompts",
            "draft_status_resp",
            "current_stage",
        ]
    }
    payload["idea_id"] = actual_idea_id
    payload["version_id"] = version_id

    payload.setdefault("image_engine", "fal/gpt")
    payload.setdefault("video_engine", "start_end_collage_framing")

    resp = requests.patch(f"{BAASHA_API_BASE}/draft", json=payload)
    if resp.status_code == 423:
        return {
            "error": f"Project {actual_idea_id} is currently locked by the API processing a previous request. You MUST poll using `wait_for_draft_stage` until the lock clears."
        }
    return resp.json()


@mcp.tool()
def advance_draft_stage(
    idea_id: str, version_id: int, target_stage: int, user_consent_proof: str
) -> Dict[str, Any]:
    """Advances a paused draft to the next stage in the pipeline.
    Call this ONLY after the user has reviewed and approved the assets from the current stage.
    CRITICAL: This applies a project lock. You MUST call `wait_for_draft_stage` immediately after to poll for completion.

    Args:
        idea_id: Either the UUID or the composite 'idea_id.version'.
        version_id: The version you are advancing.
        target_stage: The stage to process up to and then stop. (Max: 4 for final high-fidelity upscale).
        user_consent_proof: Quote the exact text where the user approved advancing to this specific stage.
    """
    if target_stage > 4:
        return {
            "error": f"Validation Failed: target_stage cannot exceed 4. You requested {target_stage}."
        }

    actual_idea_id = idea_id.split(".")[0] if "." in idea_id else idea_id

    payload = {
        "idea_id": actual_idea_id,
        "version_id": version_id,
        "stop_at_stage": target_stage,
    }

    # Directorial Defaults
    payload.setdefault("image_engine", "fal/gpt")
    payload.setdefault("video_engine", "start_end_collage_framing")
    payload.setdefault("avatar_engine", "lemon_slice")
    payload.setdefault("tts_toolkit", "eleven_labs")
    payload.setdefault("prompt_overrides", "director_cut")

    # Boolean Pipeline Configurations
    payload.setdefault("use_image_grid", True)
    payload.setdefault("make_image_layers", False)
    payload.setdefault("use_character_refs", True)
    payload.setdefault("judge_images", False)
    payload.setdefault("gen_video", False)
    payload.setdefault("add_phrase_sounds", False)
    payload.setdefault("add_search_assets", False)

    resp = requests.post(f"{BAASHA_API_BASE}/draft", json=payload)
    if resp.status_code == 423:
        return {
            "error": f"Project {actual_idea_id} is currently locked by the API processing a previous request. You MUST poll using `wait_for_draft_stage` until the lock clears."
        }

    return resp.json()


def _format_draft_for_agent(draft: dict) -> dict:
    """Formats the raw DB draft object into a concise, agent-parseable summary."""
    try:
        vd = draft.get("video_data")
        video_data = json.loads(vd) if isinstance(vd, str) else (vd or {})
    except Exception:
        video_data = {}

    story = video_data.get("text", [])

    img_descs = draft.get("image_descriptions") or []
    image_prompts = [
        d[0] if isinstance(d, (list, tuple)) and len(d) > 0 else d for d in img_descs
    ]

    try:
        characters = json.loads(draft.get("character_ref") or "[]")
    except Exception:
        characters = []

    scenes = []
    for i in range(max(len(story), len(image_prompts))):
        scenes.append(
            {
                "scene_number": i + 1,
                "dialogue": story[i] if i < len(story) else None,
                "image_prompt": image_prompts[i] if i < len(image_prompts) else None,
            }
        )

    stage = draft.get("stage", -1)

    possible_actions = [
        "Present the dashboard link (get_stages_view_link) to the user for approval.",
        "If approved, call advance_draft_stage to move to the next stage.",
    ]
    if stage == 0:
        possible_actions.append(
            "If user requests changes to the story, call refine_draft with rewrite_scene_dialogue."
        )
    elif stage == 1:
        possible_actions.append(
            "If user requests changes to characters, call refine_draft with override_character_prompts."
        )
    elif stage == 2:
        possible_actions.append(
            "If user requests changes to scene descriptions, call refine_draft with override_scene_prompts."
        )
    elif stage == 3:
        possible_actions.append(
            "If user rejects specific images, call refine_draft with re_render_scene_visuals and override_scene_prompts."
        )

    return {
        "idea_id": draft.get("idea_id"),
        "version": draft.get("version"),
        "stage": stage,
        "voice_id": draft.get("voice_id"),
        "style_id": draft.get("style_id"),
        "characters": characters,
        "scenes": scenes,
        "possible_next_actions": possible_actions,
    }


@mcp.tool()
def wait_for_draft_stage(idea_id: str, target_stage: int) -> Dict[str, Any]:
    """Polls the draft status until it reaches the target stage or timeouts (5 mins).
    CRITICAL: You MUST use the exact `target_stage` value returned in the response of `start_draft_pipeline`, `refine_draft`, or `advance_draft_stage`. Do not guess this value!
    CRITICAL: Generation tasks are heavy. If this tool times out, you MUST retry calling it up to 3 times before reporting a failure to the user.
    Stages: 0=STORY, 1=CAST, 2=PROMPTS, 3=IMAGES, 4=UPSCALE, 5=AUDIO/CONFIG.

    Args:
        idea_id: Either the UUID or the composite 'idea_id.version'.
    """
    actual_idea_id = idea_id.split(".")[0] if "." in idea_id else idea_id
    version = int(idea_id.split(".")[1]) if "." in idea_id else None

    # let the DB patch
    time.sleep(5)

    timeout_seconds = 300
    start_time = time.time()
    while time.time() - start_time < timeout_seconds:
        url = f"{BAASHA_API_BASE}/draft/{actual_idea_id}"
        if version:
            url += f"/{version}"

        resp = requests.get(url)
        if resp.status_code == 200:
            draft = resp.json()
            current_stage = draft.get("stage", -1)
            if current_stage >= target_stage:
                return {
                    "status": "success",
                    "stage": current_stage,
                    "draft_summary": _format_draft_for_agent(draft),
                }
            if current_stage == 100:  # DRAFT_FAILED
                return {
                    "status": "failed",
                    "stage": current_stage,
                    "draft_summary": _format_draft_for_agent(draft),
                }

        time.sleep(5)

    return {
        "status": "timeout",
        "message": f"Draft did not reach stage {target_stage} within {timeout_seconds}s. This is normal for heavy rendering tasks. CRITICAL: You MUST retry calling wait_for_draft_stage (up to 3 times) to continue polling.",
    }


@mcp.tool()
def get_preview_link(idea_id: str, version_id: Optional[int] = None) -> Dict[str, Any]:
    """Generates a web preview link for the draft.
    Only works if the draft has reached Stage 4 (AUDIO/CONFIG).

    Args:
        idea_id: Either the UUID or the composite 'idea_id.version'.
        version_id: Optional explicit version ID.
    """
    actual_idea_id = idea_id.split(".")[0] if "." in idea_id else idea_id
    version = version_id or (int(idea_id.split(".")[1]) if "." in idea_id else None)

    url = f"{BAASHA_API_BASE}/draft/{actual_idea_id}"
    if version:
        url += f"/{version}"

    resp = requests.get(url)
    if resp.status_code != 200:
        return {"error": f"Failed to fetch draft: {resp.text}"}

    draft = resp.json()
    config_url = draft.get("remotion_config")

    if not config_url:
        return {
            "error": "Draft is not ready for preview. Ensure it has reached Stage 4."
        }

    # b64 encode the config URL as requested: c=btoa(link)
    b64_config = base64.b64encode(config_url.encode()).decode()

    # Base URL updated as per user request
    preview_url = f"http://173.255.237.181:3001/?c={b64_config}"

    return {
        "preview_url": preview_url,
        "message": "Send this link to the user to preview the video assets and layout.",
    }


@mcp.tool()
def get_stages_view_link(idea_id: str, version: int = 1) -> str:
    """Returns a web link to view all production stages, assets, and progress for a specific draft.
    As Creative Director, you must provide this link to the user so they can audit the story, characters, image prompts, and rendered visuals.

    Args:
        idea_id: The UUID or composite 'idea_id.version'.
        version: The version number (default 1).
    """
    actual_idea_id = idea_id.split(".")[0] if "." in idea_id else idea_id
    actual_version = version
    if "." in idea_id and version == 1:
        try:
            actual_version = int(idea_id.split(".")[1])
        except:
            pass

    # Using the production IP for the viewer link
    base_url = "http://173.255.237.181:5000"
    return f"{base_url}/stages?idea_id={actual_idea_id}&version={actual_version}"


# @mcp.tool()
# def view_images(image_urls: List[str]) -> Any:
#     """MANDATORY: Downloads and prepares visual assets for the provided URLs so you can 'see' them.
#     As Creative Director, you are REQUIRED to call this tool to visually audit every set of generated images before approving them.
#     You cannot critique quality or stylistic consistency without 'seeing' the assets through this tool.
#
#     Args:
#         image_urls: List of image URLs to fetch.
#     """
#     contents = []
#     contents.append({"type": "text", "text": f"Here are the requested images:"})
#
#     return contents
#
#     for url in image_urls:
#         try:
#             # Fetch image bytes
#             resp = requests.get(url, timeout=20)
#             if resp.status_code == 200:
#                 img = PilImage.open(io.BytesIO(resp.content))
#                 img.thumbnail((768, 768))
#
#                 if img.mode in ("RGBA", "P"):
#                     img = img.convert("RGB")
#
#                 buffer = io.BytesIO()
#                 img.save(buffer, format="JPEG", quality=80)
#                 b64_data = base64.b64encode(buffer.getvalue()).decode()
#
#                 # Return as a plain dictionary to ensure clean JSON serialization by FastMCP
#                 contents.append(
#                     {"type": "image", "data": b64_data, "mimeType": "image/jpeg"}
#                 )
#             else:
#                 contents.append(
#                     {
#                         "type": "text",
#                         "text": f"Failed to fetch {url}: Status {resp.status_code}",
#                     }
#                 )
#         except Exception as e:
#             contents.append({"type": "text", "text": f"Error fetching {url}: {str(e)}"})
#
#     return contents


if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0")
