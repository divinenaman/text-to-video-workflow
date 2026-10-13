def ask_for_youtube_shorts_content_on_topic(topic):
    format_info = f"keep it short, in under 150 words, no emoji, no links, to the point, no acknowledgement."
    prefix = "create a brief, engaging and interesting story on"

    return f"{prefix} '{topic}' {format_info}."
