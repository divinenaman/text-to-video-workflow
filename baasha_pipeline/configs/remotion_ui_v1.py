import os
from .utils import convert_actual_path_to_virtual


def get_fonts(ui_config):
    return []


def get_ui_config(data, text, audios, images, video_dur, total_time):
    timepoints_map = data["timepoints_map"]

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
                                "volume": 0.2,
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
                                                "url": os.path.join(
                                                    "assets", "transition_whoosh.mp3"
                                                ),
                                                "volume": 0.2,
                                            },
                                        },
                                        "duration": 0.3,
                                        "delay": d[1],
                                    }
                                    for d in audios
                                ]
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
                                            "props": {"url": d[0].split("/")[-1]},
                                        },
                                        "duration": 0.3,
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
                                                        "url": d[0],
                                                        "width": "full_width",
                                                        "height": "full_height",
                                                        "zoomOut": True,
                                                        "zoomDuration": d[1],
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
                                                "duration": d[1] // 2,
                                                "style": {
                                                    # "backgroundColor": 'rgba(0,0,0,0.4)',
                                                    "padding": 30,
                                                    "fontSize": "8em",
                                                    "textAlign": "center",
                                                    "textShadow": "-5px -5px 0 black, 5px -5px 0 black, -5px 5px 0 black, 5px 5px 0 black",
                                                    "fontWeight": "bold",
                                                },
                                                "color": "white",
                                            },
                                        },
                                        "duration": 0.3,
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
