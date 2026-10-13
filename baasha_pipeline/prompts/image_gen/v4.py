selected_prompts = [
    "<character> staring and looking straight standing in a lab, Shot on IMAX 70mm, Detailed, Elegant, Perfection, Shimmering, Perspective, HDR, 8k, high resolution",
    "<character> teaching students in a lecture hall, photorealistic, Depth of Field, Action Scene, Natural Lighting, Subject, Centered-Shot, 22 Megapixels, Shot on IMAX 70mm, Detailed, Elegant, Perfection, Shimmering, Perspective, HDR, 8k, high resolution",
    "<character> reading a book while in a deep thought in library, photorealistic, Depth of Field, Action Scene, Natural Lighting, Subject, Centered-Shot, 22 Megapixels, Shot on IMAX 70mm, Detailed, Elegant, Perfection, Shimmering, Perspective, HDR, 8k, high resolution",
    "<character> addressing a crowd in an auditorium, photorealistic, Depth of Field, Action Scene, Natural Lighting, Subject, Centered-Shot, 22 Megapixels, Shot on IMAX 70mm, Detailed, Elegant, Perfection, Shimmering, Perspective, HDR, 8k, high resolution",
    "<character> similing and looking straight in a park, photorealistic, Depth of Field, Action Scene, Natural Lighting, Subject, Centered-Shot, 22 Megapixels, Shot on IMAX 70mm, Detailed, Elegant, Perfection, Shimmering, Perspective, HDR, 8k, high resolution",
    "<character> wildly laughing with friends at dinner, photorealistic, Depth of Field, Action Scene, Natural Lighting, Subject, Centered-Shot, 22 Megapixels, Shot on IMAX 70mm, Detailed, Elegant, Perfection, Shimmering, Perspective, HDR, 8k, high resolution",
    "<character> doing work in the lab, photorealistic, Depth of Field, Action Scene, Natural Lighting, Subject, Centered-Shot, 22 Megapixels, Shot on IMAX 70mm, Detailed, Elegant, Perfection, Shimmering, Perspective, HDR, 8k, high resolution",
    "<character> discussing topics with peers, photorealistic, Depth of Field, Action Scene, Natural Lighting, Subject, Centered-Shot, 22 Megapixels, Shot on IMAX 70mm, Detailed, Elegant, Perfection, Shimmering, Perspective, HDR, 8k, high resolution",
]


def character_switched_prompts(ch):
    def populate(p, c):
        return p.replace("<character>", ch)

    mapped = map(lambda x: populate(x, ch), selected_prompts)
    return list(mapped)
