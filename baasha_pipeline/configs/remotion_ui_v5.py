## V5
import os
from .utils import convert_actual_path_to_virtual

file_parent_dir = os.path.join(os.path.dirname(__file__), "..")


def get_bgm_asset_url(filename, asset_type="fonts"):
    cluster = os.environ.get("S3_CLUSTER", "localhost:9000")
    bucket = os.environ.get("BGM_BUCKET", "baasha-bgm")
    protocol = os.environ.get("S3_PROTOCOL", "https")
    return f"{protocol}://{bucket}.{cluster}/{asset_type}/{filename}"


def get_fonts(ui_config):
    if ui_config and ui_config.get("text_style", {}).get("font"):
        return [{"uri": ui_config.get("text_style").get("font"), "name": "UserFont"}]

    if ui_config and ui_config.get("font"):
        return [{"uri": ui_config.get("font"), "name": "UserFont"}]

    komikax = get_bgm_asset_url("komikax.ttf")
    return [{"uri": convert_actual_path_to_virtual(komikax), "name": "Komikax"}]


def get_asset_sizes():
    return {"images": (1080, 960), "videos": (1080, 960), "avatar": (1080, 960)}


def update_ui_props(ui_config, conf_key, curr_props):
    props = curr_props.copy()
    props.update(ui_config.get(conf_key, {}).get("props", {}))

    return props


def get_text_conf(data, idx):
    conf = data.get("text_styling")
    bold = 600
    size = 70
    marginTop = 880

    if (
        conf
        and isinstance(conf, list)
        and len(conf) > idx
        and isinstance(conf[idx], dict)
    ):
        if conf[idx].get("font_size") == "large":
            size = 140
            marginTop = 820

        if conf[idx].get("bold") == "bold":
            bold = 800

    return (size, bold, marginTop)


def get_bgm(data):
    if not data.get("bgm"):
        return []

    return [
        {
            "height": "0",
            "component": {
                "component": "audio",
                "props": {
                    "metadata": "props for background music",
                    "url": convert_actual_path_to_virtual(data["bgm"][0]),
                    "loop": True,
                    "volume": 0.2,
                },
            },
        }
    ]


def get_background_image_or_video(images, image_to_videos, search_images, idx):
    curr_image = images[idx % len(images)] if len(images) > 0 else None

    if search_images and search_images[idx]:
        s = search_images[idx]
        t = "img"
        u = search_images[idx][0]
        if len(s) > 2 and s[2]:
            t = "lottie"
            u = s[2]

        return (t, {"url": u, "backgroundColor": search_images[idx][1]})

    if image_to_videos.get(str(idx + 1)):
        return ("video", {"url": image_to_videos[str(idx + 1)]})

    if image_to_videos.get(curr_image[0]):
        return ("video", {"url": image_to_videos[curr_image[0]]})

    return (
        "img",
        {
            "url": (
                convert_actual_path_to_virtual(curr_image[0])
                if curr_image and curr_image[0]
                else None
            )
        },
    )


def get_outro_ui(ui_config, delay, compensate_time):

    outro = ui_config.get("outro")

    if not outro:
        return 0, []

    timing = delay + outro["duration"] - compensate_time

    return timing, [
        {
            "transitionType": "emerge-slide",
            "component": {
                "component": "overlay",
                "props": {
                    "children": {
                        "component": "img",
                        "props": {
                            "url": convert_actual_path_to_virtual(outro["image"]),
                            "width": "full_width",
                            "height": "full_height",
                            "wobble": False,
                            "zoomout": False,
                            "zoomduration": 0,
                            "maxzoom": 1.1,
                        },
                    },
                },
            },
            "duration": delay,
            "delay": outro["duration"] - compensate_time,
        }
    ]


def get_search_images(data, audios):
    search_images = data.get("search_images", None)

    if not search_images:
        return None

    if not isinstance(search_images, list) or len(search_images) <= 0:
        return None

    validated = []
    for s in search_images:
        if isinstance(s, tuple) or isinstance(s, list):
            validated.append(s)
        else:
            validated.append(None)

    if len(audios) > len(validated):
        validated = validated + [None] * (len(audios) - len(validated))

    return validated


def get_ui_config(data, text, audios, images, video_dur, total_time):
    is_conversation = data.get("content_type") == "conversation"

    audio_transition_delay = 0.5 if is_conversation else 0.1
    is_transition_inclusive = False if is_conversation else True
    compensate_time = audio_transition_delay if is_transition_inclusive else 0

    total_time = total_time + (
        0 if is_transition_inclusive else audio_transition_delay
    ) * len(audios)

    timepoints_map = data["timepoints_map"]
    search_images = get_search_images(data, audios)
    sound_map = data.get("sound_map", [])
    processed_sound_map = []
    prev_end = 0
    for s in sound_map:
        if s[1] >= prev_end:
            processed_sound_map.append((s[0], s[1] - prev_end, s[2] - s[1]))
            prev_end = s[2]

    is_word_timepoints = data.get("is_word_timepoints", False)

    ui_config = data.get("ui_config", {})

    font_names = ", ".join(list(map(lambda x: x["name"], get_fonts(ui_config) or [])))
    fontWithFallback = font_names + ", Noto Sans Tamil, Noto Sans"

    transitions = ["emerge-fade", "emerge-grow", "emerge-glitch"]

    narrator_avatar = data.get("narrator_avatar", {})
    if narrator_avatar and not (
        narrator_avatar.get("url") or narrator_avatar.get("url2")
    ):
        narrator_avatar = {}

    avatarFullscreenTiming = []
    if len(audios) > 0:
        start = 0
        onIdx = 0
        end = -20  # to show avatar for the first sentence
        for idx, a in enumerate(audios[0 : min(len(images), len(audios))]):
            start += float(a[1])

            if onIdx <= idx and start - end >= 3:
                end = start + (
                    audios[idx + 1][1] if idx + 1 < len(audios) else total_time
                )
                avatarFullscreenTiming.append(
                    {
                        "anim": "fullscreen",
                        "start": 0 if onIdx == 0 else start,
                        "end": end,
                        "style": {
                            "transform1": "scale(2) translateY(-240px) translateX(-50px)"
                        },
                    }
                )
                onIdx += 2

    if len(audios) > len(images):
        start = 0
        for a in audios[0 : len(images)]:
            start += float(a[1])

        avatarFullscreenTiming.append(
            {
                "anim": "fullscreen",
                "start": start,
                "end": total_time,
                "style": {
                    "transform1": "scale(2) translateY(-240px) translateX(-50px)"
                },
            }
        )

    avatar_map = None
    if data.get("character_avatar_map") and data.get("content_type") == "conversation":
        ch_map = data.get("character_avatar_map")
        for t in data["text"]:
            if not avatar_map:
                avatar_map = []

            avatar_map.append(ch_map.get(t["character"]))

    outro = get_outro_ui(ui_config, audio_transition_delay, compensate_time)

    return (
        total_time + outro[0],
        {
            "component": "parallel",
            "props": {
                "layout": "zstack",
                "style": {"background": "#000"},
                "elements": [
                    {
                        "height": "100%",
                        "component": {
                            "component": "parallel",
                            "props": {
                                "layout": "vstack",
                                "style": {"height": "100%", "backgroundColor": "black"},
                                "elements": get_bgm(data)
                                + [
                                    {
                                        "height": "0",
                                        "component": {
                                            "component": "transition_emerge",
                                            "props": {
                                                "elements": (
                                                    [
                                                        {
                                                            "component": {
                                                                "component": "audio",
                                                                "props": {
                                                                    "url": convert_actual_path_to_virtual(
                                                                        d[0]
                                                                    )
                                                                },
                                                            },
                                                            "duration": audio_transition_delay,
                                                            "delay": d[1]
                                                            - compensate_time,
                                                        }
                                                        for d in audios
                                                    ]
                                                    if not narrator_avatar.get(
                                                        "has_audio"
                                                    )
                                                    else []
                                                )
                                            },
                                        },
                                    },
                                    {
                                        "height": "0",
                                        "component": {
                                            "component": "transition",
                                            "props": {
                                                "elements": [
                                                    {
                                                        "transitionType": "emerge",
                                                        "component": {
                                                            "component": "audio",
                                                            "props": {
                                                                "url": d[0],
                                                                "loop": False,
                                                                "volume": 0.06,
                                                            },
                                                        },
                                                        "duration": d[1],
                                                        "delay": d[2],
                                                        "unmountPrevious": True,
                                                    }
                                                    for d in processed_sound_map
                                                ]
                                            },
                                        },
                                    },
                                    {
                                        "height": "100%",
                                        "component": {
                                            "component": "transition",
                                            "props": {
                                                "elements": [
                                                    {
                                                        "transitionType": (
                                                            transitions[
                                                                idx % len(transitions)
                                                            ]
                                                        ),
                                                        "component": {
                                                            "component": get_background_image_or_video(
                                                                images,
                                                                data.get(
                                                                    "image_to_videos",
                                                                    {},
                                                                ),
                                                                search_images,
                                                                idx,
                                                            )[
                                                                0
                                                            ],
                                                            "props": {
                                                                "url": get_background_image_or_video(
                                                                    images,
                                                                    data.get(
                                                                        "image_to_videos",
                                                                        {},
                                                                    ),
                                                                    search_images,
                                                                    idx,
                                                                )[
                                                                    1
                                                                ].get(
                                                                    "url"
                                                                ),
                                                                "lottieData": get_background_image_or_video(
                                                                    images,
                                                                    data.get(
                                                                        "image_to_videos",
                                                                        {},
                                                                    ),
                                                                    search_images,
                                                                    idx,
                                                                )[
                                                                    1
                                                                ].get(
                                                                    "url"
                                                                ),
                                                                "style": {
                                                                    "width": "full_width",
                                                                    "height": "auto",
                                                                    "maxHeight": "100%",
                                                                },
                                                                "width": "full_width",
                                                                "height": "auto",
                                                                "wobble": False,
                                                                "zoomOut": True,
                                                                "zoomDuration": 10
                                                                / (d[1] + 1),
                                                                "maxZoom": 1.3,
                                                            },
                                                        },
                                                        "duration": (
                                                            0
                                                            if is_conversation
                                                            else audio_transition_delay
                                                        ),
                                                        "delay": d[1]
                                                        - (
                                                            0
                                                            if is_conversation
                                                            else compensate_time
                                                        ),
                                                        "translation": 20,
                                                        "unit": "%",
                                                        "randomize": True,
                                                        "enableZoomIn": False,
                                                        "style": {
                                                            "backgroundColor": get_background_image_or_video(
                                                                images,
                                                                data.get(
                                                                    "image_to_videos",
                                                                    {},
                                                                ),
                                                                search_images,
                                                                idx,
                                                            )[
                                                                1
                                                            ].get(
                                                                "backgroundColor",
                                                                "#000000",
                                                            ),
                                                            "width": "100%",
                                                            "height": "100%",
                                                            "display": "flex",
                                                            "alignItems": "center",
                                                        },
                                                    }
                                                    for idx, d in enumerate(audios)
                                                ]
                                                + outro[1],
                                                "style": {
                                                    "width": "100%",
                                                    "height": "100%",
                                                },
                                                "crossZoom": True,
                                            },
                                        },
                                    },
                                    {
                                        "height": "100%",
                                        "component": {
                                            "component": "video",
                                            "props": {
                                                "url": convert_actual_path_to_virtual(
                                                    narrator_avatar.get(
                                                        "url",
                                                        None,
                                                    )
                                                    or narrator_avatar.get("url2", "")
                                                ),
                                                "duration": total_time,
                                                "zoomOut": False,
                                                "loop": False,
                                                "volume": 1,
                                                "style": {
                                                    "height": "100%",
                                                    "width": "auto",
                                                    "position": "absolute",
                                                    "bottom": 0,
                                                    "transform": "scale(1)",
                                                },
                                                "timedAnimation": avatarFullscreenTiming,
                                            },
                                        },
                                    },
                                ],
                            },
                        },
                    },
                    {
                        "component": {
                            "component": "transition_emerge",
                            "props": {
                                "elements": [
                                    {
                                        "component": {
                                            "component": ui_config.get(
                                                "text_style", {}
                                            ).get("name")
                                            or "subtitle_text",
                                            "props": update_ui_props(
                                                ui_config,
                                                "text_style",
                                                {
                                                    "text": d[0],
                                                    "timepoints": timepoints_map[
                                                        audios[i][0]
                                                    ],
                                                    "isWordTimepoints": is_word_timepoints,
                                                    "duration": d[1] // 2,
                                                    "style": {
                                                        "metadata": "react css style for text",
                                                        "padding": 10,
                                                        "fontSize": get_text_conf(
                                                            data, i
                                                        )[0],
                                                        "textAlign": "center",
                                                        "textShadow": "-5px -5px 0 black, 5px -5px 0 black, -5px 5px 0 black, 5px 5px 0 black",
                                                        "fontWeight": get_text_conf(
                                                            data, i
                                                        )[1],
                                                        "marginTop": get_text_conf(
                                                            data, i
                                                        )[2],
                                                    },
                                                    "color": "white",
                                                    "fontFamily": fontWithFallback,
                                                    "paginateCount": None,
                                                },
                                            ),
                                        },
                                        "duration": audio_transition_delay,
                                        "delay": d[1] - compensate_time,
                                    }
                                    for i, d in enumerate(text)
                                ],
                                "hidePrevious": True,
                                "style": {
                                    "width": "100%",
                                    "height": "100%",
                                    "display": "flex",
                                    "justifyContent": "center",
                                    "alignItems": "start",
                                    "paddingTop": "0px",
                                },
                            },
                        }
                    },
                ],
            },
        },
    )
