# Free Resources to use in PROD env

Everything below needs **no credit card / payment method**. Only a free
account + free API key (or nothing at all).

## Already wired in

| Kind | Value | Where |
| --- | --- | --- |
| `voice_id` | `gtts` | `config.ini [TTS] TOOLKIT` |
| `avatar_engine` | `gooey_ai` | API arg |
| `background_music_id` | `10` | API arg |
| `primary_chatbot` | `groq` | `config.ini [PREFS] PRIMARY_CHATBOT` |

## LLM (free, vision-capable)

Set `PRIMARY_CHATBOT` in `config.ini [PREFS]` to one of:

| Value | Provider | Free limits (Oct 2026) | Key required |
| --- | --- | --- | --- |
| `groq` | Groq `qwen/qwen3.8-27b` (vision, 3 img/req) | 30 RPM · 1K RPD · 8K TPM | `GROQ_KEY` |
| `openrouter` | OpenRouter free models (auto fallback chain, see below) | 20 RPM · 50 RPD (1,000 RPD after any $10+ top-up ever) | `OPENROUTER_KEY` |
| `openrouter#<model>` | OpenRouter, pinned model (no fallback) | same | `OPENROUTER_KEY` |
| `cloudflare` | Cloudflare Workers AI `@cf/meta/llama-4-scout-17b-16e-instruct` | ~10K Neurons/day (shared pool) | `CLOUDFLARE_API_TOKEN` + `CLOUDFLARE_ACCOUNT_ID` || `gemini` | Google Gemini Flash free tier | unpublished, per-project (check AI Studio) | `GOOGLE_GENAI_KEY` |
| `ollama#<model>` | Local Ollama (e.g. `ollama#llama3.2-vision`) | unlimited | none |

`PRIMARY_CHATBOT` also accepts a **comma-separated fallback chain**, tried
in order when the head errors/429s. Every part must name a known provider:

```ini
PRIMARY_CHATBOT = groq, openrouter, cloudflare
```

Multiple keys on the same provider (`GROQ_KEY = k1, k2`) are tried before
the chain moves on, so `groq, openrouter` means `groq#k1 → groq#k2 → openrouter`.

Free key sign-ups (all no card):

- OpenRouter → <https://openrouter.ai/keys>
- Cloudflare → <https://dash.cloudflare.com/api-tokens> (needs Account ID from the dashboard sidebar)

OpenRouter free-model status (live-tested Oct 2026) — `openrouter#` tries these in order:

| Model | Status |
| --- | --- |
| `dots-studio/dots-3-note-preview:free` | ✅ default — vision works, 512k ctx, reliable |
| `google/gemma-4-26b-a4b-it:free` | ⚠️ vision+video, but 429 upstream most of the day |
| `google/gemma-4-31b-it:free` | ⚠️ vision+video, 429 upstream most of the day |
| `openrouter/free` (router) | ❌ **do not use** — picks random models, e.g. routed a prompt to `nvidia/nemotron-3.5-content-safety` which ignored it and replied `"User Safety: safe"` |
| `thinkingmachines/inkling*:free` | ❌ 403, agentic-harness only |
| `nvidia/nemotron-3-nano-omni*:free` | ❌ 502, upstream exhausted |

Only 7 of OpenRouter's 14 free models accept images; the other 4 are text-only.

Notes:

- **Heads-up:** in this venv `groq==0.11.0` + `httpx==0.28.1` is broken
  (`TypeError: Client.__init__() got an unexpected keyword argument 'proxies'`),
  so `ChatInterface("groq")` — the repo default — fails before any request.
  Pin `httpx<0.28` or upgrade `groq`.
- OpenRouter free models are capped at **20 requests/min** account-wide;
  `ChatInterface` self-throttles to 3s between calls.
- Groq's binding limit is **8K tokens/min** — heavy vision batches (grid
  judging, image search) will 429 first. Use `openrouter`/`cloudflare` as
  the fallback, they are wired into `ChatInterface.llm_fallback`.
- Gemini **image/video/music generation models are paid-only** now — only
  the text/vision Flash models are free.

## Image generation (free)

Set `image_engine` to one of:

| Value | Backend | Free limits | Key required |
| --- | --- | --- | --- |
| `cf_flux` | Cloudflare Workers AI `FLUX.1-schnell` | **172.8 Neurons/image** → ~**57 images/day** on the 10K free pool, resets 00:00 UTC | `CLOUDFLARE_API_TOKEN` + `CLOUDFLARE_ACCOUNT_ID` |
| `pollinations` | Pollinations.ai (keyless) | ~1 req / 15s, 1-concurrent per IP, HTTP 402 when exceeded; server downgrades anonymous jobs to the `sana` model | none (`POLLINATIONS_KEY` optional → real `flux` + higher limits) |

Caveats:

- `cf_flux` calls a **JSON-only** endpoint that always returns **1024×1024** —
  it 400s on `width`/`height`/`image_size`/`num_images`/`seed`. Aspect ratio
  is applied by center-cropping the square in `baasha_pipeline/cloudflare_flux.py`,
  so a 9:16 `1K` output is 576×1024. Pillow is used for the crop.
- `cf_flux` and `pollinations` are **text-to-image only** — character/style
  reference images are dropped (they are not in `multi_ref_support` in
  `processor.image_gen`). Use `gemini_nano_banana` or `fal` when you need
  reference-driven character continuity.
- Cloudflare also exposes `@cf/black-forest-labs/flux-2-klein-4b` /
  `flux-2-dev`, which advertise **multi-reference** editing, but the live
  endpoint requires `multipart/form-data` (not JSON). Not wired up yet.
- `gemini_nano_banana` (the server default) is **no longer free** on the
  Gemini API — every image model shows "Free Tier: Not available".
- `hf_flux1` exists in the codebase but free HuggingFace accounts now get
  only **$0.10/month** inference credit — treat it as paid.
- Free image tiers have no SLA. Treat them as best-effort and keep
  `image_gen_errors` handling enabled.

## Keys to add

Put real keys in **`config.secrets.ini`** (gitignored, loaded on top of
`config.ini` by `server.py` / `app.py` / `mcp_server.py`). Never put them in
`config.ini` — that file is tracked.

```ini
# config.secrets.ini
[SECRETS]
OPENROUTER_KEY =            # free, no card
CLOUDFLARE_ACCOUNT_ID =     # free, no card
CLOUDFLARE_API_TOKEN =      # free, no card
POLLINATIONS_KEY =          # optional, keyless works without it
```

Empty placeholders live in `config.ini [SECRETS]` so the keys are
discoverable; the secrets file only needs the ones you actually filled in.

## Gotchas hit by the live end-to-end run (all fixed)

Three bugs only surface once you run idea → draft → images → audio for real:

1. **Workers AI truncates long JSON.** `@cf/meta/llama-4-scout-17b-16e-instruct`
   defaults to `max_tokens: 256`, so the story/image-prompt calls came back cut
   off mid-string with no closing ```` ``` ```` fence. `markdown_parse()` then
   returned `None` and `json.loads(None)` crashed the draft. Measured live:
   default → 993 chars (broken), `max_tokens: 4096` → complete object.
   `free_llms.CLOUDFLARE_MAX_TOKENS` now sets this on every call.

2. **`ASSETS_*_BUCKET` helpers are passed uncalled.** They are functions
   returning `(bucket, folder)`, but every caller in the repo passes the
   function itself, so `bucket_name, folder_path = bucket` raised
   `cannot unpack non-iterable function object`. This broke image upload *and*
   the TTS audio upload — and because audio then failed, `timepoints_map`
   was never set and stage 5 died with `KeyError: 'timepoints_map'`.
   `object_storage.resolve_bucket()` now accepts both styles.

3. **Local S3 mock only serves path-style URLs.** Returned URLs used
   virtual-host style (`http://baasha-assets.localhost:9000/...`) which 404s on
   read-back even though the upload succeeded. `object_storage.compose_url()`
   switches to path style (`http://localhost:9000/baasha-assets/...`) when the
   cluster is loopback, or when `object_storage.path_style` is set explicitly.
   Remote clusters keep virtual-host URLs, so production is unchanged.

Verified end-to-end with `image_engine=cf_flux`, `voice_id=gtts`,
`stop_at_stage=5`: story + title + 3 image prompts + 3 images + 2 TTS clips +
word-level `timepoints_map` + remotion config, all fetched back HTTP 200.


- Cerebras — replaced free tier with a $5/30-day card-required trial
- GitHub Models — retired 30 Jul 2026
- Together AI / SambaNova — trial credits ended
- OpenRouter image generation — no `:free` image models
- `ideogram`, `sieve_ai`, `segmind_api_key`, `eachlabs_ai_token` — keys are
  forced empty or never populated in this repo
