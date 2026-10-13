import os

file_dir = os.path.dirname(__file__)
auth_dir = os.path.join(file_dir, "..", "auth")

app_config = {
    "default_keywords": "",
    "tmp_path": os.path.normpath(os.path.join(file_dir, "..", "tmp")),
    "tts_toolkit": "gtts",
    "coqui_server": "http://localhost:8000",
    "log_path": "/tmp/baasha_pipeline.log",
    "primary_chatbot": "ollama#deepseek-r1:1.5b",
    "auth": {
        "playgroundAI_cookie": None,
        "eleven_labs_key": None,
        "object_storage": {
            "access_key": None,
            "secret_key": None,
            "cluster": None,
            "assets_bucket": "baasha-assets",
            "bgm_bucket": "baasha-bgm",
            "protocol": "https",
        },
        "slack_token": None,
        "stability_ai_key": None,
        "unreal_speech_key": None,
        "goapi_midjourney_key": "",
        "hugchat_cookie": os.path.normpath(
            os.path.join(file_dir, "..", "tmp", "hugchat.json")
        ),
        "google_genai_key": None,
        "sarvam_ai_key": None,
        "groq_key": None,
        "fal_token": None,
        "ollama_host": "http://localhost:11434",
        "hf_token": None,
    },
}


def set(key, val):
    app_config[key] = val
    return app_config


def get():
    return app_config
