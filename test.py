from operator import ne
import processor as P
from baasha_pipeline import stability_generator, goapi_midjourney_generator
import time
import os

prompt_category = {
    "character": ["find-story-characters"],
    "entity": ["ner-v1"],
    "entity_image": ["entity-to-image"],
}

styles = [
    ""
    # "Potrait By Peter Kemp, 50mm lens for a natural look, closeups, closeups, golden ratio composition, piercing gaze commanding attention, ultra realistic, blurred in the backdrop in a epic epic superb super sharp super sharp, very high realism, high realism, ultra-detailed, sharp shadows, sharp shadows, detailed, high high bokeh blur bokeh blur bokeh bokeh blur, realistic 12K realistic 12K  realistic 12K 12K realistic 12K 12K 12K 12K 12K, HDR, classy golden golden golden yellow epic epic, Diffuse light and create a soft, even glow, sharp edges, lot of fog fog in the backdrop, highlighting the subject, center of attention, midjourney, midjourney"
]

story = """
Did Albert Einstein cheat his way to success? The truth might shock you!
"""

# Few know that Einstein's first wife, Mileva Marić, was a brilliant physicist too - some say she was the real mastermind behind his most famous work. But did Einstein really steal credit for her ideas?
# Einstein and Marić met as students in Switzerland, where they collaborated on groundbreaking research.
#
def regress_prompt(chatbot):
    global prompt_category, styles, story

    print("regress testing prompts")

    script = P.split_text_into_sentences_with_styling(chatbot, story, "story")
    character_list = []
    for e in prompt_category["character"]:
        character_list = P.find_story_characters(chatbot, story, None, e, None)

        print("\n\n\n")

        print("######################################################")

        print("characters in story with description: ", character_list)

        print("######################################################")

        print("\n\n\n")

    for e in prompt_category["entity"]:
        for em in prompt_category["entity_image"]:
            for st in styles:
                res = P.generate_image_prompts_ner(
                    chatbot,
                    scene_count=-1,
                    script_lines=script,
                    image_styles=st,
                    ner_prompt_key=e,
                    ner_image_prompt_key=em,
                )

                print("\n\n\n\n\n")
                print("#####################################################")
                print("\n")

                print("Entity Prompt : ", e)
                print("Enity to Image Promot : ", em)
                print("Image Styles : ", st)

                print("\nEntities:")
                for et in res[1]:
                    print("-> ", et)
                print("\n\n")

                print("Image Prompts:")
                for im in res[0]:
                    print("-> ", im)
                print("\n")

                print("Character Match:")
                for (p, c) in res[0]:
                    ch = P.match_character(c, [], character_list)
                    print("-> ", ch)
                print("\n")

                # if len(res[0]) > 0:
                #    out_dir = "{}.{}".format("test_res", int(time.time()))
                #    out = stability_generator.generate_images(res[0][0:min(2, len(res[0]))], P.get_prompt_text("standard-negative-prompt-v1"), f"{os.getcwd()}/tmp/{out_dir}")
                #    print("Images :")
                #    for o in out:
                #        print("-> ", o)
                #    print("\n")

                print("#####################################################")
                print("\n\n\n\n\n")


def test_image_gen(engine):
    p = "Katie Holyfield and Taylor Matkins, co-founders of The Lucky Ones Coffee, stand amidst the vibrant atmosphere of their coffee shop, surrounded by happy customers and employees with disabilities. A brew station in the background, 50mm lens capturing the duo's smiles and gestures as they discuss new opportunities for their inclusive business. Soft morning lighting, emphasizing their passion for empowering their employees. clear features, cinematic, epic, 35 mm lens, f/1.8, accent lighting, global illumination, uplight, Photorealistic | Depth of field | Action Scene | Natrual Lighting | Subject | Centered-Shot | 22 Megapixels | Shot on IMAX 70 mm | Detailed | Elegant | Perfection | Shimmering | Perpective, HDR, 8k, high resolution"
    out_dir = "{}.{}".format("test_res", int(time.time()))
    out = f"{os.getcwd()}/tmp/{out_dir}"
    res = None

    if engine == "goapi_midjourney":
        res = goapi_midjourney_generator.generate_images(
            [(p, None)], P.get_prompt_text("standard-negative-prompt-v1"), out
        )
    elif engine == "stability":
        res = stability_generator.generate_images(
            p, P.get_prompt_text("standard-negative-prompt-v1"), out
        )

    print("\n\n\n\n")
    print("Generated Image : ", res)
    print("\n\n")
