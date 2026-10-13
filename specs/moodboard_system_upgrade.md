# Moodboard API & Context Grounding Specification

## 1. Overview
The Moodboard system is a standalone creative tool designed to generate multiple, high-fidelity stylistic references based on a human-provided `topic` and optional `ctx`. Unlike the primary video pipeline, it is decoupled from the `Idea` and `Draft` database models, allowing for rapid, independent stylistic exploration.

## 2. The Moodboard API (`POST /api/moodboard`)

### Request Parameters
| Parameter | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `topic` | string | Yes | The core subject for style brainstorming. |
| `ctx` | string | No | Narrative boundaries, emotional tone, or environmental constraints. |
| `num_styles` | integer | No (Default: 3) | Number of unique artistic variations to generate. |

### Internal Logic Flow
1.  **Internet-Grounded Context (`summary_ctx`):**
    The system immediately passes the `topic` and `ctx` to `processor.build_and_set_script_context`.
    - This triggers the `gemini_search` agent to fetch real-world data from Google Search.
    - Research summaries are pinned to the chatbot's system memory via `chatbot.set_global_ctx(final_summary)`.
2.  **Art Director Reasoning:**
    The `moodboard-style-generation` prompt is invoked. It analyzes the grounded context to brainstorm `num_styles` distinct art styles.
3.  **UGC Realism Enforcement:**
    Every generated style is filtered through the **User-Generated Content (UGC) Realism Standard**. This enforces a non-CGI, raw documentary aesthetic (candid smartphone photos, natural lighting, lens grain).
4.  **Native Panel Generation (8 Panels):**
    For each style, the LLM produces exactly **8 distinct panel descriptions**. Each prompt is injected with a **Single Frame & Anti-Grid constraint** to ensure the generated references are clean individual shots, suitable for use as high-quality style references in the downstream video pipeline.
5.  **Parallel One-Shot Grid Generation:**
    Styles are processed concurrently using `ThreadPoolExecutor`. For each style, the system calls `processor.create_image_grid`. This generates a high-res grid containing the panels.
6.  **Slicing & Vision Detection:**
    *(Currently skips automated slicing in favor of Master Grid URLs for faster dashboard exploration).*

### Response Structure
```json
{
  "topic": "Cyberpunk market in Old Delhi",
  "ctx": "Monsoon rain, crowded, smell of spices mixed with ozone",
  "moodboard": [
    {
      "style_name": "Gritty 35mm Street Photography",
      "reasoning": "Standard documentary lenses capture the chaos of the market with shallow depth...",
      "master_grid_url": "https://storage.baasha.ai/.../grid.png",
      "cropped_references": [
        "https://storage.baasha.ai/.../crop_1.png",
        "https://storage.baasha.ai/.../crop_2.png"
      ]
    }
  ]
}
```

## 3. Collaboration & Extension Guiding Principles

### Adding New Constraints
- **Global Context:** Always use `chatbot.set_global_ctx` for long-running narrative constraints to avoid prompt bloating in downstream calls.
- **Realism Guide:** Any new stylistic prompt should reference the `realistic_image_system_prompt.md` to maintain the Documentary/UGC brand identity.

### Testing and Validation
- **Grid Consistency:** Verify that `create_image_grid` correctly slices panels without bleeding.
- **Search Relevance:** Use the `/test/image-search` or equivalent logs to ensure `gemini_search` is fetching high-signal grounding data for the topic.
- **JSON Integrity:** Ensure LLM outputs are strictly pure JSON to prevent parser orphans during parallel style generation.
