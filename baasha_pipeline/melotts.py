import base64
import os
import subprocess
import tempfile

import requests

from . import errors
from .configs import app_config
from .logger import logging

MODEL = "@cf/myshell-ai/melotts"
REQUEST_TIMEOUT = 120


@errors.raise_ctx_errors
def _endpoint():
    auth_config = app_config.get().get("auth")
    token = auth_config.get("cloudflare_token")
    account_id = auth_config.get("cloudflare_account_id")
    if not token or not account_id:
        raise errors.BaashaError(
            "melotts: CLOUDFLARE_API_TOKEN / CLOUDFLARE_ACCOUNT_ID not configured"
        )
    return (
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{MODEL}",
        token,
    )


def _write_mp3(wav_bytes, outfile):
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(wav_bytes)
        wav_path = tmp.name

    try:
        run = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-i",
                wav_path,
                "-codec:a",
                "libmp3lame",
                "-qscale:a",
                "4",
                outfile,
            ],
            capture_output=True,
            timeout=60,
        )
        if run.returncode != 0:
            raise errors.BaashaError(
                f"melotts: ffmpeg failed - {run.stderr.decode()[:300]}"
            )
        if not os.path.exists(outfile) or os.path.getsize(outfile) == 0:
            raise errors.BaashaError("melotts: mp3 output is empty")
    finally:
        if os.path.exists(wav_path):
            os.unlink(wav_path)

    return outfile


@errors.log_ctx_errors
def tts(text, outfile, lang="en"):
    url, token = _endpoint()

    resp = requests.post(
        url,
        json={"prompt": text, "lang": lang},
        headers={"Authorization": f"Bearer {token}"},
        timeout=REQUEST_TIMEOUT,
    )

    if resp.status_code != 200:
        raise errors.BaashaError(
            f"melotts: HTTP {resp.status_code} - {resp.text[:300]}"
        )

    data = resp.json()
    if data.get("success") is False:
        raise errors.BaashaError(f"melotts: {str(data.get('errors'))[:300]}")

    audio_b64 = (data.get("result") or {}).get("audio")
    if not audio_b64:
        raise errors.BaashaError("melotts: no audio in response")

    logging.info(f"melotts: synthesized {len(text)} chars in lang={lang}")
    return _write_mp3(base64.b64decode(audio_b64), outfile)
