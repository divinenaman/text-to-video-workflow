from .google_services.ssml_markup_tts_generator import SSMLMarkupTTSGenerator
from .google_services import voices
import os
from uuid import uuid4
import requests
import random
import audioread
import json
from . import (
    eleven_labs,
    vosk_toolkit,
    gtts_local as gtts,
    object_storage,
    coqui_tts,
    melotts,
    errors,
    unreal_speech,
    sarvam_ai,
    groq_local as groq,
    replicate_api,
    gemini,
)
from .logger import logging
from .configs import app_config
from io import BytesIO
import subprocess
import base64
from .chatbot import ChatInterface
from .prompts.splitters import markdown_parse
import cv2
import numpy as np
from PIL import Image
from typing import Optional
import time

text_mappings = {"&": "and", "!": ""}

file_dir = os.path.dirname(__file__)


def is_baasha_base64(data):
    return data.startswith("baashaBase64::")


def is_baasha_json(data):
    return data.startswith("baashaJson::")


def is_baasha_encoded(data):
    return is_baasha_base64(data) or is_baasha_json(data)


def deocde_baasha_encode(data):
    if is_baasha_base64(data):
        return deocde_baasha_base64(data)
    elif is_baasha_json(data):
        return decode_baasha_json(data)
    return data


def decode_baasha_json(data):
    unprefix_data = data.split("baashaJson::")[-1]
    return json.loads(unprefix_data)


def deocde_baasha_base64(data):
    unprefix_data = data.split("baashaBase64::")[-1]
    return json.loads(base64.b64decode(unprefix_data))


def parse_media_type(uri: str):
    if uri.startswith("http"):
        return ("url", uri)

    elif uri.startswith("url-ref::"):
        return ("url_ref", uri.split("url-ref::")[-1])

    elif uri.startswith("prompt::"):
        return ("prompt", uri.split("prompt::")[-1])

    elif uri.startswith("prompt-ref::"):
        return ("prompt_ref", uri.split("prompt-ref::")[-1])

    elif uri.startswith("file::"):
        return ("file", uri.split("file::")[-1])

    else:
        return ("url", uri)


def encode_base64(data):
    return base64.b64encode(data).decode("utf-8")


def upload_base64_image(base64_uri, path):
    splits = base64_uri.split(",")
    ext = splits[0].split(":")[1].split("/")[1].split(";")[0]
    file_path = f"{path}/{uuid4()}.{ext}"
    image_bytes = base64.b64decode(splits[1])

    url = object_storage.upload_data(
        object_storage.ASSETS_IMG_BUCKET,
        image_bytes,
        file_path,
        object_storage.ACL_PUBLIC,
    )

    return url


def get_image_by_url(url, fallback=None):
    if url == None:
        return None

    checked_url = None
    try:
        request = requests.get(url, allow_redirects=True, timeout=20)
        if "html" not in str(request.content):
            checked_url = request
    except Exception as err:
        if fallback != None:
            return get_image_by_url(fallback, None)
        return None
    return checked_url


def save_image(config, img):
    if img == None:
        return None

    fname = uuid4()
    id = str(hex(random.randrange(1000)))

    file_name = os.path.join(config["tmp_path"], str(fname) + "_" + id[2:] + ".jpg")

    im = Image.open(BytesIO(img.content)).convert("RGB")
    im.save(file_name, "jpeg")

    return file_name


def replace_special_tokens(text):
    return text.replace("&", "and")


def google_text_to_speech(config, text, voice_key):
    try:
        text = list(map(lambda x: replace_special_tokens(x), text))

        generator = SSMLMarkupTTSGenerator()

        outfile_name = uuid4()
        output_file = os.path.join(config["tmp_path"], f"{outfile_name}_audio.mp3")

        audio = voices.google_tts_voice_dict["AUDIO_CONFIG_QUICK_FACTS"]
        voice = voices.google_tts_voice_dict.get(
            voice_key, voices.google_tts_voice_dict["RHEA_IN_FEMALE"]
        )

        audio_info = generator.generate(
            text, output_file, audio, voice, split_lines=True, store_ssml=True
        )
        silence_timepoints = True
        return audio_info, not silence_timepoints
    except Exception as e:
        raise e


def get_outpath(ext="mp3", config=app_config.get()):
    uid = uuid4()
    output_file = os.path.join(config["tmp_path"], f"{uid}_audio.{ext}")

    return output_file


@errors.raise_ctx_errors
def text_to_speech(
    config, text, voice_key=None, tts_toolkit=None, voice_description=None
):

    toolkit = tts_toolkit or config.get("tts_toolkit")
    lang = config.get("tts_lang") or "en"
    logging.info(f"Selected audio toolkit : {toolkit} (lang={lang})")

    if toolkit == "google":
        text = list(map(lambda x: replace_special_tokens(x), text))
        return google_text_to_speech(config, text, voice_key)

    audio_info = []
    word_timepoints = False

    try:
        chatbot = ChatInterface()
        chatbot.new_conversation()

        spellout_prompt = "Given a script in mixed language. Spell out all the numbers in the script using the primary language of the script. Do not change any other text/word/phrase/language in the script except numbers. Output the new script as json with key script enclosed with ```json\nScript: "
    except:
        pass

    for tt in text:
        t = tt
        try:
            output = chatbot.fetch_text(spellout_prompt + tt)
            parsed_out = json.loads(markdown_parse(output))
            if parsed_out.get("script"):
                t = parsed_out.get("script")
        except Exception:
            pass

        output_file = get_outpath("mp3")
        timepoints = None
        logging.info(f"BaashaUtils-tts: running tts on `{t}`")

        if toolkit.startswith("eleven_labs"):
            f, timepoints = eleven_labs.tts(
                text=t, filename=output_file, voice=voice_key, model_version=tts_toolkit
            )

        elif toolkit == "unreal_speech":
            output_file = unreal_speech.generate_audio(t, voice_key)

        elif toolkit.startswith("replicate"):
            output_file = replicate_api.text_to_speech(t, voice_key)

        elif toolkit == "sarvam_ai":
            output_file = sarvam_ai.tts(t, output_file, voice_key)

        elif toolkit == "gemini":
            output_file, timepoints = gemini.tts(
                t, output_file, voice_key, voice_description=voice_description
            )
            time.sleep(30)

        elif toolkit == "coqui":
            if coqui_tts.healthy():
                coqui_file = coqui_tts.tts(text=t)

            if coqui_file == None:
                logging.info(f"error while coqui-tts for `{t}`, falling back to gtts")
                gtts.tts(t, output_file, lang)
            else:
                output_file = coqui_file

        elif toolkit == "melotts":
            if melotts.tts(t, output_file, lang) is None:
                logging.info(f"error while melotts for `{t}`, falling back to gtts")
                gtts.tts(t, output_file, lang)

        elif toolkit == "gtts":
            gtts.tts(t, output_file, lang)

        # upload to object storage
        public_url = object_storage.upload_file(
            object_storage.ASSETS_AUDIO_BUCKET,
            output_file,
            os.path.basename(output_file),
            object_storage.ACL_PUBLIC,
        )

        if not timepoints:
            # whisper transcription
            timepoints = groq.stt(output_file)

            if not timepoints:
                timepoints = vosk_toolkit.get_audio_timepoints(output_file)

        patched_timepoints = None
        if timepoints == None:
            logging.info("error while timepoint generation, skipping word patch")
        else:
            patched_timepoints = patch_timepoints_words_v2(tt, timepoints)

        if patched_timepoints == None:
            patched_timepoints = timepoints or []

        word_timepoints = True
        audio_info.append((public_url, output_file, patched_timepoints))

    return audio_info, word_timepoints


def process_text(t):
    t = t.replace(",", " ")
    t = t.replace(".", " ")
    t = t.replace("?", " ")
    t = t.strip()
    return t


@errors.log_ctx_errors
def patch_timepoints_words_v2(text, wordTimepoints):
    words = list(filter(lambda x: x != "", process_text(text).split(" ")))

    transcriped_words = list(map(lambda x: x[0].lower(), wordTimepoints))
    patched_timepoints = []
    last_match_idx = -1
    start_idx = 0
    last_end_time = 0
    for i, w in enumerate(words):
        try:
            if len(w) < 2 and i < len(words) - 1:
                continue

            match_idx = None
            for j in range(
                last_match_idx + 1,
                min(last_match_idx + 8 + i - start_idx, len(transcriped_words)),
            ):
                if w.lower().startswith(transcriped_words[j]) or transcriped_words[
                    j
                ].startswith(w.lower()):
                    diff = abs(len(w) - len(transcriped_words[j]))
                    if diff < 2:
                        match_idx = j

                    if diff == 0:
                        break

            if match_idx == None:
                raise Exception("no matching word")

            if start_idx < i:
                # same number of words
                if match_idx - last_match_idx - 1 == i - start_idx:
                    for j in range(i - start_idx):
                        patched_timepoints.append(
                            (
                                words[start_idx + j],
                                wordTimepoints[last_match_idx + 1 + j][1],
                                wordTimepoints[last_match_idx + 1 + j][2],
                            )
                        )
                else:
                    total_chacters = 0
                    for wr in words[start_idx:i]:
                        total_chacters = total_chacters + len(wr)

                    offset = (
                        wordTimepoints[match_idx][1] - last_end_time
                    ) / total_chacters
                    offset_start = last_end_time
                    for e in words[start_idx:i]:
                        patched_timepoints.append(
                            (e, offset_start, offset_start + offset * len(e))
                        )
                        offset_start = offset_start + offset * len(e)

            patched_timepoints = patched_timepoints + [
                (
                    words[i],
                    wordTimepoints[match_idx][1],
                    wordTimepoints[match_idx][2],
                )
            ]
            last_end_time = wordTimepoints[match_idx][2]
            last_match_idx = match_idx
            start_idx = i + 1
        except Exception as e:
            if i == len(words) - 1:
                i = i + 1
                if start_idx < i:
                    # same number of words
                    if len(transcriped_words) - last_match_idx - 1 == i - start_idx:
                        for j in range(i - start_idx):
                            patched_timepoints.append(
                                (
                                    words[start_idx + j],
                                    wordTimepoints[last_match_idx + 1 + j][1],
                                    wordTimepoints[last_match_idx + 1 + j][2],
                                )
                            )
                    else:
                        total_chacters = 0
                        for wr in words[start_idx:i]:
                            total_chacters = total_chacters + len(wr)

                        offset = (
                            wordTimepoints[-1][2] - last_end_time
                        ) / total_chacters
                        offset_start = last_end_time
                        for e in words[start_idx:i]:
                            patched_timepoints.append(
                                (e, offset_start, offset_start + offset * len(e))
                            )
                            offset_start = offset_start + offset * len(e)

    return patched_timepoints


@errors.raise_ctx_errors
def map_audio_timepoints(tupled_audio_timepoints):
    audios = []
    local_audios = []
    timepoint_map = {}
    for audio, local_path, timepoint in tupled_audio_timepoints:
        audios.append(audio)
        local_audios.append(local_path)
        timepoint_map[audio] = timepoint

    return audios, local_audios, timepoint_map


@errors.raise_ctx_errors
def get_media_duration(filename):
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            filename,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    return float(result.stdout)


@errors.log_ctx_errors
def get_image_dims_from_bytes(byts):
    im = Image.open(BytesIO(byts))
    return im.size


@errors.log_ctx_errors
def get_aspect_ratio(content_type: str, url: str) -> Optional[float]:
    response = requests.get(url, stream=True)
    response.raise_for_status()

    if content_type == "image":
        from PIL import Image
        from io import BytesIO

        image = Image.open(BytesIO(response.content))
        width, height = image.size
        return width / height
    elif content_type == "video":
        import cv2
        import tempfile

        with tempfile.NamedTemporaryFile(delete=False) as tmpfile:
            for chunk in response.iter_content(chunk_size=8192):
                tmpfile.write(chunk)
            tmp_filename = tmpfile.name

        cap = cv2.VideoCapture(tmp_filename)
        if not cap.isOpened():
            os.unlink(tmp_filename)
            return None

        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()
        os.unlink(tmp_filename)

        if height == 0:
            return None
        return width / height
    else:
        return None


def loop_video_by_time(video, to_time, outpath=None):
    dur = get_media_duration(video)
    loop = int(to_time // dur + (1 if to_time % dur > 0 else 0))

    if outpath == None:
        ext = video.split(".")[-1]
        f = f"video_looped_{str(uuid4()).replace('-', '1')}.{ext}"
        outpath = os.path.join(file_dir, "tmp", f)

    cmds = [
        "ffmpeg",
        "-stream_loop",
        f"{loop}",
        "-i",
        f"{video}",
        "-c",
        "copy",
        f"{outpath}",
    ]

    err = subprocess.check_call(cmds, stderr=subprocess.STDOUT, stdout=subprocess.PIPE)

    if err:
        print("error", err)
        return None

    return (outpath, loop * dur)


def video_to_audio(video_file):
    output = os.path.join(os.path.dirname(__file__), "tmp", str(uuid4()) + ".wav")
    cmds = ["ffmpeg", "-i", video_file, output]
    err = subprocess.check_call(cmds, stderr=subprocess.STDOUT, stdout=subprocess.PIPE)

    if err:
        logging.error(f"video-to-audio-error: {err}")
        return None

    return output


def download_media_by_url(
    url, fallback_ext="mp4", force_ext=None, config=app_config.get()
):

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.164 Safari/537.36",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.5",
    }

    r = requests.get(url.strip(), headers=headers, verify=True)

    logging.info(f"media status {url} -> {r.status_code}")
    if r.status_code != 200:
        return None

    ctype = r.headers["content-type"]

    if force_ext:
        ext = force_ext
    else:
        ext = ctype.split("/")[-1] if ctype else fallback_ext

    filename = f"media_{uuid4()}.{ext}"
    outpath = os.path.join(config["tmp_path"], filename)

    with open(outpath, "wb") as f:
        for chunk in r.iter_content(chunk_size=1024):
            if chunk:
                f.write(chunk)
    return outpath


def image_url_to_base64_data(url):
    img = download_media_by_url(url, "jpg")
    img_content = open(img, "rb").read()
    ext = img.split(".")[-1]
    return f"data:image/{ext};base64,{encode_base64(img_content)}"


def pngs_to_webm(frame_dir, fps):
    logging.info("converting png to webm")
    output_file = os.path.join(
        os.path.dirname(__file__), "tmp", f"video_{str(uuid4())}.webm"
    )

    # Use ffmpeg to create a webm video from the png files
    command = [
        "ffmpeg",
        "-framerate",
        str(fps),
        "-i",
        os.path.join(frame_dir, "frame_%04d.png"),
        "-c:v",
        "libvpx-vp9",
        "-lossless",
        "1",
        "-auto-alt-ref",
        "0",
        output_file,
    ]

    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
        logging.info(f"Successfully created {output_file}")
    except Exception as e:
        logging.error(f"Error creating webm video: {e}")
        return None

    return output_file


def chroma_key(input_video):
    # Create a temporary directory for the frames
    output_video = None

    frame_dir = os.path.join(os.path.dirname(__file__), "tmp", "frames_" + str(uuid4()))
    os.makedirs(frame_dir, exist_ok=True)

    try:
        cap = cv2.VideoCapture(input_video)

        if not cap.isOpened():
            logging.info(f"Error: Could not open video file: {input_video}")
            return None

        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_count = 0

        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break

            frame = cv2.imread("img.png")

            # 2. Define the bounds (using your yellow/green ranges)
            lower_green = np.array([0, 180, 180])
            upper_green = np.array([120, 255, 255])

            # 3. Create the initial mask based on color
            mask_1 = cv2.inRange(frame, lower_green, upper_green)

            # kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (200, 200))
            # mask_2 = cv2.morphologyEx(mask_1, cv2.MORPH_CLOSE, kernel)
            # coords = cv2.findNonZero(mask_1)
            # mask_2 = cv2.convexHull(coords)
            #
            ## 4. Find the contours of that "white border"
            ## RETR_EXTERNAL gets the outermost boundary
            ## contours, _ = cv2.findContours(mask_2, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            ## 5. Create a solid white silhouette
            ## This fills the space between the borders
            # clean_mask = np.zeros(mask_1.shape, dtype=np.uint8)
            # cv2.drawContours(clean_mask, [mask_2], -1, 255, thickness=cv2.FILLED)

            clean_mask = np.zeros_like(mask_1)

            # Loop through every row in the mask
            for y in range(mask_1.shape[0]):
                # Find all yellow pixels in this specific row
                row_pixels = np.where(mask_1[y, :] > 0)[0]

                if len(row_pixels) > 1:
                    # Get the first and last yellow pixel in this row
                    x_start = row_pixels[0]
                    x_end = row_pixels[-1]

                    # Fill everything in between with white
                    clean_mask[y, x_start:x_end] = 255

            # 6. APPLY TO ORIGINAL FRAME
            # Convert original BGR frame to BGRA (adds the Alpha/Transparency channel)
            foreground_layer = cv2.cvtColor(frame, cv2.COLOR_BGR2BGRA)

            # Put the solid filled mask into the Alpha channel (index 3)
            # 255 = Keep color, 0 = Transparent
            foreground_layer[:, :, 3] = clean_mask

            # 7. Save the outputs
            cv2.imwrite("mask.png", mask_1)  # The original detection
            cv2.imwrite("mask1.png", clean_mask)  # The solid filled stencil
            cv2.imwrite("final_foreground.png", foreground_layer)  # The color cutout

            # Apply the mask to the frame
            # Ensure the frame is BGR format before applying the mask
            try:
                foreground = cv2.bitwise_and(frame, frame, mask=mask_inv)

                mask_2 = cv2.inRange(foreground, lower_green_1, upper_green_1)
                foreground_patched = cv2.bitwise_and(
                    foreground, foreground, mask=cv2.bitwise_not(mask_2)
                )

                foreground_rgba = cv2.cvtColor(foreground_patched, cv2.COLOR_BGR2BGRA)
                # set alpha channel
                foreground_rgba[:, :, 3] = clean_mask

                # Save the frame as a PNG
                frame_path = os.path.join(frame_dir, f"frame_{frame_count:04d}.png")
                cv2.imwrite(frame_path, foreground_rgba)

                frame_count += 1
            except Exception as e:
                logging.error(f"Error processing frame: {e}")
                break

            break

        cap.release()
        cv2.destroyAllWindows()

        output_video = pngs_to_webm(frame_dir, fps)

    except Exception as e:
        logging.error(f"error while performing chroma_key: {e}")

    finally:
        import shutil

        shutil.rmtree(frame_dir)

    # Convert the frames to a webm video
    return output_video


@errors.log_ctx_errors
def remove_background_using_border(img_path, output_path):
    frame = cv2.imread(img_path)

    # 2. Define the bounds (using your yellow/green ranges)
    lower_yellow = np.array([0, 160, 160])
    upper_yellow = np.array([120, 255, 255])

    # 3. Create the initial mask based on color
    mask_1 = cv2.inRange(frame, lower_yellow, upper_yellow)

    clean_mask = np.zeros_like(mask_1)

    for _ in range(1):
        prev_visible_row = []
        prev_visible_col = None

        # Loop through every row in the mask
        for y in range(mask_1.shape[0]):
            # Find all yellow pixels in this specific row
            row_pixels = np.where(mask_1[y, :] > 0)[0]

            if (
                len(prev_visible_row) > 0
                and len(row_pixels) == 1
                and y - prev_visible_row[-1][0] <= 5
            ):

                diff1 = abs(prev_visible_row[-1][1] - row_pixels[0])
                diff2 = abs(prev_visible_row[-1][2] - row_pixels[0])
                bound = prev_visible_row[-1][1]
                if diff2 < diff1:
                    bound = prev_visible_row[-1][2]

                row_pixels = [min(row_pixels[0], bound), max(row_pixels[0], bound)]

            if len(row_pixels) > 1:
                # Get the first and last yellow pixel in this row
                x_start = row_pixels[0]
                x_end = row_pixels[-1]

                # Fill everything in between with white
                clean_mask[y, x_start:x_end] = 255

                prev_visible_row.append((y, x_start, x_end))

        # Loop through every row in the mask
        for x in range(mask_1.shape[1]):
            # Find all yellow pixels in this specific row
            col_pixels = np.where(clean_mask[:, x] > 0)[0]

            # if (
            #    prev_visible_col
            #    and len(col_pixels) <= 1
            #    and x - prev_visible_col[0] <= 1
            # ):
            #    if len(col_pixels) == 1:
            #        col_pixels = [
            #            min(col_pixels[0], prev_visible_col[1]),
            #            max(col_pixels[0], prev_visible_col[2]),
            #        ]
            #    else:
            #        col_pixels = [prev_visible_col[1], prev_visible_col[2]]

            if len(col_pixels) > 1:

                group = [col_pixels[0]]
                max_group = []
                for c in range(1, len(col_pixels)):
                    if col_pixels[c] - group[-1] < 250:
                        group.append(col_pixels[c])
                    elif len(max_group) < len(group):
                        max_group = group
                        group = [col_pixels[c]]

                if len(max_group) < len(group):
                    max_group = group

                if len(max_group) < 2:
                    continue

                col_pixels = max_group

                # Get the first and last yellow pixel in this row
                y_start = col_pixels[0]
                y_end = col_pixels[-1]

                # Fill everything in between with white
                clean_mask[y_start:y_end, x] = 255

                prev_visible_col = (x, y_start, y_end)

        mask_1 = clean_mask

    # 6. APPLY TO ORIGINAL FRAME
    # Convert original BGR frame to BGRA (adds the Alpha/Transparency channel)
    foreground_layer = cv2.cvtColor(frame, cv2.COLOR_BGR2BGRA)

    # Put the solid filled mask into the Alpha channel (index 3)
    # 255 = Keep color, 0 = Transparent
    foreground_layer[:, :, 3] = clean_mask

    # 7. Save the outputs
    cv2.imwrite(output_path, foreground_layer, [cv2.IMWRITE_PNG_COMPRESSION, 1])

    return output_path


if __name__ == "__main__":
    # print(
    #    text_to_speech(
    #        app_config.get(),
    #        ["Bharat Jodo Yatra begins Jammu & Kashmir leg", "Test", "1"],
    #    )
    # )
    # v = os.path.join(file_dir, "tmp", "vid.mp4")
    # a = download_media_by_url(
    #    "https://file-examples.com/storage/fe58a1f07d66f447a9512f1/2017/11/file_example_MP3_700KB.mp3"
    # )
    # b = get_media_duration(a)

    t = "Look brother, Nifty50 is currently in a bullish zone, with a resistance level at 22,750 to 22,800. If it breaks through this, there's a possibility it could go up to 23,000."

    tt = [
        ("\nLook", 0.0, 0.255),
        ("brother,", 0.302, 0.766),
        ("Nifty", 1.149, 1.486),
        ("fifty", 1.556, 1.881),
        ("is", 1.927, 2.02),
        ("currently", 2.078, 2.45),
        ("in", 2.508, 2.566),
        ("a", 2.601, 2.635),
        ("bullish", 2.705, 3.042),
        ("zone,", 3.1, 3.576),
        ("with", 3.959, 4.122),
        ("a", 4.156, 4.191),
        ("resistance", 4.261, 4.865),
        ("level", 4.911, 5.19),
        ("at", 5.248, 5.329),
        ("twenty-two", 5.375, 5.77),
        ("thousand,", 5.84, 6.362),
        ("seven", 6.803, 7.105),
        ("hundred", 7.163, 7.407),
        ("and", 7.43, 7.5),
        ("fifty", 7.558, 7.848),
        ("to", 7.883, 7.93),
        ("twenty-two", 7.964, 8.324),
        ("thousand,", 8.382, 8.893),
        ("eight", 9.334, 9.543),
        ("hundred.", 9.578, 9.961),
        ("If", 10.658, 10.797),
        ("it", 10.855, 10.925),
        ("breaks", 10.971, 11.215),
        ("through", 11.25, 11.471),
        ("this,", 11.505, 11.865),
        ("there's", 11.958, 12.19),
        ("a", 12.214, 12.249),
        ("possibility", 12.318, 13.038),
        ("it", 13.084, 13.131),
        ("could", 13.166, 13.305),
        ("go", 13.351, 13.479),
        ("up", 13.56, 13.665),
        ("to", 13.723, 13.781),
        ("twenty-three", 13.851, 14.303),
    ]

    # a = patch_timepoints_words_v2(t, tt)
    # print(a)

    # Example usage:
    input_video = "video.mp4"
    # out = chroma_key(input_video)

    out = remove_background_using_border("dhoni.png", "img_edit.png")

    print(out)
