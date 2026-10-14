from gtts import gTTS
from . import errors


@errors.log_ctx_errors
def tts(text, outfile, lang="en"):
    a = gTTS(text, lang=lang)
    a.save(outfile)
    return outfile


if __name__ == "__main__":
    import os

    tts("Hello!", os.path.join(os.path.dirname(__file__), "tmp", "pytts_test.wav"))
