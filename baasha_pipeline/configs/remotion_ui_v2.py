import os
from .utils import convert_actual_path_to_virtual

file_parent_dir = os.path.join(os.path.dirname(__file__), "..")


def get_bgm_font_url(filename):
    cluster = os.environ.get("S3_CLUSTER", "localhost:9000")
    bucket = os.environ.get("BGM_BUCKET", "baasha-bgm")
    protocol = os.environ.get("S3_PROTOCOL", "https")
    return f"{protocol}://{bucket}.{cluster}/fonts/{filename}"


def get_fonts(ui_config):
    lemonpie = os.path.join(file_parent_dir, "assets", "fonts", "lemonpie.ttf")
    kalyubi = os.path.join(file_parent_dir, "assets", "fonts", "kalyubi.otf")
    brush_squad = os.path.join(file_parent_dir, "assets", "fonts", "brush_squad.ttf")
    good_brush = get_bgm_font_url("good_brush.otf")

    return [{"uri": convert_actual_path_to_virtual(good_brush), "name": "GoodBrush"}]


def get_ui_config(data, text, audios, images, video_dur, total_time):
    audio_transition_delay = 0.3

    total_time = total_time + audio_transition_delay * len(audios)

    timepoints_map = data["timepoints_map"]
    is_word_timepoints = data.get("is_word_timepoints", False)

    img_dur = 3
    images = list(map(lambda x: (x[0], img_dur), images))
    diff = total_time - (len(images) * img_dur)
    if diff > 0:
        images = int((diff // img_dur) + 1) * images

    font = "GoodBrush"

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
                                "url": convert_actual_path_to_virtual(data["bgm"][0]),
                                "loop": True,
                                "volume": 0.25,
                            },
                        }
                    },
                    {
                        "component": {
                            "component": "video",
                            "props": {
                                "url": convert_actual_path_to_virtual(data["video"]),
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
                                            "props": {
                                                "url": convert_actual_path_to_virtual(
                                                    d[0]
                                                )
                                            },
                                        },
                                        "duration": audio_transition_delay,
                                        "delay": d[1],
                                    }
                                    for d in audios
                                ]
                            },
                        }
                    },
                    {
                        "component": {
                            "component": "transition_slide",
                            "props": {
                                "elements": [
                                    {
                                        "component": {
                                            "component": "overlay",
                                            "props": {
                                                "children": {
                                                    "component": "img",
                                                    "props": {
                                                        "url": convert_actual_path_to_virtual(
                                                            d[0]
                                                        ),
                                                        "width": "full_width",
                                                        "height": "full_height",
                                                        "zoomOut": True,
                                                        "zoomDuration": d[1],
                                                        "maxZoom": 1.3,
                                                    },
                                                }
                                            },
                                        },
                                        "duration": 0.3,
                                        "delay": d[1],
                                        "translation": 100,
                                        "unit": "%",
                                        "randomize": True,
                                    }
                                    for d in images
                                ],
                                "style": {"width": "100%", "height": "100%"},
                            },
                        }
                    },
                    {
                        "component": {
                            "component": "container",
                            "props": {
                                "children": {
                                    "component": "text",
                                    "props": {
                                        "text": data["onScreenTitle"],
                                        "style": {
                                            "display": "inline",
                                            "textAlign": "center",
                                            "marginTop": 100,
                                            "height": "max-content",
                                            "fontSize": "5em",
                                            "background": "#000",
                                            "color": "#fff",
                                            "fontWeight": "bold",
                                            "padding": (
                                                15 if data["onScreenTitle"] != "" else 0
                                            ),
                                            "fontFamily": font,
                                        },
                                    },
                                },
                                "style": {
                                    "width": "100%",
                                    "display": "flex",
                                    "justifyContent": "center",
                                },
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
                                                    # "backgroundColor": 'rgba(0,0,0,0.4)',
                                                    "padding": 30,
                                                    "fontSize": "8em",
                                                    "textAlign": "center",
                                                    "textShadow": "-20px -20px 0 black, 20px -20px 0 black, -20px 20px 0 black, 20px 20px 0 black",
                                                    "fontWeight": "bold",
                                                },
                                                "color": "white",
                                                "font": font,
                                            },
                                        },
                                        "duration": audio_transition_delay,
                                        "delay": d[1],
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
