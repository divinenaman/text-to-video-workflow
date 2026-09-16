# API Documentation

## Overview

This API provides a comprehensive suite of tools for idea management, draft creation, and multimedia content generation, including stories, images, audio, and video. It allows users to manage creative ideas, develop them into detailed drafts through multiple stages, and customize various aspects like voice, music, and visual styles. The API supports asynchronous processing for content generation tasks and offers webhook notifications for long-running processes like video rendering.

**Key Features:**

*   **Idea Management:** Create, retrieve, and delete ideas.
*   **Drafting Workflow:** Iterate on ideas by creating and patching drafts. Draft generation involves multiple stages, from story generation to final video rendering.
*   **Rich Content Generation:** Generate stories, image prompts, images, text-to-speech audio, and video configurations.
*   **Customization:**
    *   Select voices, background music, and visual styles.
    *   Provide character references for image generation.
    *   Fine-tune generated content through patching operations.
*   **Asynchronous Operations:** Heavy tasks like content generation and video rendering are performed in the background.
*   **Webhook Support:** Get notifications for completed video generation tasks.
*   **Resource Management:** Manage libraries of voices, background music, and styles.

## Idea Resource

Manages creative ideas, which serve as the starting point for draft creation.

#### `GET /idea`

*   **Description**: Retrieves all ideas associated with a `user_id` if provided, otherwise, this endpoint requires an `idea_id` specified in the path (see `GET /idea/<idea_id>`).
*   **Query Parameters**:
    *   `user_id` (string, optional): If provided, returns all ideas associated with this user ID.
*   **Response (Success - 200 OK - if `user_id` provided)**:
    ```json
    [
        {
            "id": "string",
            "prompt": "string",
            "length": "integer",
            "user_id": "string"
        }
    ]
    ```
*   **Response (Error - 400 Bad Request - if no `idea_id` in path and no `user_id` in query)**:
    ```json
    {
        "error": "An idea_id in the request path or a user_id as a query param must be specified to fetch an Idea"
    }
    ```

#### `GET /idea/<idea_id>`

*   **Description**: Retrieves a specific idea by its ID.
*   **Path Parameters**:
    *   `idea_id` (string, required): The unique identifier for the idea.
*   **Response (Success - 200 OK)**:
    ```json
    {
        "id": "string",
        "prompt": "string",
        "length": "integer",
        "user_id": "string"
    }
    ```
*   **Response (Error - 404 Not Found)**:
    ```json
    {
        "error": "Idea not found"
    }
    ```

#### `POST /idea`

*   **Description**: Creates a new idea.
*   **Request Body (JSON)**:
    *   `prompt` (string, required): The prompt for the idea. Must be under 200 characters.
    *   `length` (integer, required): The desired length of the idea (e.g., number of scenes, duration indicator).
    *   `user_id` (string, optional, default: "unregistered"): The user ID associated with the idea.
*   **Response (Success - 201 Created)**:
    ```json
    {
        "message": "Idea created successfully",
        "id": "generated_idea_id"
    }
    ```
*   **Response (Error - 400 Bad Request)**:
    ```json
    {
        "message": "Both prompt and length are required"
    }
    ```

#### `DELETE /idea/<idea_id>`

*   **Description**: Deletes an idea by its ID.
*   **Path Parameters**:
    *   `idea_id` (string, required): The unique identifier for the idea to be deleted.
*   **Response (Success - 204 No Content)**
*   **Response (Error - 404 Not Found)**:
    ```json
    {
        "message": "Idea not found"
    }
    ```

## Draft Resource

Manages drafts, which are developed from ideas and go through various content generation stages.

#### Draft Stages

The `stage` field in a Draft indicates its current point in the generation pipeline.
*   `STORY_GEN` (Integer: `0`): Story generation stage.
*   `CHARACTER_REF_GEN` (Integer: `1`): Character reference generation stage.
*   `IMAGE_PROMPT_GEN` (Integer: `2`): Image prompt generation stage.
*   `IMAGE_GEN` (Integer: `3`): Image generation stage. (Technically, Audio Gen and Video Config Gen happen before this stage in the code, but image gen is a distinct step of asset creation)
*   `AUDIO_GEN_VIDEO_CONFIG_GEN` (Integer: `4`): Audio generation and video configuration generation stage.
*   `VIDEO_GEN_STARTED` (Integer: `5`): Video generation started stage.
*   `VIDEO_GEN_PROCESSING` (Integer: `6`): Video generation processing stage.
*   `VIDEO_GEN_FAILED` (Integer: `7`): Video generation failed stage.
*   `VIDEO_GENERATED` (Integer: `8`): Video generated stage.

A `stage` value of `-1` typically indicates initialization or pre-story generation.

#### `GET /draft/<idea_id>`

*   **Description**: Retrieves the latest version of a draft for a given idea ID.
*   **Path Parameters**:
    *   `idea_id` (string, required): The unique identifier for the idea.
*   **Response (Success - 200 OK)**:
    *   A JSON object representing the Draft. Key fields include:
        *   `idea_id` (string)
        *   `version` (integer)
        *   `story` (string)
        *   `title` (string)
        *   `image_descriptions` (list of lists/strings)
        *   `background_music_id` (integer)
        *   `voice_id` (string)
        *   `style_id` (string)
        *   `video_data` (stringified JSON): Contains detailed generated assets like image URLs, audio URLs, text arrays, timing information, etc. The structure of this JSON is dynamic based on the generation process.
        *   `character_ref` (stringified JSON): Contains character names and reference image URLs.
        *   `remotion_config` (string URL): Link to the video rendering configuration.
        *   `generated_video` (string URL): Link to the final rendered video.
        *   `stage` (integer): Current generation stage (see Draft Stages).
        *   Other metadata.
*   **Response (Error - 404 Not Found)**:
    ```json
    {
        "message": "No drafts found for idea <idea_id>"
    }
    ```

#### `GET /draft/<idea_id>/<version_id>`

*   **Description**: Retrieves a specific draft version for a given idea ID.
*   **Path Parameters**:
    *   `idea_id` (string, required): The unique identifier for the idea.
    *   `version_id` (integer, required): The version number of the draft.
*   **Response (Success - 200 OK)**:
    *   A JSON object representing the Draft (see `GET /draft/<idea_id>` for structure).
*   **Response (Error - 404 Not Found)**:
    ```json
    {
        "message": "Draft version <version_id> for idea <idea_id> not found"
    }
    ```

#### `POST /draft`

*   **Description**: Creates a new draft for a given idea ID or updates an existing draft if `version_id` is provided. It triggers a background process to generate content for the draft based on the provided parameters and the parent idea.
*   **Request Body (JSON)**:
    *   `idea_id` (string, required): The unique identifier for the idea to create/update a draft for.
    *   `version_id` (integer, optional): If provided, the API attempts to update the specified draft version by re-processing it with the new parameters. If not provided, the API increments from the latest existing version or creates version 1 if no drafts exist.
    *   `story` (string, optional): Initial story text for the draft. If not provided, it may be generated from the idea's prompt or `video_source`.
    *   `video_source` (string, optional): URL of a video (e.g., Instagram Reel) to extract audio and story from. If provided, this can be used to initialize the `story`.
    *   `title` (string, optional): Title for the draft. If not provided, it may be generated.
    *   `image_descriptors` (list of strings/lists, optional): List of initial image descriptors/prompts for the draft.
    *   `background_music_id` (integer, optional): ID of the background music to use for the draft.
    *   `voice_id` (string, optional): ID of the voice to use for Text-to-Speech.
    *   `style_id` (string, optional): ID of the visual style to apply to the draft.
    *   `guidance` (string, optional): Additional guidance for the AI during story or content generation.
    *   `image_count` (integer, optional, default: 10): Target number of images to generate if not explicitly defined by story length or other parameters.
    *   `image_styles` (dict, optional): A dictionary to append additional style keywords to image prompts. Example: `{"themes": ["cyberpunk"], "lighting": ["neon"]}`. See `StyleData` structure below.
    *   `image_prompts` (list of strings, optional): Explicit list of image prompts to use.
    *   `image_urls` (list of strings, optional): Pre-generated image URLs to use, bypassing image generation for these.
    *   `bgm_name` (string, optional): Name of the background music. Can be used instead of `background_music_id`.
    *   `tts_toolkit` (string, optional, default: "gtts"): Specifies the Text-to-Speech toolkit (e.g., "gtts", "eleven_labs", "coqui").
    *   `image_engine` (string, optional): Specifies the image generation model/engine (e.g., "goapi_midjourney").
    *   `video_engine` (string, optional): Specifies the video generation model/engine.
    *   `gen_video` (boolean, optional, default: `False`): If `True`, automatically triggers video rendering after draft generation.
    *   `character_ref` (dict, optional): A dictionary mapping character names to image URLs for reference during image generation. Example: `{"hero": "http://example.com/hero.jpg", "narrator_avatar": "http://example.com/narrator.jpg"}`.
    *   `stop_at_stage` (integer, optional, default: `VIDEO_GENERATED` (8)): Specifies the draft generation stage at which the background process should stop. See `Draft Stages`.
*   **Response (Success - 201 Created/Updated)**:
    ```json
    {
        "message": "Draft version <version> for idea <idea_id> created/updated successfully",
        "id": "<idea_id>.<version>"
    }
    ```
*   **Response (Error - 400/404)**:
    *   If `idea_id` is not found or other validation errors occur.
    ```json
    {
        "message": "Error message detailing the issue"
    }
    ```
*   **Nuances**:
    *   This endpoint initiates a background task. The response indicates acceptance, not completion.
    *   If `story` is not provided, the system attempts to generate one based on `idea_prompt`, `video_source`, or `guidance`.
    *   The `video_data` field of the draft will be populated incrementally by the background process.

#### `PATCH /draft`

*   **Description**: Updates an existing draft with new data. Triggers a background process to apply the patches. It allows for modifying various aspects of a draft, such as the story, images, audio, and styling. The updates can either be applied to the current draft version or create a new draft version, depending on the `edit_inplace` parameter.
*   **Request Body (JSON)**:
    *   `idea_id` (string, required): The unique identifier of the idea whose draft is to be patched.
    *   `version_id` (integer, required): The version number of the draft to patch.
    *   `edit_inplace` (boolean, optional, default: `False`):
        *   If `True`, applies edits directly to the specified `version_id`.
        *   If `False`, creates a new draft version with the patches applied, incrementing from the latest version.
    *   `story` (string, optional): Updated story text for the draft. If provided, the story is split into sentences. Audio for all sentences of the new story will be regenerated.
    *   `edit_story_sentence` (dict, optional): A dictionary where keys are 0-indexed sentence indices (as strings or integers) and values are the new sentence text. This allows for editing specific sentences. Audio for edited sentences will be regenerated.
    *   `gen_audio` (list of integers, optional): A list of 0-indexed sentence indices for which to regenerate audio. Useful if the text hasn't changed but audio needs re-generation with current voice/TTS settings. Overridden if `story` is patched (all audio regenerated) or used in conjunction with `edit_story_sentence`.
    *   `image_urls` (list of strings, optional): A list of image URLs to replace existing images. The order corresponds to the image sequence in the draft.
    *   `bgm_name` (string, optional): The name of the background music to use. The API will attempt to find a matching BGM.
    *   `style_id` (string, optional): The ID of a style to apply. This will update image descriptions/prompts with the selected style and may trigger image regeneration if `regen_images` is also used.
    *   `character_ref` (dict, optional): A dictionary mapping character names to image URLs (e.g., `{"character_name": "url", "narrator_avatar": "url"}`). Updates or adds character references. If `narrator_avatar` is changed, its video/audio might be regenerated.
    *   `regen_images` (list of integers, optional): A list of 1-indexed image positions to regenerate.
    *   `regen_image_prompts` (list of strings, optional): A list of new prompts for images specified in `regen_images`. Order corresponds to `regen_images`. If a prompt is an empty string, the API will attempt to regenerate a prompt for that image based on the story/sentence.
    *   `upscale_image` (boolean, optional, default: `False`): If `True`, all images in the draft will be upscaled.
    *   `voice_id` (string, optional): The ID of the voice to use for TTS. Updates the voice for subsequent audio generation.
    *   `ui_order` (dict, optional): A frontend-defined structure to customize the presentation order of UI elements (image, audio, text).
    *   `ai_edit_ui` (string, optional): A natural language instruction for editing the UI configuration (e.g., "make the first image appear before the text").
    *   `toggle_ai_edit` (list of booleans, optional): Enables/disables specific AI edits applied via `ai_edit_ui`. Corresponds to the order of applied AI edits.
    *   `regen_video_conf` (string, optional): If provided (e.g., a version string like "v2"), regenerates the video configuration.
    *   `self_heal` (boolean, optional, default: `False`): If `True`, attempts to regenerate images that previously failed during generation or patching. Checks `image_gen_errors` and `image_gen_patch_errors` in `video_data`.
    *   `convert_to_video` (list of dicts, optional): Converts specified images to short video clips. Each dictionary in the list should have:
        *   `pos` (integer, required): 1-indexed position of the image to convert.
        *   `prompt` (string, required): Motion prompt for the image-to-video conversion.
    *   `image_engine` (string, optional): Image generation engine to use for `regen_images`.
    *   `avatar_engine` (string, optional): Engine for narrator avatar generation (e.g., "replicate_video_retalking") if `character_ref` updates `narrator_avatar`.
    *   `video_engine` (string, optional): Video engine for `convert_to_video` (e.g., "goapi_wanx", "gooey_lipsync").
    *   `tts_toolkit` (string, optional): TTS toolkit to use for audio regeneration if not determined by `voice_id`.
    *   `image_styles` (dict, optional): Used during image prompt regeneration if `style_id` is not provided. See `POST /draft` for structure.
    *   `gen_video` (boolean, optional, default: `False`): If `True`, triggers video rendering after patches are applied and processed.
*   **Response (Success - 200 OK)**:
    ```json
    {
        "version": "new_or_updated_version_id"
    }
    ```
*   **Response (Error - 400/404)**:
    ```json
    {
        "message": "Error message detailing the issue"
    }
    ```
*   **Notes & Nuances**:
    *   This endpoint initiates a background task. The response indicates acceptance.
    *   Only include parameters for aspects you want to change.
    *   `edit_inplace=False` (default) is safer as it preserves the original draft version.
    *   Regeneration tasks (images, audio, video config) can be time-consuming.
    *   `video_data` (JSON string in the Draft model) stores all generated assets and metadata. Patch operations modify this data.
    *   If `story` is patched, `args.gen_audio` is internally set to regenerate audio for all new sentences. If `story` is not patched, `gen_audio` can target specific sentences.
    *   `self_heal` will attempt to fix images marked with errors in `video_data.image_gen_errors` or `video_data.image_gen_patch_errors` unless `regen_images` explicitly overrides this for those positions.

#### `StyleData` Structure (for `image_styles` parameter)

This structure helps in guiding AI for image prompt generation or stylization.
```json
{
    "themes": ["string"],         // e.g., "fantasy", "sci-fi"
    "emotions": ["string"],       // e.g., "joyful", "mysterious"
    "camera_angles": ["string"],  // e.g., "low angle", "bird's eye view"
    "camera_lens": ["string"],    // e.g., "wide angle", "macro"
    "lighting": ["string"],       // e.g., "soft light", "dramatic lighting"
    "color_palettes": ["string"]  // e.g., "monochromatic blue", "vibrant sunset"
}
```

## Preview Resource

Provides access to draft data, typically for non-editable views.

#### `GET /preview/<idea_id>`

*   **Description**: Retrieves the latest processed draft for a given idea ID for preview. A draft is considered "processed" when it has reached a stage suitable for preview (e.g., essential assets generated).
*   **Path Parameters**:
    *   `idea_id` (string, required): The unique identifier for the idea.
*   **Response (Success - 200 OK)**:
    *   JSON object of the Draft (if processed).
*   **Response (Accepted - 202 Accepted)**:
    ```json
    {
        "message": "Draft version latest for idea <idea_id> is not ready for preview"
    }
    ```
    (If the latest draft is not yet processed for preview)

#### `GET /preview/<idea_id>/<version_id>`

*   **Description**: Retrieves a specific processed draft version for a given idea ID for preview.
*   **Path Parameters**:
    *   `idea_id` (string, required): The unique identifier for the idea.
    *   `version_id` (integer, required): The version number of the draft.
*   **Response (Success - 200 OK)**:
    *   JSON object of the Draft (if processed).
*   **Response (Accepted - 202 Accepted)**:
    ```json
    {
        "message": "Draft version <version_id> for idea <idea_id> is not ready for preview"
    }
    ```
    (If the specified draft version is not yet processed for preview)

## Voice Resource

Manages voice samples used for Text-to-Speech (TTS) generation.

#### `GET /voices`

*   **Description**: Retrieves all available voice samples.
*   **Response (Success - 200 OK)**:
    ```json
    [
        {
            "id": "string", // Voice provider's ID, e.g., ElevenLabs voice_id
            "voice_name": "string",
            "voice_sample": "string_url_or_base64", // URL to voice sample or base64 audio data
            "tags": "string"_or_dict, // e.g., "{\"accent\": \"british\", \"gender\": \"female\"}"
            "description": "string",
            "tts_toolkit": "string" // e.g., "eleven_labs", "gtts"
        }
    ]
    ```

#### `GET /voices/<voice_id>`

*   **Description**: Retrieves a specific voice sample by its ID.
*   **Path Parameters**:
    *   `voice_id` (string, required): The unique identifier for the voice sample.
*   **Response (Success - 200 OK)**:
    ```json
    {
        "id": "string",
        "voice_name": "string",
        "voice_sample": "string_url_or_base64",
        "tags": "string_or_dict",
        "description": "string",
        "tts_toolkit": "string"
    }
    ```

#### `POST /voices`

*   **Description**: Creates a new voice sample.
*   **Request Body (JSON)**:
    *   `voice_id` (string, required): The unique identifier for the voice (often from the TTS provider).
    *   `voice_name` (string, required): The display name of the voice.
    *   `voice_sample` (string, required): A sample of the voice. Can be a URL to an audio file or a special `baasha_file:<path>` indicator.
    *   `tags` (string, optional): Tags associated with the voice sample (e.g., "calm, male, narrator").
    *   `description` (string, optional): A description of the voice sample.
    *   `tts_toolkit` (string, required): The TTS toolkit used for this voice (e.g., "eleven_labs", "gtts", "coqui").
*   **Response (Success - 201 Created)**:
    *   The created Voice object.
*   **Nuances**:
    *   The system preloads voices from ElevenLabs if configured.

#### `DELETE /voices/<voice_id>`

*   **Description**: Deletes a voice sample by its ID.
*   **Path Parameters**:
    *   `voice_id` (string, required): The unique identifier for the voice sample to be deleted.
*   **Response (Success - 200 OK)**:
    ```json
    {
        "message": "Voice sample deleted successfully"
    }
    ```

## Background Music Resource

Manages background music samples.

#### `GET /bgm`

*   **Description**: Retrieves all background music samples (excluding those marked specifically as transitions).
*   **Response (Success - 200 OK)**:
    ```json
    [
        {
            "id": "integer", // Auto-incrementing ID
            "music_name": "string",
            "music_sample": "string_url", // URL to music sample
            "tags": "string",
            "description": "string"
            // "transition" field is usually false here
        }
    ]
    ```

#### `GET /bgm/<bgm_id>`

*   **Description**: Retrieves a specific background music sample by its ID.
*   **Path Parameters**:
    *   `bgm_id` (integer, required): The unique identifier for the background music sample.
*   **Response (Success - 200 OK)**:
    ```json
    {
        "id": "integer",
        "music_name": "string",
        "music_sample": "string_url",
        "tags": "string",
        "description": "string",
        "transition": "boolean"
    }
    ```

#### `POST /bgm`

*   **Description**: Creates a new background music sample.
*   **Request Body (JSON)**:
    *   `music_name` (string, required): The name of the music.
    *   `music_sample` (string, required): A URL to the music sample.
    *   `tags` (string, optional): Tags associated with the music.
    *   `description` (string, optional): A description of the music.
    *   `transition` (boolean, optional, default: `False`): Indicates if the music is primarily for transitions rather than continuous background.
*   **Response (Success - 201 Created)**:
    *   The created BackgroundMusic object.
*   **Nuances**:
    *   When creating, an embedding of the description is generated and stored for semantic search capabilities (e.g., finding appropriate sound effects for story phrases).

#### `DELETE /bgm/<bgm_id>`

*   **Description**: Deletes a background music sample by its ID.
*   **Path Parameters**:
    *   `bgm_id` (integer, required): The unique identifier for the background music sample to be deleted.
*   **Response (Success - 200 OK)**:
    ```json
    {
        "message": "Background music id <bgm_id> deleted successfully"
    }
    ```

## Styles Resource

Manages image styles that can be applied during image generation.

#### `GET /styles`

*   **Description**: Retrieves all image styles.
*   **Response (Success - 200 OK)**:
    ```json
    [
        {
            "id": "integer", // Auto-incrementing ID
            "style_name": "string",
            "style_sample": "string_url", // URL to a sample image demonstrating the style
            "tags": "string",
            "description": "string"
        }
    ]
    ```

#### `GET /styles/<style_id>`

*   **Description**: Retrieves a specific image style by its ID.
*   **Path Parameters**:
    *   `style_id` (integer, required): The unique identifier for the image style.
*   **Response (Success - 200 OK)**:
    ```json
    {
        "id": "integer",
        "style_name": "string",
        "style_sample": "string_url",
        "tags": "string",
        "description": "string"
    }
    ```

#### `POST /styles`

*   **Description**: Creates a new image style.
*   **Request Body (JSON)**:
    *   `style_name` (string, required): The name of the style (e.g., "Van Gogh", "Pixel Art").
    *   `style_sample` (string, required): A URL to an image sample representing the style.
    *   `tags` (string, optional): Tags associated with the style.
    *   `description` (string, optional): A description of the style.
*   **Response (Success - 201 Created)**:
    *   The created Styles object.

#### `DELETE /styles/<style_id>`

*   **Description**: Deletes an image style by its ID.
*   **Path Parameters**:
    *   `style_id` (integer, required): The unique identifier for the image style to be deleted.
*   **Response (Success - 200 OK)**:
    ```json
    {
        "message": "Image style id <style_id> deleted successfully"
    }
    ```

## Webhooks

#### `GET /video_gen_webhook/<idea>/<version>`

*   **Description**: Webhook endpoint called by an external video generation service (Flare) to notify the API about the status and result of a video generation task. This endpoint updates the corresponding Draft's status.
*   **Path Parameters**:
    *   `idea` (string, required): The idea ID of the video being generated.
    *   `version` (string, required): The version number (as a string) of the draft being generated.
*   **Query Parameters**:
    *   `path` (string, optional): Local path to the generated video file on the rendering service. If `link` is not provided, this path might be used to upload the video.
    *   `link` (string, optional): Publicly accessible URL to the generated video.
    *   `error` (string, optional): Flag indicating if an error occurred (e.g., "true", "1").
    *   `processing` (string, optional): Flag indicating if video generation is still in progress (e.g., "true", "1").
    *   `msg` (string, optional): An error message or status update related to the video generation.
*   **Response (Success - 200 OK)**:
    ```json
    {
        "status": "success" // Indicates the webhook was received and processed
    }
    ```
*   **Response (Error - 400 Bad Request)**:
    ```json
    {
        "status": "error" // Indicates an issue processing the webhook
    }
    ```
*   **Nuances**:
    *   If `error` is true, the draft's stage is set to `VIDEO_GEN_FAILED`.
    *   If `processing` is true, the draft's stage is set to `VIDEO_GEN_PROCESSING`.
    *   If `link` (or `path` from which a link can be derived) is provided and no error/processing, the draft's `generated_video` field is updated and stage set to `VIDEO_GENERATED`.

## Health Check

#### `GET /health`

*   **Description**: Returns the health status of the service.
*   **Response (Success - 200 OK)**:
    ```json
    {
        "status": "healthy"
    }
    ```

## Test Endpoints

These endpoints are primarily for testing and development purposes.

#### `DELETE /hugchat`

*   **Description**: Deletes all conversations from the Hugging Face chatbot cache/session.
*   **Response (Success - 200 OK)**:
    ```json
    {
        "status": "success"
    }
    ```

#### `GET /test/all`

*   **Description**: Runs a suite of regression tests, including prompt generation tests using a chatbot.
*   **Response (Success - 200 OK)**:
    ```json
    {
        "status": "test ended, check stdout"
    }
    ```

#### `GET /test/image/<engine>`

*   **Description**: Runs image generation tests for a specified engine.
*   **Path Parameters**:
    *   `engine` (string, required): The image generation engine to test (e.g., "goapi_midjourney").
*   **Response (Success - 200 OK)**:
    ```json
    {
        "status": "check stdout"
    }
    ```

#### `POST /test/image-search`

*   **Description**: Tests image search functionality using an image search agent and chatbot.
*   **Request Body (JSON)**:
    *   `search` (string, required): The search query for images.
*   **Response (Success - 200 OK)**:
    ```json
    {
        "result": "object_containing_search_results"
    }
    ```
*   **Response (Error - 200 OK with error field - check logic)**:
    ```json
    {
        "error": true // if search param is missing
    }
    ```

#### `POST /test/sound-search`

*   **Description**: Tests sound search functionality. It takes a story, generates embeddings, searches for relevant sounds (transition BGM), and attempts to map sounds to story phrases.
*   **Request Body (JSON)**:
    *   `story` (string, required): The story text to search sounds for.
*   **Response (Success - 200 OK)**:
    ```json
    {
        "sound_list": [ // List of relevant sounds found
            { "name": "string", "url": "string_url" }
        ],
        "sound_map": "object_mapping_sounds_to_story_parts"
    }
    ```
*   **Response (Error - 200 OK with error field - check logic)**:
    ```json
    {
        "error": true // if story param is missing
    }
    ```

## Examples

### Example 1: Create a new Idea

```http
POST /idea
Content-Type: application/json

{
    "prompt": "A brave knight on a quest to find a mythical dragon.",
    "length": 5,
    "user_id": "user123"
}
```

### Example 2: Create a new Draft from an Idea

```http
POST /draft
Content-Type: application/json

{
    "idea_id": "generated_idea_id_from_example_1",
    "story": "Sir Reginald, the bravest knight in the kingdom, embarked on a perilous journey. He sought the legendary Azure Dragon, whose tears were said to cure any ailment.",
    "voice_id": "voice_id_from_get_voices",
    "style_id": "style_id_from_get_styles",
    "gen_video": true,
    "stop_at_stage": 8
}
```

### Example 3: Patch an existing Draft to change the story and regenerate specific images

```http
PATCH /draft
Content-Type: application/json

{
    "idea_id": "existing_idea_id",
    "version_id": 1,
    "edit_inplace": true,
    "story": "Sir Reginald, now weary but resolute, finally reached the dragon's lair high in the misty mountains. The Azure Dragon was not fearsome, but wise.",
    "regen_images": [2],
    "regen_image_prompts": ["A close-up of Sir Reginald's determined face, showing his exhaustion."]
}
```

### Example 4: Patch a draft to convert an image to a video clip

```http
PATCH /draft
Content-Type: application/json

{
    "idea_id": "existing_idea_id",
    "version_id": 2,
    "edit_inplace": true,
    "convert_to_video": [
        {
            "pos": 3,
            "prompt": "The dragon blinks slowly, ancient wisdom in its eyes."
        }
    ],
    "video_engine": "goapi_wanx"
}

## Moodboard Resource

Generates stylistic references and image grids based on a topic and context.

#### `POST /api/moodboard`

*   **Description**: Creates a new moodboard by brainstorming artistic styles and generating consistent 2x2 image grids for each style. It leverages internet-grounded context searching.
*   **Request Body (JSON)**:
    *   `topic` (string, required): The main subject for style generation.
    *   `ctx` (string, optional): Additional narrative or emotional context.
    *   `num_styles` (integer, optional, default: 3): Number of distinct styles to generate.
*   **Response (Success - 200 OK)**:
    ```json
    {
        "topic": "string",
        "ctx": "string",
        "moodboard": [
            {
                "style_name": "string",
                "reasoning": "string",
                "master_grid_url": "string_url",
                "cropped_references": ["string_url_1", "string_url_2", "string_url_3", "string_url_4"]
            }
        ]
    }
    ```
*   **Response (Error - 400/500)**:
    ```json
    {
        "error": "Error message"
    }
    ```
