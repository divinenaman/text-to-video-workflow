from . import image_gen
from . import utils
from . import splitters
import json
from ..hugging_face import hug_chat

# a = utils.get_image_gen_prompt_from_storage("v111-p.json")
# print(a)

p, s = utils.get_image_gen_prompt_from_storage(
    "decomposed_prompt_v2.json", {"title": "Jon Snow", "prefix": "Dostovsky"}
)

t = hug_chat.fetch_text(p)

print(t)

t1 = s(t)
print(t1)

# print(prompt, split)
