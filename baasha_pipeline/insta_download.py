from instaloader import Instaloader, Post
import os
from pathlib import Path
from .logger import logging
from uuid import uuid4
import json

L = Instaloader()
session_file = os.path.join(os.path.dirname(__file__), "tmp", "insta_session.json")


def login():
    if Path(session_file).exists():
        with open(session_file, "r") as f:
            d = json.load(f)
            logging.info("loading insta session")
            L.load_session("patakaInsta", d)
    else:
        L.login("patakaInsta", "baasha2024")
        d = L.save_session()

        logging.info("logged in insta session")
        with open(session_file, "w") as f:
            f.write(json.dumps(d))


def get_code(url):
    if url.endswith("/"):
        return url.split("/")[-2]

    return url.split("/")[-1]


def download_content(url, output):
    code = get_code(url)
    post = Post.from_shortcode(L.context, code)

    res = L.download_post(post, target=output)

    if res:
        return output
    return None


def download_reel(url):
    p = os.path.join(os.path.dirname(__file__), "tmp", str(uuid4()))
    out = download_content(url, Path(p))

    try:
        for f in os.listdir(p):
            if f.endswith("mp4"):
                return os.path.join(p, f)
    except Exception as e:
        logging.error(f"Insta-Downloader-Error: ", e)

    return None


if __name__ == "__main__":
    login()
    out = download_reel("https://www.instagram.com/_masalalab/reel/C5vzIjvurtH/")
    print(out)
