import requests
import numpy as np
import time
from google import genai
from google.genai import types
from . import errors
from .configs import app_config
from .logger import logging
from sklearn.metrics.pairwise import cosine_similarity

_client = None


def get_client():
    global _client
    if _client is None:
        keys = app_config.get().get("auth").get("google_genai_key")
        key = None
        if keys and len(keys) > 0:
            key = keys[0]

        _client = genai.Client(api_key=key)
    return _client


@errors.log_ctx_errors
def embedding_hf(text, compare_to):
    api_url = "https://router.huggingface.co/hf-inference/models/sentence-transformers/all-MiniLM-L6-v2/pipeline/sentence-similarity"

    token = app_config.get().get("auth").get("hf_token")
    headers = {"Authorization": f"Bearer {token}"}

    response = requests.post(
        api_url,
        headers=headers,
        json={"inputs": {"source_sentence": text, "sentences": compare_to}},
    )
    return response.json()


@errors.log_ctx_errors
def embedding_gemini_compare(text, compare_to):
    embeddings = embedding_gemini([text] + compare_to)
    if embeddings is None or len(embeddings) < 2:
        return []
    similarities = cosine_similarity(np.array([embeddings[0]]), embeddings[1:])
    return list(similarities[0])


@errors.log_ctx_errors
def embedding_gemini(texts, dims=384, retries=5):
    if not texts or len(texts) < 1:
        raise Exception("input not correct")

    client = get_client()

    all_embeddings = None
    for attempt in range(retries):
        try:
            res = client.models.embed_content(
                model="gemini-embedding-001",
                contents=texts,
                config=types.EmbedContentConfig(task_type="SEMANTIC_SIMILARITY"),
            )
            all_embeddings = np.array([e.values for e in res.embeddings])
            break
        except Exception as e:
            err_msg = str(e).lower()
            if (
                "504" in err_msg
                or "deadline" in err_msg
                or "exhausted" in err_msg
                or "limit" in err_msg
            ) and attempt < retries - 1:
                wait_time = (2**attempt) + 1
                logging.warning(
                    f"Gemini embedding failed (attempt {attempt+1}), retrying in {wait_time}s: {e}"
                )
                time.sleep(wait_time)
            else:
                raise e

    if all_embeddings is None:
        return None

    if isinstance(texts, str):
        return all_embeddings[0]

    return all_embeddings


if __name__ == "__main__":
    ts = ["Hi", "how are you ?", "yoyo"]
    res = embedding_gemini_compare("Hi1", ts)
    print(res)
