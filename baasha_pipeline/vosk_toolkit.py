#!/usr/bin/env python3

import subprocess
import json
import os
from vosk import Model, KaldiRecognizer, SetLogLevel
from . import utils, errors
from .logger import logging

SAMPLE_RATE = 16000
WORDS_PER_LINE = 7

SetLogLevel(-1)


def timestring(seconds):
    minutes = seconds / 60
    seconds = seconds % 60
    hours = int(minutes / 60)
    minutes = int(minutes % 60)
    return "%i:%02i:%06.3f" % (hours, minutes, seconds)


@errors.raise_ctx_errors
def transcribe(file):
    model = Model(lang="en-us")
    rec = KaldiRecognizer(model, SAMPLE_RATE)
    rec.SetWords(True)

    command = [
        "ffmpeg",
        "-nostdin",
        "-loglevel",
        "quiet",
        "-i",
        file,
        "-ar",
        str(SAMPLE_RATE),
        "-ac",
        "1",
        "-f",
        "s16le",
        "-",
    ]
    with subprocess.Popen(command, stdout=subprocess.PIPE) as process:

        results = []
        while True:
            data = process.stdout.read(4000)
            if len(data) == 0:
                break
            if rec.AcceptWaveform(data):
                results.append(rec.Result())
        results.append(rec.FinalResult())

        return results


@errors.log_ctx_errors
def get_audio_timepoints(filename):
    transcribed_audio = transcribe(filename)
    timepoints = []
    if transcribed_audio == None:
        return []

    for _, res in enumerate(transcribed_audio):
        words = json.loads(res).get("result", [])

        for w in words:
            timepoints.append((w["word"], w["start"], w["end"]))

    return timepoints


if __name__ == "__main__":
    t = "It was 1928, and Fleming was working in his lab at St. Mary's Hospital in London. He had been experimenting with bacteria, and had left a petri dish containing bacteria uncovered overnight. When he returned the next morning, he noticed something strange - a mold had grown on the dish, and it had killed off the surrounding bacteria."
    t1 = "Niels Bohr, a Danish physicist, revolutionized our understanding of the atom. His model of the atom, which depicted electrons orbiting the nucleus like planets around the sun, changed the game. But it wasn't just science that made Bohr remarkable. During WWII, he fled Denmark to escape Nazi occupation, carrying his country's gold reserves on his person. He later used his influence to help Jews flee to Sweden, saving countless lives. Bohr's contributions to science and humanity make him a true legend. #NielsBohr #AtomicTheory #Heroism"
    t2 = "Meet Srinivasa Ramanujan, the Indian mathematician who revolutionized mathematics without formal training. Born in poverty, he grew up with a passion for numbers, often borrowing books from local libraries to self-study. His talent was recognized by Cambridge professor G.H. Hardy, who invited him to collaborate. Together, they produced pathbreaking research, including the Ramanujan Prime and the Ramanujan Theta functions. Despite facing discrimination and health issues, Ramanujan remained dedicated to his work, leaving behind a legacy that continues to inspire mathematicians worldwide. His story is a reminder that brilliance knows no boundaries, and that dedication can lead to groundbreaking achievements."

    t3 = "Imagine decoding one of humanity's greatest puzzles but never getting credit for it? This is the story of the overlooked genius who laid the groundwork for decoding DNA. Without whom, all those ancestry sites, genetic disorder testing and decades of evolutionary research wouldn't be possible! Enter Rosalind Franklin, Born in London in 1920, Franklin was a force to be reckoned with. With her meticulous methods and keen mind, she excelled in chemistry and physics. By the early '50s, she found herself at King's College studying DNA's molecular structures. Using innovative techniques, she produced stunning images of DNA's iconic double helix. Tragically, her accomplishments were overshadowed by her male counterparts. Two of her peers, James Watson and Francis Crick, built upon her work and claimed the glory for themselves. Yet, Franklin's influence cannot be denied. Decades later, her vital role came to light, forever changing our perception of DNA's intricate puzzle. This tale of triumph and tragedy leaves us questioning the cost of ambition and the price of recognition. Who knows what incredible revelations await in the shadows of history? The truth may surprise us all."
    t4 = "Was Tesla's greatest invention inspired by a bird's wings?"

    # a = get_audio_timepoints(
    #    os.path.join(os.path.dirname(__file__), "tmp", "test3.mp3")
    # )
    # b = utils.patch_timepoints_words_v2(t4, a)

    # print(a, "\n\n", t4, "\n\n", b)

    # t3 = "Was Tesla's greatest invention inspired by a bird's wings?"
    # a = get_audio_timepoints(
    #    os.path.join(os.path.dirname(__file__), "tmp", "test3.mp3")
    # )
    # b = utils.patch_timepoints_words_v2(t3, a)
    t5 = "But bad boy yet smart guy vibes for sure."
    a = get_audio_timepoints(
        os.path.join(os.path.dirname(__file__), "tmp", "../../../prompt_for_story.mp3")
    )
    print(" ".join(list(map(lambda a: a[0], a))))
    b = utils.patch_timepoints_words_v2(t5, a)

    print(a, "\n\n", t4, "\n\n", b)
