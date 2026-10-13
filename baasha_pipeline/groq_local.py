from groq import Groq
from . import errors
from .configs import app_config


def get_client(key):
    return Groq(
        api_key=key,
    )


@errors.log_ctx_errors
def fetch_text(client, ctx, text, img=None, system=None, model=None):

    def mk_text(role, text):
        return {"role": role, "content": text}

    msg = [
        {
            "role": "system",
            "content": "you are a helpful assistant." if not system else system,
        }
    ]

    for c in ctx:
        msg.append(mk_text(c[0], c[1]))

    if text:
        if img:
            text = [
                {"type": "text", "text": text},
                {"type": "image_url", "image_url": {"url": img}},
            ]
        msg.append(mk_text("user", text))

    chat_completion = client.chat.completions.create(
        messages=msg,
        model=model
        or (
            "meta-llama/llama-4-scout-17b-16e-instruct"
            if img
            else "llama-3.1-8b-instant"
        ),
    )

    return chat_completion.choices[0].message.content


@errors.log_ctx_errors
def stt(audio_file):
    client = get_client(app_config.get().get("auth").get("groq_key")[0])

    with open(audio_file, "rb") as file:
        transcription = client.audio.transcriptions.create(
            file=file,
            model="whisper-large-v3-turbo",
            # prompt="Specify context or spelling",
            response_format="verbose_json",
            timestamp_granularities=["word", "segment"],
            temperature=0.0,  # Optional
        )

        return list(
            map(lambda wd: (wd["word"], wd["start"], wd["end"]), transcription.words)
        )


if __name__ == "__main__":

    out = fetch_text(
        get_client(app_config.get().get("auth").get("groq_key")[0]),
        [],
        "Can you describe the image ?",
        "https://res.cloudinary.com/aenetworks/image/upload/c_fill,ar_2,w_3840,h_1920,g_auto/dpr_auto/f_auto/q_auto:eco/v1/donald-trump-gettyimages-687193180?_a=BAVAZGDX0",
    )

    # out = stt("tmp/sample.mp3")

    # arr = list(map(lambda x: x[0], out))

    print(out)
