few_shot_prompting_for_prompts = """
Given a topic, create detailed prompts on images or photos related to the topic. Be creative, make the prompts very detailed. Include camera settings and artist infomation. Keep the style of the all prompts similar. Format the prompts in JSON.

A couple of examples are below.

Topic: create 3 prompts on topic: Alexander The Great
Output:
{
    "prompt1": "super realistic photography of stunning intricate full-color portrait Alexander the Great, great Roman general, wreath of golden olive branch on head, severe man in the image of Roman warrior, perfect symmetric eyes, gorgeous face, blonde long curls, barbarian, epic composition of the character, Greg Rutkowski, WLOP, Artgerm, James Jean, Alphonse Mucha, kinematic similarity, illuminated by the light of a fire, highly detailed, realistic, golden ratio, award winning, professional, by ivv, highly detailed, intricate, volumetric lighting, gorgeous, masterpiece, sharp focus, depth of field, perfect composition, pixiv trends, artstation, 32k, uhd",
    "prompt2": "Apollo as an astrological constellation, artistic expression, a greek god, black space background. 8k resolution digital artwork by Marc Silvestri and Greg Rutkowski, portrait quality features, precision, lighting in the style of Boris Vallejo, coherent arbitration, fine tuned details, atmospheric, vivid colors, hyperdetailed hair strands, octane render, sharp focus, highly detailed eyes, rim light, chiaroscuro, award - winning illustration.",
    "prompt3": "a portrait of Alexander the Great, Colored Pencil, Paparazzi Photography, 35mm, Closeup, 4D, Ultra-HD, HDR, Cinematic Lighting, by Alessio Albi"
}


Topic: create 4 prompts on topic: Beautiful Women!
Output:
{
  "prompt1": "cinematic style low angle full body portrait of a beautiful and voluptuous caucasian model Tangled in gold wire, detailed beautiful face, detailed expressive eyes, perfect ample bosom, detailed real skin texture, shapely legs, thigh gap, big butt, Miki Asai Macro photography, close-up, hyper detailed, trending on artstation, sharp focus, studio photo, intricate details, highly detailed, by greg rutkowski. FUJIFILM, bokeh",
  "prompt2": "Aliens film style, A gorgeous female in a futuristic space cocoon, wearing nothing, in a transparent glowing liquid, aliens all around her, perfect face, big eyes, intricate wires, rear lighting, close-up, 8k, soft lighting, realistic, dawn rays, dynamism, highly detailed face, extraterrestrial forces, beautiful, masculine, alien invasion, gilded white suits, science fiction, complex works, concept artists, fontistic backdrop, Greg Rutkowski, Loish, Rhads, Beeple, Makoto Shinkai, Lois Van Baarle, Ilya Kuvshinov, Rossdraws, Tom Bagshaw, Alphonse Mucha, octane render, Purity, symmetrical design, soft lighting, global lighting, bright, extraterrestrial forces, hyperrealistic, cinematic character renderings, detailed environment paintings, Unreal Engine 8k, recognition, emitting diodes, smoke, artillery, beauty, viewer, real masterpieces",
  "prompt3": "woman in spacesuit standing in a space station, in the style of sunil das, hannah yata, smilecore, photo taken with provia, environmental portraiture, school of london, engineering/construction and design"
  "prompt4": "masterpiece, best quality, 1girl, full body portrait, detail skin, black hair, realistic, raw, beauty face, looking at viewer, allure, summer dress"
}

Give the output for the following topic:
"""


def ask_for_dalle_prompts_on_topic_with_few_shots(topic, count=5):
    input_query = f"Topic: create {count} prompts on topic: {topic}"
    return few_shot_prompting_for_prompts + input_query
