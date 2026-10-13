from hugchat import hugchat
from hugchat.login import Login
import importlib
import json
import os
from threading import Thread
from ..configs import app_config
from .. import errors
import time
from ..logger import logging


# Log in to huggingface and grant authorization to huggingchat
@errors.raise_ctx_errors
def login():
    email = ""
    passwd = ""
    sign = Login(email, passwd)
    cookies = sign.login()
    print(cookies)

    # Save cookies to the local directory
    cookie_path_dir = os.path.dirname(
        app_config.get().get("auth").get("hugchat_cookie")
    )
    print(cookie_path_dir)
    sign.saveCookiesToDir(cookie_path_dir)


# Create a ChatBot
@errors.raise_ctx_errors
def load_cookies():
    p = app_config.get().get("auth").get("hugchat_cookie")
    with open(p, "r") as f:
        j = json.load(f)
    return j


@errors.raise_ctx_errors
def get_chatbot():
    logging.info("HugChat: loading cookies - %s", load_cookies())
    return hugchat.ChatBot(cookies=load_cookies())


@errors.raise_ctx_errors
def fetch_text(prompt, chatbot=None, retry=1):
    if not chatbot:
        chatbot = get_chatbot()

    logging.info(f"HugChat: quering - {prompt}")

    try:
        query_result = chatbot.chat(
            prompt
            # retry_count=2,
            # stream=False,
            # ,   temperature = 1.5
            # ,   truncate = 1000
            # ,   max_new_tokens = 1024
            # ,   top_p = 0.95
            # ,   repetition_penalty = 1.2
            # ,   top_k = 50
            # ,   return_full_text = False
        )
        return query_result.wait_until_done()
    except Exception as e:
        logging.error(f"HugChat: gen error - {str(e)}")

        if retry > 0:
            logging.info("HugChat: timeout 5 sec for retry")
            time.sleep(5)
            return fetch_text(prompt, chatbot, retry - 1)

        raise Exception(f"HugChat: gen error {str(e)}")


@errors.raise_ctx_errors
def llm_list(chatbot):
    l = chatbot.get_available_llm_models()
    names = list(map(lambda x: str(x), l))
    return names


hugchat_model_index_list = [
    "meta-llama/Meta-Llama-3.1-70B-Instruct",
    "meta-llama/Meta-Llama-3.1-405B-Instruct-FP8",
    "CohereForAI/c4ai-command-r-plus",
    "mistralai/Mixtral-8x7B-Instruct-v0.1",
    "NousResearch/Nous-Hermes-2-Mixtral-8x7B-DPO",
    "01-ai/Yi-1.5-34B-Chat",
    "mistralai/Mistral-7B-Instruct-v0.3",
    "microsoft/Phi-3-mini-4k-instruct",
]

if __name__ == "__main__":
    bot = get_chatbot()
    l = llm_list(bot)
    res = fetch_text("Hi how are you ?", bot)
    print(l)
    print("chat : ", res)

    # login()
    # prompt = "Fasinating facts about blackholes!"
    # res = fetch_text(prompt)
    # print(res)
