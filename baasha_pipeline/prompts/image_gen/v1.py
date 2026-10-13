import random


def ask_for_dalle_prompts_on_topic(topic, count=5):
    formatter = "JSON"
    format_info = f"Format the prompts into a {formatter} object with one key prompt."
    prefix = f"create {count} dalle-2 prompts on '{topic}', make each prompt detailed, add artist name, camera settings etc."

    return f"{prefix} {format_info}."


def get_dalle_images_style():
    arr1 = ["8K, 3D, digital art", "8K, 3D", "Award Winning", "8K, Detailed"]
    # "screenshot from Game of Thrones"
    arr2 = ["Trending on ArtStation", "Photorealistic", "Unreal Engine"]

    return random.choice(arr1) + ", " + random.choice(arr2)
