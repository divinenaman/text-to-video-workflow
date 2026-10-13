import logging
from elevenlabs import Voice, VoiceSettings
from elevenlabs import save
from elevenlabs.client import ElevenLabs
from io import BytesIO
import os
from .configs import app_config
from . import errors
import base64
import requests

VOICES = {
    "default": "nPczCjzI2devNBz1zQrb",
    "default2": "flq6f7yk4E4fJM5XTYuZ",
}  # Adam, Charlie


@errors.raise_ctx_errors
def get_key():
    API_KEY = app_config.get().get("auth").get("eleven_labs_key")
    return API_KEY


@errors.raise_ctx_errors
def clone_voice(audio, name, desp):
    elevenlabs = ElevenLabs(
        api_key=get_key(),
    )

    voice = elevenlabs.clone(name=name, files=[audio], description=desp)

    return voice.voice_id


@errors.log_ctx_errors
def create_dialogue(text, key):
    url = "https://api.us.elevenlabs.io/v1/enhance-dialogue"
    headers = {
        "Referer": "https://elevenlabs.io/",
        "Content-Type": "application/json",
        "Origin": "https://elevenlabs.io",
        "xi-api-key": key,
    }
    data = {"dialogue_blocks": [text]}
    response = requests.post(url, headers=headers, json=data)
    response.raise_for_status()

    return response.json().get("enhanced_blocks")[0]


@errors.log_ctx_errors
def tts(text, filename, model_version="eleven_labs", voice=VOICES["default"]):
    key = get_key()
    enhanced = None

    model_id = "eleven_multilingual_v2"
    if model_version.endswith("v3"):
        model_id = "eleven_v3"

    if model_id == "eleven_v3":
        enhanced = create_dialogue(text, key)
        if enhanced:
            logging.info(f"eleven-labs-enhanced: {enhanced}")
            text = enhanced

    selected_voice = voice if voice else VOICES["default"]

    settings = VoiceSettings(stability=0.1, similarity_boost=0.75)
    voice = Voice(voice_id=selected_voice, settings=settings)

    client = ElevenLabs(api_key=key)

    res = client.text_to_speech.convert_with_timestamps(
        text=text, voice_id=selected_voice, model_id=model_id
    )

    # res = client.generate(text=text, voice=voice, model="eleven_multilingual_v2")

    audio = res.get("audio_base64", "")

    audio_bytes = base64.b64decode(audio)

    # with open(filename, "wb") as f:
    #    f.write(audio_bytes)

    save(audio=audio_bytes, filename=filename)

    if not enhanced:
        align = res.get("alignment")
        if align:
            characters = align.get("characters")
            start = align.get("character_start_times_seconds")
            end = align.get("character_end_times_seconds")

            timepoints = []
            idx = -1
            for i, c in enumerate(characters):
                if c == " ":
                    st = start[idx + 1]
                    e = end[i - 1]
                    word = "".join(characters[idx + 1 : i])
                    timepoints.append((word, st, e))

                    idx = i

            return filename, timepoints

    return filename, None


if __name__ == "__main__":

    #    with open(
    #        os.path.join(os.path.dirname(__file__), "tmp", "podcast_2.json"), "r"
    #    ) as f:
    #        pod = json.load(f)
    #        continuation = "..."
    #
    #        speakers = {}
    #        voices = list(VOICES.values())
    #
    #        ffmpeg_cmd = {"inputs": 0, "sources": "", "streams": "", "delays": []}
    #
    #        for p in pod:
    #            if not speakers.get(p[0]):
    #                speakers[p[0]] = []
    #
    #            if len(speakers[p[0]]) == 0:
    #                speakers[p[0]].append(p[1])
    #
    #            elif p[1].startswith(continuation):
    #                speakers[p[0]][-1] = speakers[p[0]][-1] + " " + p[1][3:]
    #            else:
    #                speakers[p[0]].append(p[1])
    #
    #        gens = {}
    #        voice_idx = -1
    #        for s in speakers.keys():
    #            idx = 0
    #            voice_idx += 1
    #
    #            for p in speakers[s]:
    #                name = f"podcast_{s}_{idx}"
    #                o = tts(
    #                    p,
    #                    os.path.join(os.path.dirname(__file__), "tmp", name + ".wav"),
    #                    voices[voice_idx],
    #                )
    #                idx += 1
    #                a = vosk_toolkit.get_audio_timepoints(o)
    #                b = utils.patch_timepoints_words_v2(p, a)
    #
    #                gens[name] = {"file": o.replace(" ", "\ "), "timepoints": b}
    #
    #        with open(
    #            os.path.join(os.path.dirname(__file__), "tmp", f"gens_{time.time()}.json"),
    #            "w",
    #        ) as f:
    #            json.dump(gens, f)
    #
    #        speaker_idx = {}
    #        curr_time = 0
    #        last_speech_len = 0
    #
    #        def time_by_words(g, l):
    #            if len(g) >= l:
    #                return g[l - 1][2]
    #
    #            return g[-1][2]
    #
    #        for idx, p in enumerate(pod):
    #            if not speaker_idx.get(p[0]):
    #                speaker_idx[p[0]] = (0, (0, 0))
    #
    #            f = gens[f"podcast_{p[0]}_{speaker_idx[p[0]][0]}"]
    #            t = p[1]
    #
    #            if t.startswith(continuation):
    #                l = (
    #                    speaker_idx[p[0]][1][0]
    #                    + f'<break time="{last_speech_len}s" />'
    #                    + len(t.strip().split(" "))
    #                )
    #                speaker_idx[p[0]] = (
    #                    speaker_idx[p[0]][0],
    #                    (l, time_by_words(f["timepoints"], l)),
    #                )
    #            else:
    #                ffmpeg_cmd["sources"] = ffmpeg_cmd["sources"] + f"-i {f['file']} "
    #                ffmpeg_cmd["inputs"] = ffmpeg_cmd["inputs"] + 1
    #                ffmpeg_cmd["delays"].append(
    #                    f"[{ffmpeg_cmd['inputs'] - 1}:0]adelay={curr_time}|{curr_time},asetpts=N/SR/TB[tmp{ffmpeg_cmd['inputs'] - 1}]"
    #                )
    #                ffmpeg_cmd["streams"] = (
    #                    ffmpeg_cmd["streams"] + f"[tmp{ffmpeg_cmd['inputs'] - 1}]"
    #                )
    #                l = len(t.strip().split(" "))
    #                speech_len = time_by_words(f["timepoints"], l)
    #                speaker_idx[p[0]] = (speaker_idx[p[0]][0] + 1, (l, speech_len))
    #                last_speech_len = speech_len
    #
    #            curr_time += int(speaker_idx[p[0]][1][1] * 1000)
    #
    #        output = os.path.join(
    #            os.path.dirname(__file__), "tmp", f"podcast_{time.time()}.mp3"
    #        )
    #        cmd = [
    #            "ffmpeg",
    #            ffmpeg_cmd["sources"],
    #            "-filter_complex "
    #            + f"\"{';'.join(ffmpeg_cmd['delays'])}; {ffmpeg_cmd['streams']}amix=inputs={ffmpeg_cmd['inputs']}\"",
    #            "-c:a libmp3lame",
    #            output,
    #        ]
    #
    #        print(" ".join(cmd))
    #
    #        err = subprocess.check_call(
    #            cmd, stderr=subprocess.STDOUT, stdout=subprocess.PIPE
    #        )
    #
    #        if err:
    #            print("error", err)
    #        else:
    #            print("success")
    #
    # 'ffmpeg -i audio1.mp3 -i audio2.mp3 -i audio3.mp3 -filter_complex "[0:0][1:0][2:0] adelay=0|5000|5000|10000|10000,amerge=inputs=3,pan=stereo|FL=FL+FR|FR=FL+FR" -c:a libmp3lame output.mp3'

    res = tts(
        "[excited] Google DeepMind's Genie is next-level AI—it creates 3D worlds from a simple text prompt, instantly and interactively. [chuckles] But this isn't just for gamers, businesses can use Genie for real-time prototypes, teachers can build custom virtual lessons, and robotics engineers can train bots in dynamic environments. [thoughtful] You describe it, Genie builds it. It remembers your changes and adapts in real time. Basically, if you can imagine it, Genie makes it real. [enthusiastic] Go Explore41!",
        os.path.join(os.getcwd(), "elevenTest.wav"),
        "EDJKU0p25nHYuI7ahxbE",
    )

    n = "praveen_cloud"
    d = "cloud engineer / teacher"
    aud = "audio.mp3"
    # res = clone_voice(aud, n, d)

    print(res)
