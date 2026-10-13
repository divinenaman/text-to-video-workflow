import os
from google.ai.generativelanguage import CustomMetadata

from google.generativeai.types.content_types import image_to_blob
from .utils import convert_actual_path_to_virtual
from functools import reduce

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


def update_ui_props(ui_config, conf_key, curr_props):
    props = curr_props.copy()
    props.update(ui_config.get(conf_key, {}).get("props", {}))

    return props


def get_asset_sizes():
    return {"images": (1080, 1920), "videos": (1080, 1920), "avatar": (1080, 1920)}


def get_bgm(data):
    if not data.get("bgm"):
        return []

    return [
        {
            "component": {
                "component": "audio",
                "props": {
                    "metadata": "props for background music",
                    "url": convert_actual_path_to_virtual(data["bgm"][0]),
                    "loop": True,
                    "volume": 0.3,
                },
            }
        }
    ]


def get_background_image(ui_config):
    if not ui_config.get("background_image"):
        return []

    return [
        {
            "component": {
                "component": "img",
                "props": {
                    "metadata": "props for background image",
                    "url": convert_actual_path_to_virtual(
                        ui_config.get("background_image")
                    ),
                    "width": "full_width",
                    "height": "full_height",
                },
            }
        }
    ]


def get_background_image_or_video(images, image_to_videos, idx):
    curr_image = images[idx % len(images)] if len(images) > 0 else None

    if not curr_image:
        return ("img", None, None)

    if image_to_videos.get(str(idx + 1)):
        return ("video", image_to_videos[str(idx + 1)], None)

    if image_to_videos.get(curr_image[0]):
        return ("video", image_to_videos[curr_image[0]], None)

    return (
        "img",
        (
            convert_actual_path_to_virtual(curr_image[0])
            if curr_image and curr_image[0]
            else None
        ),
        curr_image[1] if curr_image else None,
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
    default = ("img", None, None, None)

    if not search_images:
        return None

    if not isinstance(search_images, list) or len(search_images) <= 0:
        return None

    validated = []
    for i, s in enumerate(search_images):
        if isinstance(s, tuple) or isinstance(s, list):
            if len(s) > 2:
                viewType = "lottie" if s[2] else "img"
                validated.append((viewType, s[0], s[1], s[2]))
            else:
                validated.append(("img", s[0], s[1], None))
        else:
            validated.append(default)

    if len(audios) > len(validated):
        validated = validated + [default] * (len(audios) - len(validated))

    return validated


def get_ui_config(data, text, audios, images, video_dur, total_time):
    content_type = data.get("content_type")
    is_conversation = content_type == "conversation"
    is_slides = content_type == "slides"

    audio_transition_delay = 0.5 if is_conversation else 0.1
    is_transition_inclusive = False if is_conversation else True
    compensate_time = audio_transition_delay if is_transition_inclusive else 0

    total_time = total_time + (
        0 if is_transition_inclusive else audio_transition_delay
    ) * len(audios)

    timepoints_map = data["timepoints_map"]
    search_images = None  # get_search_images(data, audios)
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

    transitions = ["emerge-fade", "emerge-grow", "emerge-slide", "emerge-fade"]

    narrator_avatar = data.get("narrator_avatar", {})
    if narrator_avatar and not (
        narrator_avatar.get("url") or narrator_avatar.get("url2")
    ):
        narrator_avatar = {}

    primary_asset = []
    img_to_videos = data.get(
        "image_to_videos",
        {},
    )
    image_layers = data.get("image_layers", [])

    image_focus_directions = data.get("image_focus_directions", []) or []
    for idx, a in enumerate(audios):
        asset = get_background_image_or_video(
            images,
            img_to_videos,
            idx,
        )
        primary_asset.append(asset)

    avatarFullscreenTiming = []
    avatar_fullscreen_scenes = []
    if len(audios) > 0:
        start = 0
        onIdx = 0
        end = -20  # to show avatar for the first sentence
        for idx, a in enumerate(audios):
            start += float(a[1])

            if (
                (not primary_asset[idx] or not primary_asset[idx][1])
                or (idx == len(audios) - 1)
                or (onIdx <= idx and start - end >= 3)
            ):
                end = (
                    start
                    + (audios[idx + 1][1] if idx + 1 < len(audios) else total_time)
                    + audio_transition_delay * 3
                )
                avatarFullscreenTiming.append(
                    {
                        "anim": "fullscreen",
                        "start": 0 if onIdx == 0 else start,
                        "end": end,
                        "style": {"opacity": 1},
                    }
                )
                avatar_fullscreen_scenes.append(idx)
                onIdx += 2

    avatar_map = None
    if data.get("character_avatar_map") and is_conversation:
        ch_map = data.get("character_avatar_map")
        for t in data["text"]:
            if not avatar_map:
                avatar_map = []

            avatar_map.append(ch_map.get(t["character"]))

    outro = get_outro_ui(ui_config, audio_transition_delay, compensate_time)

    image_size = get_asset_sizes()["images"]

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
                                "layout": "zstack",
                                "style": {"background": "#000", "height": "100%"},
                                "elements": get_bgm(data)
                                + get_background_image(ui_config)
                                + [
                                    {
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
                                        }
                                    },
                                    {
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
                                                                "volume": 0.5,
                                                            },
                                                        },
                                                        "duration": d[1],
                                                        "delay": d[2],
                                                        "unmountPrevious": True,
                                                    }
                                                    for d in processed_sound_map
                                                ]
                                            },
                                        }
                                    },
                                    {
                                        "component": {
                                            "component": "transition",
                                            "props": {
                                                "elements": [
                                                    {
                                                        "transitionType": transitions[
                                                            idx % len(transitions)
                                                        ],
                                                        "component": {
                                                            "component": "overlay",
                                                            "props": {
                                                                "children": {
                                                                    "component": primary_asset[
                                                                        idx
                                                                    ][
                                                                        0
                                                                    ],
                                                                    "props": {
                                                                        "url": primary_asset[
                                                                            idx
                                                                        ][
                                                                            1
                                                                        ],
                                                                        "ar": primary_asset[
                                                                            idx
                                                                        ][
                                                                            2
                                                                        ],
                                                                        "focusPoint": (
                                                                            image_focus_directions[
                                                                                idx
                                                                            ]
                                                                            if len(
                                                                                image_focus_directions
                                                                            )
                                                                            > idx
                                                                            else "middle"
                                                                        ),
                                                                        "layers": (
                                                                            image_layers[
                                                                                idx
                                                                            ]
                                                                            if len(
                                                                                image_layers
                                                                            )
                                                                            > idx
                                                                            else None
                                                                        ),
                                                                        "style": {
                                                                            "width": "auto",
                                                                            "height": image_size[
                                                                                1
                                                                            ],
                                                                            "transform": (
                                                                                f"translateX({-1 * (0.5 * (primary_asset[idx][2] * image_size[1] - image_size[0]))}px)"
                                                                                if primary_asset[
                                                                                    idx
                                                                                ][
                                                                                    2
                                                                                ]
                                                                                else None
                                                                            ),
                                                                        },
                                                                        "width": "auto",
                                                                        "height": image_size[
                                                                            1
                                                                        ],
                                                                        "wobble": (
                                                                            False
                                                                            if idx % 2
                                                                            == 0
                                                                            else True
                                                                        ),
                                                                        "zoomOut": (
                                                                            True
                                                                            if idx % 2
                                                                            == 0
                                                                            else False
                                                                        ),
                                                                        "wobbleDuration": d[
                                                                            1
                                                                        ],
                                                                        "zoomDuration": d[
                                                                            1
                                                                        ],
                                                                        "maxZoom": (
                                                                            1.6
                                                                            if is_slides
                                                                            else 1.2
                                                                        ),
                                                                        "useAutoCorrectPositioning": False,
                                                                        "autoCorrectPositionDuration": d[
                                                                            1
                                                                        ],
                                                                    },
                                                                },
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
                                                        "unmountPrevious": False,
                                                        "style": {"width": "100%"},
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
                                        }
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
                                                "ar": narrator_avatar.get("ar"),
                                                "style": {
                                                    "height": "100%",
                                                    "width": "auto",
                                                    "position": "absolute",
                                                    "bottom": 0,
                                                    "opacity": 0,  # default invisible
                                                },
                                                "timedAnimation": avatarFullscreenTiming,
                                                "useAutoCorrectPositioning": True,
                                            },
                                        },
                                    },
                                    (
                                        {
                                            "component": {
                                                "component": "transition",
                                                "props": {
                                                    "elements": [
                                                        {
                                                            "tag": "search_images",
                                                            "transitionType": "emerge-slide",
                                                            "component": {
                                                                "component": (
                                                                    search_images[idx][
                                                                        0
                                                                    ]
                                                                    if search_images[
                                                                        idx
                                                                    ]
                                                                    else "img"
                                                                ),
                                                                "props": {
                                                                    "url": search_images[
                                                                        idx
                                                                    ][
                                                                        1
                                                                    ],
                                                                    "lottieData": search_images[
                                                                        idx
                                                                    ][
                                                                        3
                                                                    ],
                                                                    "width": (
                                                                        "full_width"
                                                                        if avatar_map
                                                                        else "auto"
                                                                    ),
                                                                    "height": (
                                                                        "auto"
                                                                        if avatar_map
                                                                        else "100%"
                                                                    ),
                                                                    "wobble": False,
                                                                    "zoomOut": True,
                                                                    "zoomDuration": d[1]
                                                                    * 1.2,
                                                                    "maxZoom": 1.3,
                                                                },
                                                            },
                                                            "duration": (
                                                                d[1]
                                                                + (
                                                                    0
                                                                    if is_conversation
                                                                    else audio_transition_delay
                                                                )
                                                            )
                                                            // 2.2,
                                                            "delay": (
                                                                d[1]
                                                                - (
                                                                    0
                                                                    if is_conversation
                                                                    else compensate_time
                                                                )
                                                            )
                                                            * 0.8,
                                                            "style": {
                                                                "backgroundColor": (
                                                                    search_images[idx][
                                                                        2
                                                                    ]
                                                                    if search_images[
                                                                        idx
                                                                    ]
                                                                    else "#00000000"
                                                                ),
                                                                "width": "90%",
                                                                "padding": 15,
                                                                "marginBottom": 30,
                                                                "height": "auto",
                                                                "display": (
                                                                    "flex"
                                                                    if search_images[
                                                                        idx
                                                                    ][1]
                                                                    else "none"
                                                                ),
                                                                "alignItems": "center",
                                                                "justifyContent": "center",
                                                                "overflow": "hidden",
                                                                "position": "relative",
                                                                "borderRadius": "30px",
                                                            },
                                                            "unmountPrevious": True,
                                                            "hidePrevious": True,
                                                        }
                                                        for idx, d in enumerate(audios)
                                                    ],
                                                    "style": {
                                                        "width": "100$",
                                                        "height": "100%",
                                                        "display": "flex",
                                                        "justifyContent": "center",
                                                        "alignItems": (
                                                            "flex-end"
                                                            if avatar_map
                                                            else "center"
                                                        ),
                                                        "overflow": "hidden",
                                                    },
                                                },
                                            }
                                        }
                                        if search_images
                                        else {}
                                    ),
                                    (
                                        {
                                            "component": {
                                                "component": "transition",
                                                "props": {
                                                    "elements": [
                                                        {
                                                            "transitionType": "emerge-slide",
                                                            "component": {
                                                                "component": "img",
                                                                "props": {
                                                                    "url": avatar_map[
                                                                        idx
                                                                    ],
                                                                    "width": "auto",
                                                                    "height": 1920 / 4,
                                                                    "wobble": False,
                                                                    "zoomOut": True,
                                                                    "zoomDuration": d[1]
                                                                    * 2,
                                                                    "maxZoom": 1.3,
                                                                },
                                                            },
                                                            "duration": 2,
                                                            "delay": max(d[1] - 2, 0),
                                                            "translation": 1000,
                                                            "unit": "px",
                                                            "randomize": True,
                                                            "enableZoomIn": False,
                                                            "style": {
                                                                "bottom": "100px",
                                                                "overflow": "hidden",
                                                                "position": "relative",
                                                                "borderRadius": "30px",
                                                            },
                                                        }
                                                        for idx, d in enumerate(audios)
                                                    ],
                                                    "style": {
                                                        "width": "100%",
                                                        "height": "100%",
                                                        "display": "flex",
                                                        "padding": 30,
                                                        "justifyContent": "center",
                                                        "alignItems": "center",
                                                    },
                                                    "crossZoom": True,
                                                    "hidePrevious": True,
                                                },
                                            }
                                        }
                                        if avatar_map
                                        else {}
                                    ),
                                    (
                                        {
                                            "component": {
                                                "component": "transition",
                                                "props": {
                                                    "elements": [
                                                        {
                                                            "transitionType": "emerge-slide",
                                                            "component": {
                                                                "component": "audio",
                                                                "props": {
                                                                    "url": get_bgm_asset_url("whoosh.mp3", "effects"),
                                                                    "loop": False,
                                                                    "volume": 0.5,
                                                                },
                                                            },
                                                            "duration": audio_transition_delay,
                                                            "delay": d[1]
                                                            - compensate_time,
                                                            "translation": 1000,
                                                            "unit": "px",
                                                            "randomize": False,
                                                            "enableZoomIn": False,
                                                            "style": {
                                                                "bottom": "100px"
                                                            },
                                                        }
                                                        for idx, d in enumerate(audios)
                                                    ],
                                                    "style": {
                                                        "width": "100%",
                                                        "height": "100%",
                                                        "display": "flex",
                                                        "padding": 30,
                                                        "justifyContent": "flex-start",
                                                        "alignItems": "flex-end",
                                                    },
                                                    "crossZoom": False,
                                                    "hidePrevious": True,
                                                },
                                            }
                                        }
                                        if avatar_map
                                        else {}
                                    ),
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
                                                                    "timepoints": timepoints_map.get(
                                                                        audios[i][0]
                                                                    ),
                                                                    "isWordTimepoints": is_word_timepoints,
                                                                    "duration": d[1]
                                                                    // 2,
                                                                    "style": {
                                                                        "metadata": "react css style for text",
                                                                        "padding": 10,
                                                                        "fontSize": 50,
                                                                        "textAlign": "center",
                                                                        "textShadow": "-5px -5px 0 black, 5px -5px 0 black, -5px 5px 0 black, 5px 5px 0 black",
                                                                        "fontWeight": "bold",
                                                                        "marginTop": 1000,
                                                                        "fontFamily": fontWithFallback,
                                                                    },
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
                                                    "paddingTop": "350px",
                                                },
                                            },
                                        }
                                    },
                                ],
                            },
                        },
                    },
                ],
            },
        },
    )
