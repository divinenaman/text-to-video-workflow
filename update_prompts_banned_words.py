import json

with open("prompts.json", "r", encoding="utf-8") as f:
    prompts = json.load(f)

# Update banned words to specifically ban camera terms which ruin style refs
if "banned-words" in prompts:
    prompts["banned-words"][
        "text"
    ] += ", iPhone, candid, smartphone, DSLR, 35mm, cinematic, masterpiece, photograph, photography"

# Remove the "Heavily apply the specific lighting..." from prompts
for key in ["find-story-characters", "entity-to-image"]:
    if key in prompts:
        text = prompts[key]["text"]
        text = text.replace(
            " Heavily apply the specific lighting, texture, era, and aesthetic vibe from the Style Reference.",
            "",
        )
        text = text.replace(
            " Heavily apply the specific lighting, texture, and aesthetic vibe from the Style Reference.",
            "",
        )
        prompts[key]["text"] = text

with open("prompts.json", "w", encoding="utf-8") as f:
    json.dump(prompts, f, indent=2)
