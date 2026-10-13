import os

def get_bgm_font_url(filename):
    cluster = os.environ.get("S3_CLUSTER", "localhost:9000")
    bucket = os.environ.get("BGM_BUCKET", "baasha-bgm")
    protocol = os.environ.get("S3_PROTOCOL", "https")
    return f"{protocol}://{bucket}.{cluster}/fonts/{filename}"


def get_fonts(ui_config):
    komikax = get_bgm_font_url("komikax.ttf")

    return [{"uri": komikax, "name": "Komikax"}]


def get_ui_config(data, text, audios, images, video_dur, total_time):
    audio_transition_delay = 0.1
    is_transition_inclusive = True
    compensate_time = audio_transition_delay if is_transition_inclusive else 0

    total_time = total_time + (
        0 if is_transition_inclusive else audio_transition_delay
    ) * len(audios)

    timepoints_map = data["timepoints_map"]
    sound_map = data["sound_map"]

    image_to_videos = data.get("image_to_videos", {})
    processed_sound_map = []
    prev_end = 0
    for s in sound_map:
        if s[1] >= prev_end:
            processed_sound_map.append((s[0], s[1] - prev_end, s[2] - s[1]))
            prev_end = s[2]

    is_word_timepoints = data.get("is_word_timepoints", False)

    font = "Komikax"
    fontWithFallback = "Komikax, Noto Sans Tamil, Noto Sans"

    transitions = ["emerge-zoom", "emerge-slide", "emerge-grow", "emerge-fade"]

    return (
        total_time,
        {
            "component": "parallel",
            "props": {
                "layout": "zstack",
                "style": {"background": "#000"},
                "elements": [
                    {
                        "component": {
                            "component": "audio",
                            "props": {
                                "metadata": "props for background music",
                                "url": data["bgm"][0],
                                "loop": True,
                                "volume": 0.10,
                            },
                        }
                    },
                    {
                        "component": {
                            "component": "video",
                            "props": {
                                "url": data.get("video", ""),
                                "duration": video_dur,
                                "zoomOut": True,
                                "loop": True,
                                "volume": 0.2,
                                "style": {"width": "100%", "height": "100%"},
                            },
                        }
                    },
                    {
                        "component": {
                            "component": "transition_emerge",
                            "props": {
                                "elements": [
                                    {
                                        "component": {
                                            "component": "audio",
                                            "props": {"url": d[0]},
                                        },
                                        "duration": audio_transition_delay,
                                        "delay": d[1] - compensate_time,
                                    }
                                    for d in audios
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
                                        "transitionType": (
                                            transitions[idx % len(transitions)]
                                        ),
                                        "component": {
                                            "component": "overlay",
                                            "props": {
                                                "children": {
                                                    "component": (
                                                        "video"
                                                        if image_to_videos.get(
                                                            images[idx % len(images)][0]
                                                        )
                                                        else "img"
                                                    ),
                                                    "props": {
                                                        "url": image_to_videos.get(
                                                            images[idx % len(images)][0]
                                                        )
                                                        or images[idx % len(images)][0],
                                                        "width": "full_width",
                                                        "height": "full_height",
                                                        "wobble": True,
                                                        "zoomOut": True,
                                                        "zoomDuration": d[1],
                                                        "maxZoom": 1.3,
                                                    },
                                                }
                                            },
                                        },
                                        "duration": audio_transition_delay,
                                        "delay": d[1] - compensate_time,
                                        "translation": 20,
                                        "unit": "%",
                                        "randomize": True,
                                        "enableZoomIn": False,
                                    }
                                    for idx, d in enumerate(audios)
                                ],
                                "style": {"width": "100%", "height": "100%"},
                                "crossZoom": True,
                            },
                        }
                    },
                    {
                        "component": {
                            "component": "transition_emerge",
                            "props": {
                                "elements": [
                                    {
                                        "component": {
                                            "component": "subtitle_text",
                                            "props": {
                                                "text": d[0],
                                                "timepoints": timepoints_map[
                                                    audios[i][0]
                                                ],
                                                "isWordTimepoints": is_word_timepoints,
                                                "duration": d[1] // 2,
                                                "style": {
                                                    "metadata": "react css styles for text",
                                                    "padding": 30,
                                                    "fontSize": "7em",
                                                    "textAlign": "center",
                                                    "textShadow": "-5px -5px 0 black, 5px -5px 0 black, -5px 5px 0 black, 5px 5px 0 black",
                                                    "fontWeight": "bold",
                                                },
                                                "color": "white",
                                                "font": fontWithFallback,
                                            },
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
                                    "alignItems": "center",
                                },
                            },
                        }
                    },
                ],
            },
        },
    )
