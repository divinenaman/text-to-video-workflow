import argparse
import logging
import os
import sys
from . import voices
import xml.dom.minidom

# from google.cloud import texttospeech
from ssml_builder.core import Speech
from google.cloud import texttospeech_v1beta1 as texttospeech

# assumes you are running from the baasha-pipeline root folder
file_dir = os.path.dirname(__file__)
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.path.join(
    file_dir, "baasha-google-api-key.json"
)
standard_pause = "350ms"
short_pause = "250ms"


class SSMLMarkupTTSGenerator(object):
    def __init__(self):
        # logging.basicConfig(
        #     level=logging.INFO,
        #     format="%(asctime)s [%(levelname)s] %(message)s",
        #     handlers=[
        #         logging.FileHandler("/tmp/ssml_markup_tts_generator.log"),
        #         logging.StreamHandler(sys.stdout)
        #     ]
        # )
        pass

    @staticmethod
    def generate_audio_file(
        script_object, outfile, voice_config, audio_config, ssml_output=True
    ):
        ssml_raw_text = script_object.speak()
        ssml_txt = xml.dom.minidom.parseString(ssml_raw_text).toprettyxml()
        logging.info("SSML Text Generated: %s", ssml_txt)
        if ssml_output:
            ssml_file = outfile.replace(".mp3", ".ssml")
            with open(ssml_file, "w") as ssml_file:
                ssml_file.write(ssml_txt)

        # Create TTS client object
        client = texttospeech.TextToSpeechClient()
        synthesis_input = texttospeech.SynthesisInput(ssml=ssml_raw_text)

        # Perform the text-to-speech request on the text input with the selected
        # voice parameters and audio file type
        response = client.synthesize_speech(
            request=texttospeech.SynthesizeSpeechRequest(
                input=synthesis_input,
                voice=voice_config,
                audio_config=audio_config,
                enable_time_pointing=[
                    texttospeech.SynthesizeSpeechRequest.TimepointType.SSML_MARK
                ],
            )
        )

        # The response's audio_content is binary.
        with open(outfile, "wb") as out:
            # Write the response to the output file.
            out.write(response.audio_content)
            logging.info("Audio content written to file".format(outfile))

        return response.timepoints

    @staticmethod
    def process_line_for_speech(speech_object, text_line):
        def add_mark_to_each_word(text):
            text_split = text.strip().split(" ")
            res = list(
                map(lambda x: f'<mark name="{x[0]}"/>{x[1]}', enumerate(text_split))
            )
            return " ".join(res) + f'<mark name="{len(text_split)}"/>'

        speech_object.pause(standard_pause)
        text_line = add_mark_to_each_word(text_line)
        text_line = text_line.replace("- ", '<break time="%s"/>'.format(short_pause))
        speech_object.add_text(text_line)

    @staticmethod
    def process_timepoints(timepoints):
        ordered = sorted(timepoints, key=lambda tup: tup.time_seconds)
        return list(map(lambda x: x.time_seconds, ordered))

    def generate(
        self,
        script_lines,
        output_file,
        audio_configuration,
        voice_configuration,
        split_lines,
        store_ssml,
    ):
        results = []
        voice = texttospeech.VoiceSelectionParams(voice_configuration)
        audio = texttospeech.AudioConfig(audio_configuration)

        script = "\n".join(list(map(lambda x: x.strip(), script_lines)))

        lines = script.splitlines()  # sent_tokenize(script)
        speech_parts = []
        speech = Speech()
        for line in lines:
            if split_lines:
                self.process_line_for_speech(speech, line)
                speech_parts.append(speech)
                speech = Speech()
            else:
                self.process_line_for_speech(speech, line)
        if not split_lines:
            speech_parts = [speech]

        line_number = 0
        for speech_part in speech_parts:
            suffix = "" if not split_lines else "_part{}.mp3".format(line_number)
            filename = output_file.replace(".mp3", suffix)
            timepoints = self.generate_audio_file(
                speech_part, filename, voice, audio, ssml_output=store_ssml
            )
            line_number += 1

            results.append((filename, self.process_timepoints(timepoints)))
        return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Baasha SSML Markup Generator")
    parser.add_argument(
        "-f", "--script-file", help="File containing raw script", required=True
    )
    parser.add_argument(
        "--voice-conf",
        help="Voice configuration",
        required=False,
        default=voices.RHEA_IN_FEMALE,
    )
    parser.add_argument(
        "--audio-conf",
        help="Audio configuration",
        required=False,
        default=voices.AUDIO_CONFIG_NORMAL,
    )
    parser.add_argument("-o", "--output-file", help="Output file", required=True)
    parser.add_argument(
        "--ssml-output",
        help="Record SSML Output file",
        default=False,
        action="store_true",
    )
    parser.add_argument(
        "--split-lines",
        help="Split lines into separate MP3s",
        default=False,
        action="store_true",
    )

    args = vars(parser.parse_args())
    generator = SSMLMarkupTTSGenerator()
    with open(args["script_file"], "r") as script_file:
        files = generator.generate(
            script_file.readlines(),
            args["output_file"],
            args["audio_conf"],
            args["voice_conf"],
            args["split_lines"],
            args["ssml_output"],
        )
    logging.info("Generated: {}".format(", ".join(files)))
