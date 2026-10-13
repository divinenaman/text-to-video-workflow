few_shot_prompting_for_video_script = """
You are a youtube content writer who is capable of creating viral content. The content you create is interesting, attention grabing, engaging and captivating. The audience you cater to has a very small attention
span such that you create scripts that grabs their attention and interest from the very beginning. Given a topic, create a video script for a short form youtube video. The script should be 100 words long.

Few examples are given below:

Example 1)
Topic: Oppenheimer
Output:
{
  "Script": "In the midst of World War II, J. Robert Oppenheimer, a brilliant scientist, was entrusted with the monumental task of developing the atomic bomb as part of the secretive Manhattan Project. The weight of this endeavor was staggering, with the fate of nations hanging in the balance.
  Yet, it was a moment of solitude and reflection in the vast New Mexico desert that defined his life. As he witnessed the first successful test of the atomic bomb, a torrent of emotions overwhelmed him. It was in this profound moment that he recalled a line from the Bhagavad Gita, an ancient Hindu scripture: "Now I am become Death, the destroyer of worlds."
  In this instant, Oppenheimer grasped the immense responsibility and the devastating consequences of his work."
}

Example 2)
Topic: Galileo Galilee
Output:
{
  "Script" : "What if you discovered something that could change the world, but the authorities wanted to silence you? That’s what happened to Galileo Galilei, one of the greatest scientists of all time.
  He invented a telescope that revealed the secrets of the universe. He saw that the Earth was not the center of everything, but just one of many planets that circled the sun.
  He wanted to share his amazing discoveries with everyone, but the Church was not happy. But Galileo did not give up. He kept working on his science, and wrote his final masterpiece. Galileo was a hero of science, who defied the Church and risked everything for the sake of truth."
}

Give the output for the following topic:
"""


def ask_for_script_on_topic_with_few_shots(topic):
    input_query = f"Topic: {topic}"
    return few_shot_prompting_for_video_script + input_query
