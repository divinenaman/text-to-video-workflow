from .hugging_face import hug_chat
import google.generativeai as google_genai
from .configs import app_config
from . import errors
from .logger import logging
from . import groq_local as groq
from . import free_llms
import time
from dataclasses import dataclass
import base64
from typing import Optional
import requests
import json

LLM_HUGCHAT = "hugchat"
LLM_GEMINI = "gemini"
LLM_GEMMA = "gemma"
LLM_GROQ = "groq"
LLM_OLLAMA = "ollama"
LLM_OPENROUTER = "openrouter"
LLM_CLOUDFLARE = "cloudflare"
LLM_STATELESS = (LLM_GROQ, LLM_OPENROUTER, LLM_CLOUDFLARE)
LLM_PROVIDERS = (
    LLM_GEMINI,
    LLM_GEMMA,
    LLM_HUGCHAT,
    LLM_GROQ,
    LLM_OLLAMA,
    LLM_OPENROUTER,
    LLM_CLOUDFLARE,
)


def get_keys(k):
    k = app_config.get().get("auth").get(k)
    if not isinstance(k, list):
        return [k]
    return k


@dataclass
class Img:
    _bytes: list[bytes]
    text: str


def encode_image(img_bytes):
    return base64.b64encode(img_bytes).decode("utf-8")


def split_prompt(p):
    """Normalize a fetch_text payload into ``(text, [image_bytes, ...])``."""
    texts = []
    imgs = []

    items = p if isinstance(p, list) else [p]
    for q in items:
        if isinstance(q, Img):
            if q.text:
                texts.append(q.text)
            if q._bytes:
                imgs.append(q._bytes)
        elif q is not None:
            texts.append(str(q))

    return "\n".join(texts), imgs


def get_global_ctx(req_global_ctx):

    c = app_config.get().get("global_chatbot_ctx")
    ctx = None
    if c:
        ctx = c
    if req_global_ctx:
        if ctx:
            ctx += "\n\n" + req_global_ctx
        else:
            ctx = req_global_ctx

    return ctx


def get_gemini_settings():
    gen_config = {"temperature": 1.0}

    return {
        "safety_settings": [
            {
                "category": "HARM_CATEGORY_HARASSMENT",
                "threshold": "BLOCK_NONE",
            },
            {
                "category": "HARM_CATEGORY_HATE_SPEECH",
                "threshold": "BLOCK_NONE",
            },
            {
                "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                "threshold": "BLOCK_NONE",
            },
            {
                "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
                "threshold": "BLOCK_NONE",
            },
        ],
        "generation_config": gen_config,
    }


class ChatInterface:
    @errors.raise_ctx_errors
    def __init__(self, llm_name=None, keys=None, _chain=None):
        self.llm = None
        self.llm_fallback = None
        self.rate_limiter = None
        self.llm_service = None
        self.ctx = []
        self.global_ctx = None

        if not llm_name:
            llm_name = app_config.get().get("primary_chatbot")

        # "groq, openrouter, cloudflare" -> primary + cross-provider fallbacks.
        # Only splits when every comma-separated part names a known provider,
        # so a model id that happens to contain a comma is left alone.
        chain = _chain
        if chain is None and "," in str(llm_name):
            names = [n.strip() for n in str(llm_name).split(",") if n.strip()]
            if len(names) > 1 and all(n.split("#")[0] in LLM_PROVIDERS for n in names):
                llm_name = names[0]
                chain = names[1:]

        llm_name_split = llm_name.split("#")

        if llm_name.startswith(LLM_GEMINI) or llm_name.startswith(LLM_GEMMA):

            if not keys:
                keys = get_keys("google_genai_key")
            key = keys[0]

            if not key:
                # err
                raise Exception("BaashaChatInterface: Google genai key not found!")

            google_genai.configure(api_key=key)
            gemini_settings = get_gemini_settings()
            try:
                model = google_genai.GenerativeModel(
                    model_name=llm_name,
                    safety_settings=gemini_settings["safety_settings"],
                    generation_config=gemini_settings["generation_config"],
                )
            except Exception as e:
                logging.error(
                    f"BaashaChatInterface: error while loading gemini model - {llm_name}, falling back to gemini 1.0"
                )
                model = google_genai.GenerativeModel(
                    model_name="gemini-pro",
                    safety_settings=gemini_settings["safety_settings"],
                    generation_config=gemini_settings["generation_config"],
                )

            self.llm_name = llm_name
            self.llm_service = LLM_GEMINI
            self.model_class = model
            self.llm = model.start_chat(history=[])
            self.rate_limiter = {"timeout": 5, "last_req": None}

            if len(keys) > 1:
                self.llm_fallback = ChatInterface(llm_name, keys[1:])

        elif llm_name_split[0] == LLM_HUGCHAT:
            self.llm_service = LLM_HUGCHAT
            self.llm = hug_chat.get_chatbot()
            self.rate_limiter = {"timeout": 10, "last_req": None}

            try:
                # find model
                idx = hug_chat.hugchat_model_index_list.index(llm_name_split[1])
                logging.info(f"BaashaChatInterface: loading model - {llm_name}")
                self.llm.switch_llm(idx)
                self.llm_name = llm_name
            except Exception as e:
                logging.error(
                    f"BaashaChatInterface: model not found - {llm_name} - {str(e)}"
                )
                logging.info(
                    f"BaashaChatInterface: falling back to first model - {hug_chat.hugchat_model_index_list[0]}"
                )
                self.llm.switch_llm(0)
                self.llm_name = hug_chat.hugchat_model_index_list[0]

            # 20 seconds b/w each request
            self.rate_limiter = {"timeout": 30, "last_req": None}

        elif llm_name == LLM_GROQ:
            if not keys:
                keys = get_keys("groq_key")
            key = keys[0]

            self.llm = groq.get_client(key)
            self.llm_service = LLM_GROQ
            self.rate_limiter = {"timeout": 8, "last_req": None}
            self.llm_name = "qwen/qwen3.8-27b"
            self.llm_name_vision = ""
            self.ctx = []

            if len(keys) > 1:
                self.llm_fallback = ChatInterface(llm_name, keys[1:])

        elif llm_name.startswith(LLM_OLLAMA):
            # ollama#model_name format
            model_name = (
                llm_name_split[1] if len(llm_name_split) > 1 else "llama3.2-vision"
            )
            self.llm_service = LLM_OLLAMA
            self.llm_name = model_name
            self.ollama_host = (
                app_config.get()
                .get("auth")
                .get("ollama_host", "http://localhost:11434")
            )
            self.ctx = []
            self.rate_limiter = {
                "timeout": 0,
                "last_req": None,
            }  # no rate limit for local

            # Test connection
            try:
                self._ollama_check_model(model_name)
            except Exception as e:
                logging.error(f"BaashaChatInterface: Ollama model check failed - {e}")

        elif llm_name_split[0] == LLM_OPENROUTER:
            # openrouter#<model> format, defaults to the free-models router
            if not keys:
                keys = get_keys("openrouter_key")
            keys = [k for k in (keys or []) if k]

            if not keys:
                raise Exception(
                    "BaashaChatInterface: OpenRouter key not found! "
                    "Set OPENROUTER_KEY in config.secrets.ini (free, no card)."
                )

            self.llm_service = LLM_OPENROUTER
            self.llm = keys[0]
            self.llm_name = (
                llm_name_split[1]
                if len(llm_name_split) > 1
                else free_llms.OPENROUTER_DEFAULT_MODEL
            )
            self.ctx = []
            # free tier is 20 requests/min across all :free models
            self.rate_limiter = {"timeout": 3, "last_req": None}

            if len(keys) > 1:
                self.llm_fallback = ChatInterface(llm_name, keys[1:])

        elif llm_name_split[0] == LLM_CLOUDFLARE:
            # cloudflare#@cf/<model> format
            if not keys:
                keys = get_keys("cloudflare_token")
            keys = [k for k in (keys or []) if k]

            if not keys:
                raise Exception(
                    "BaashaChatInterface: Cloudflare token not found! "
                    "Set CLOUDFLARE_API_TOKEN + CLOUDFLARE_ACCOUNT_ID in "
                    "config.secrets.ini (free, no card)."
                )

            self.llm_service = LLM_CLOUDFLARE
            self.llm = keys[0]
            self.llm_account_id = get_keys("cloudflare_account_id")[0] or ""
            self.llm_name = (
                llm_name_split[1]
                if len(llm_name_split) > 1
                else free_llms.CLOUDFLARE_DEFAULT_MODEL
            )
            self.ctx = []
            # free tier is 10k Neurons/day, ~300 req/min
            self.rate_limiter = {"timeout": 1, "last_req": None}

            if len(keys) > 1:
                self.llm_fallback = ChatInterface(llm_name, keys[1:])

        else:
            raise Exception(f"BaashaChatInterface: Model ({llm_name}) not found!!")

        if chain:
            tail = self
            while tail.llm_fallback:
                tail = tail.llm_fallback
            tail.llm_fallback = ChatInterface(chain[0], _chain=chain[1:])

    def _ollama_check_model(self, model_name):
        """Check if model exists in Ollama, pull if not."""
        response = requests.get(f"{self.ollama_host}/api/tags", timeout=10)
        response.raise_for_status()
        models = response.json().get("models", [])
        model_names = [m.get("name", "") for m in models]

        if not any(model_name in m for m in model_names):
            logging.info(f"BaashaChatInterface: Pulling Ollama model {model_name}...")
            pull_resp = requests.post(
                f"{self.ollama_host}/api/pull",
                json={"name": model_name},
                timeout=300,
                stream=True,
            )
            pull_resp.raise_for_status()
            for line in pull_resp.iter_lines():
                if line:
                    try:
                        data = json.loads(line)
                        if data.get("status"):
                            logging.info(f"  {data['status']}")
                    except Exception:
                        pass
            logging.info(f"BaashaChatInterface: Model {model_name} ready")

    @errors.log_ctx_errors
    def is_ideal(self):
        if self.rate_limiter:
            timeout = self.rate_limiter.get("timeout", 0)
            last_req = self.rate_limiter.get("last_req", 0)
            if last_req == None:
                last_req = -timeout

            time_diff = timeout + last_req - time.time()

            if time_diff > 0:
                return time_diff

            return 0

        return 0

    @errors.log_ctx_errors
    def sync_ctx(self):
        # equivalent to being on the same page
        # TODO: add threading
        if self.llm_fallback:
            logging.info(
                f"BaashaChatInterface: syncing context prompt to {self.llm_fallback.llm_name}"
            )

            if self.llm_fallback.llm_service in LLM_STATELESS and self.ctx:
                self.llm_fallback.ctx = self.ctx.copy()
                self.llm_fallback.sync_ctx()

            elif self.llm_fallback.llm_service == LLM_GEMINI and self.ctx:
                self.llm_fallback.ctx = self.ctx.copy()
                self.llm_fallback.llm = self.llm_fallback.model_class.start_chat(
                    history=self.llm_fallback.ctx
                )
                self.llm_fallback.sync_ctx()

            elif self.llm_fallback.llm_service == LLM_OLLAMA and self.ctx:
                self.llm_fallback.ctx = self.ctx.copy()

        return True

    @errors.log_ctx_errors
    def clear_ctx(self):
        if self.ctx:
            self.ctx = []

            if self.llm_service == LLM_GEMINI:
                ctx_text = []
                has_global_ctx = get_global_ctx(self.global_ctx)
                if has_global_ctx:
                    ctx_text.append(
                        {"role": "user", "parts": [{"text": has_global_ctx}]}
                    )

                self.ctx = ctx_text
                self.llm = self.model_class.start_chat(history=self.ctx)

                self.sync_ctx()

            elif self.llm_service == LLM_OLLAMA:
                has_global_ctx = get_global_ctx(self.global_ctx)
                if has_global_ctx:
                    self.ctx = [{"role": "system", "content": has_global_ctx}]

            elif self.llm_fallback:
                self.llm_fallback.clear_ctx()

    @errors.log_ctx_errors
    def set_global_ctx(self, t):
        self.global_ctx = t

        if self.llm_service == LLM_GEMINI:
            ctx_text = {"role": "user", "parts": [{"text": get_global_ctx(t)}]}
            self.ctx.append(ctx_text)
            self.llm = self.model_class.start_chat(history=self.ctx)

            self.sync_ctx()

        elif self.llm_service == LLM_OLLAMA:
            ctx_text = {"role": "system", "content": get_global_ctx(t)}
            self.ctx = [ctx_text]

    @errors.raise_ctx_errors
    def fetch_text(
        self,
        p: str,
        is_context: bool = False,
        append_context: bool = False,
        system_prompt: Optional[str] = None,
        custom_model: Optional[str] = None,
    ):
        self.llm_name = custom_model or self.llm_name

        if self.rate_limiter:
            time_diff = self.is_ideal()
            if time_diff > 0:
                if self.llm_fallback and not is_context:
                    fallback_time_diff = self.llm_fallback.is_ideal()

                    if fallback_time_diff < time_diff:
                        # optimization
                        return self.llm_fallback.fetch_text(
                            p, system_prompt=system_prompt, custom_model=custom_model
                        )

                logging.info(
                    f"BaashaChatInterface {self.llm_name}: query timeout for {time_diff} seconds"
                )
                time.sleep(time_diff)

            t = time.time()
            logging.info(
                f"BaashaChatInterface {self.llm_name}: query recorded timestamp {t}"
            )
            self.rate_limiter["last_req"] = t

        if self.llm_service == LLM_HUGCHAT:
            if is_context:
                _ = self.sync_ctx()
            return hug_chat.fetch_text(p, self.llm)

        elif self.llm_service == LLM_GROQ:
            img = None
            text = p

            if isinstance(text, list) and len(text) > 0:
                text = text[0]

            if isinstance(text, Img):
                img = f"data:image/png;base64," + encode_image(text._bytes)
                text = text.text

            t = groq.fetch_text(
                self.llm,
                self.ctx,
                text,
                img,
                system=system_prompt or get_global_ctx(self.global_ctx),
                model=custom_model,
            )

            # TODO: add img to ctx
            if is_context and append_context and self.ctx:
                self.ctx.append(("user", text))
                self.ctx.append(("assistant", t if t else "no reponse"))
            elif is_context:
                self.ctx = [("user", text)]
                self.ctx.append(("assistant", t if t else "no reponse"))

            if is_context:
                self.sync_ctx()

            if not t and self.llm_fallback:
                return self.llm_fallback.fetch_text(
                    p, system_prompt=system_prompt, custom_model=custom_model
                )

            if not t:
                raise Exception("BaashaChatInterface: Generation Failed!!")

            return t

        elif self.llm_service in (LLM_OPENROUTER, LLM_CLOUDFLARE):
            return self._free_fetch_text(
                p,
                is_context=is_context,
                append_context=append_context,
                system_prompt=system_prompt,
                custom_model=custom_model,
            )

        elif self.llm_service == LLM_OLLAMA:
            return self._ollama_fetch_text(
                p,
                is_context=is_context,
                append_context=append_context,
                system_prompt=system_prompt,
                custom_model=custom_model,
            )

        elif self.llm_service.startswith(LLM_GEMINI):
            res = None
            err = None
            user_query = p

            try:
                if isinstance(p, list):
                    p_process = []
                    for q in p:
                        if isinstance(q, Img):
                            p_process.append(
                                {"mime_type": "image/png", "data": q._bytes}
                            )
                            p_process.append(q.text)
                        else:
                            p_process.append(q)
                    p = p_process

                if isinstance(p, Img):
                    res = self.llm.send_message(
                        [{"mime_type": "image/png", "data": p._bytes}, p.text]
                    )
                    user_query = p.text
                else:
                    res = self.llm.send_message(p)
            except Exception as e:
                err = e

            text = None
            if not err:
                text = ""
                try:
                    for chunck in res:
                        next_t = chunck.text
                        if next_t != "":
                            text = text + next_t

                except Exception as e:
                    for chunck in res.parts:
                        next_t = chunck.text
                        if next_t != "":
                            text = text + next_t

            # TODO: add img to ctx
            if is_context and append_context:
                self.ctx.append({"role": "user", "parts": [{"text": user_query}]})
                self.ctx.append(
                    {
                        "role": "model",
                        "parts": [{"text": text if text else "no reponse"}],
                    }
                )
            elif is_context:
                self.ctx = [{"role": "user", "parts": [{"text": user_query}]}]
                self.ctx.append(
                    {
                        "role": "model",
                        "parts": [{"text": text if text else "no reponse"}],
                    }
                )

            if is_context:
                self.sync_ctx()

            if err and self.llm_fallback:
                return self.llm_fallback.fetch_text(p)
            elif err:
                raise err

            return text

        raise Exception("BaashaChatInterface: Model not found!!")

    def _free_fetch_text(
        self,
        p,
        is_context: bool = False,
        append_context: bool = False,
        system_prompt: Optional[str] = None,
        custom_model: Optional[str] = None,
    ):
        """Dispatch to the free OpenAI-compatible providers (OpenRouter / Cloudflare)."""
        if not self.llm:
            raise Exception(
                f"BaashaChatInterface: {self.llm_name} API key not configured"
            )

        text, imgs = split_prompt(p)
        system = system_prompt or get_global_ctx(self.global_ctx)
        model = custom_model or self.llm_name

        try:
            if self.llm_service == LLM_OPENROUTER:
                fallbacks = None
                if (
                    custom_model is None
                    and self.llm_name == free_llms.OPENROUTER_DEFAULT_MODEL
                ):
                    fallbacks = free_llms.OPENROUTER_MODEL_FALLBACKS
                t = free_llms.openrouter_fetch_text(
                    self.llm, self.ctx, text, imgs, system, model, fallbacks
                )
            else:
                t = free_llms.cloudflare_fetch_text(
                    self.llm,
                    self.llm_account_id,
                    self.ctx,
                    text,
                    imgs,
                    system,
                    model,
                )
        except Exception as e:
            logging.error(f"BaashaChatInterface {self.llm_name}: {e}")
            if self.llm_fallback:
                return self.llm_fallback.fetch_text(
                    p, system_prompt=system_prompt, custom_model=custom_model
                )
            raise

        if is_context and append_context and self.ctx:
            self.ctx.append({"role": "user", "content": text})
            self.ctx.append({"role": "assistant", "content": t if t else "no reponse"})
        elif is_context:
            self.ctx = [{"role": "user", "content": text}]
            self.ctx.append({"role": "assistant", "content": t if t else "no reponse"})

        if is_context:
            self.sync_ctx()

        if not t and self.llm_fallback:
            return self.llm_fallback.fetch_text(
                p, system_prompt=system_prompt, custom_model=custom_model
            )

        if not t:
            raise Exception("BaashaChatInterface: Generation Failed!!")

        return t

    def _ollama_encode_image(self, img_bytes):
        """Encode image bytes to base64 for Ollama."""
        return base64.b64encode(img_bytes).decode("utf-8")

    def _ollama_fetch_text(
        self,
        p,
        is_context: bool = False,
        append_context: bool = False,
        system_prompt: Optional[str] = None,
        custom_model: Optional[str] = None,
    ):
        """Fetch text from Ollama API with multimodal support."""
        model = custom_model or self.llm_name
        messages = []

        # Add system prompt if provided
        if system_prompt or self.global_ctx:
            sys_text = system_prompt or get_global_ctx(self.global_ctx)
            if sys_text:
                messages.append({"role": "system", "content": sys_text})

        # Add context history
        if is_context and append_context and self.ctx:
            messages.extend(self.ctx)
        elif is_context and self.ctx:
            messages = self.ctx.copy()

        # Handle image input
        if isinstance(p, Img):
            img_b64 = self._ollama_encode_image(p._bytes)
            messages.append(
                {
                    "role": "user",
                    "content": p.text,
                    "images": [img_b64],
                }
            )
        elif isinstance(p, list):
            # Handle list of messages (multimodal)
            for q in p:
                if isinstance(q, Img):
                    img_b64 = self._ollama_encode_image(q._bytes)
                    messages.append(
                        {
                            "role": "user",
                            "content": q.text,
                            "images": [img_b64],
                        }
                    )
                else:
                    messages.append({"role": "user", "content": str(q)})
        else:
            messages.append({"role": "user", "content": str(p)})

        # Call Ollama API
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": 0.7,
                "num_ctx": 4096,
            },
        }

        try:
            response = requests.post(
                f"{self.ollama_host}/api/chat",
                json=payload,
                timeout=120,
            )
            response.raise_for_status()
            result = response.json()
            text = result.get("message", {}).get("content", "")

            # Update context
            if is_context:
                if append_context and self.ctx:
                    self.ctx.append(
                        {
                            "role": "user",
                            "content": str(p) if not isinstance(p, Img) else p.text,
                        }
                    )
                    self.ctx.append({"role": "assistant", "content": text})
                elif is_context:
                    self.ctx = [
                        {
                            "role": "user",
                            "content": str(p) if not isinstance(p, Img) else p.text,
                        },
                        {"role": "assistant", "content": text},
                    ]

            return text

        except Exception as e:
            logging.error(f"Ollama fetch_text error: {e}")
            if self.llm_fallback:
                return self.llm_fallback.fetch_text(
                    p, system_prompt=system_prompt, custom_model=custom_model
                )
            raise

    @errors.raise_ctx_errors
    def new_conversation(self):
        if self.llm_service.startswith(LLM_GEMINI):
            pass

        elif self.llm_service == LLM_HUGCHAT:
            self.conv = self.llm.new_conversation()

        if self.llm_fallback != None:
            self.llm_fallback.new_conversation()

    @errors.raise_ctx_errors
    def delete_conversation(self):
        if self.llm_service.startswith(LLM_GEMINI):
            pass

        elif self.llm_service == LLM_HUGCHAT and self.conv != None:
            self.llm.delete_conversation(self.conv)

        if self.llm_fallback != None:
            self.llm_fallback.delete_conversation()

    @errors.raise_ctx_errors
    def llm_list(self):
        arr = [LLM_GEMINI]

        # query hugchat
        llms = hug_chat.hugchat_model_index_list
        arr = arr + list(map(lambda x: LLM_HUGCHAT + "#" + str(x), llms))

        # free-tier providers (only listed when a key is configured)
        if any(get_keys("groq_key")):
            arr.append(LLM_GROQ)
        if any(get_keys("openrouter_key")):
            arr.append(LLM_OPENROUTER)
        if any(get_keys("cloudflare_token")):
            arr.append(LLM_CLOUDFLARE)

        # add ollama models
        try:
            response = requests.get(
                f"{app_config.get().get('auth').get('ollama_host', 'http://localhost:11434')}/api/tags",
                timeout=5,
            )
            if response.status_code == 200:
                models = response.json().get("models", [])
                for m in models:
                    name = m.get("name", "")
                    if name:
                        arr.append(f"{LLM_OLLAMA}#{name}")
        except Exception:
            pass  # ollama not available

        return arr


if __name__ == "__main__":
    import requests

    p = """"Read this Text:
"
Did Albert Einstein cheat his way to success? The truth might shock you!
"

Can you list down all the characters in the story. List down full names of characters. If a character's name is not mentioned, mention the character along with the relation to the main character of the story. Along with the name, create a description of each character's potrait, giving complete description of their face, expressions, body features and other unique details. Format it into a JSON Object with keys as name and description."""

    chatbot = ChatInterface("groq")
    chatbot.new_conversation()

    img = "https://res.cloudinary.com/aenetworks/image/upload/c_fill,ar_2,w_3840,h_1920,g_auto/dpr_auto/f_auto/q_auto:eco/v1/donald-trump-gettyimages-687193180?_a=BAVAZGDX0"
    res = requests.get(img)

    p_img = Img(
        _bytes=res.content, text="Describe the image and do entity image recognition!"
    )

    res = chatbot.fetch_text(p_img, True)

    print(res)

    # print(res)

    # res2 = chatbot.fetch_text("Can you repeat my previous question ?")

    # print(res2)

    chatbot.delete_conversation()
