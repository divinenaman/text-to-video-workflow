def gen_image_background():
    return "Old black background. grunge texture. dark wallpaper. blackboard, chalkboard, room wall., vibrant, colorful gradient splash, hd, 4k, high-quality, highly detailed, photorealistic, raw, high quality, dynamic lighting, sharp focus, ultra realistic, masterpiece"

    # res = chatbot.fetch_text(f"""You are an artist. Before creating your masterpieces, you breakdown your
    # composition into foreground and background. The foreground consists of people, characters or enitites that
    # the art is about while the background consists of themes, styles, asthetics, colors, art style,
    # artist you took inspiration from or object that might be closely linked to the foreground in some sense.
    # I have a foreground in mind {entity}, describe me a background""")
    # return res


def get_actions():
    return [
        "staring and looking straight",
        "teaching students",
        "reading a book while in a deep thought",
        "addressing a crowd",
        "similing and looking straight",
        "wildly laughing",
        "doing work in his lab",
        "writing on blackboard",
        "discussing topics with peers",
        "intensly working with full concentration",
    ]


def mk_fg(
    entity,
    action,
    styles="photorealistic, Depth of Field, Action Scene, Natural Lighting, Subject, Centered-Shot, 22 Megapixels, Shot on IMAX 70mm, Detailed, Elegant, Perfection, Shimmering, Perspective, HDR, 8k, high resolution",
):
    return f"A close up {entity} {action}, {styles}"


def join_prompt(fg, bg):
    return f"The foreground has {fg} while the background is inpired by {bg}"


def mk_prompts(entity):
    res = []
    bg = gen_image_background()
    for a in get_actions():
        fg = mk_fg(entity, a)
        p = join_prompt(fg, bg)

        res.append(p)

    return res
