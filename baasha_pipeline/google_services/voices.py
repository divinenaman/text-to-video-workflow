from google.cloud import texttospeech

google_tts_voice_dict = dict(
    RHEA_IN_FEMALE={
        "language_code": "hi-IN",
        "ssml_gender": texttospeech.SsmlVoiceGender.FEMALE,
        "name": "hi-IN-Neural2-A",
    },
    TARA_IN_FEMALE={
        "language_code": "hi-IN",
        "ssml_gender": texttospeech.SsmlVoiceGender.FEMALE,
        "name": "hi-IN-Neural2-D",
    },
    AJAY_IN_MALE={
        "language_code": "hi-IN",
        "ssml_gender": texttospeech.SsmlVoiceGender.MALE,
        "name": "hi-IN-Neural2-B",
    },
    ROHIT_IN_MALE={
        "language_code": "hi-IN",
        "ssml_gender": texttospeech.SsmlVoiceGender.MALE,
        "name": "hi-IN-Neural2-C",
    },
    JACK_EN_MALE={
        "language_code": "en-US",
        "ssml_gender": texttospeech.SsmlVoiceGender.MALE,
        "name": "en-US-Neural2-D",
    },
    ROSE_EN_FEMALE={
        "language_code": "en-US",
        "ssml_gender": texttospeech.SsmlVoiceGender.FEMALE,
        "name": "en-US-Neural2-E",
    },
    RICK_EN_MALE={
        "language_code": "en-US",
        "ssml_gender": texttospeech.SsmlVoiceGender.MALE,
        "name": "en-US-Neural2-I",
    },
    RITA_EN_FEMALE={
        "language_code": "en-US",
        "ssml_gender": texttospeech.SsmlVoiceGender.FEMALE,
        "name": "en-US-Neural2-F",
    },
    AUDIO_CONFIG_NORMAL={
        "audio_encoding": texttospeech.AudioEncoding.MP3,
        "speaking_rate": 1.0,
        "effects_profile_id": ["headphone-class-device"],
        "pitch": 0,
    },
    AUDIO_CONFIG_QUICK_FACTS={
        "audio_encoding": texttospeech.AudioEncoding.MP3,
        "speaking_rate": 1.10,
        "effects_profile_id": ["headphone-class-device"],
        "pitch": 0,
    },
    AUDIO_CONFIG_SLOW={
        "audio_encoding": texttospeech.AudioEncoding.MP3,
        "speaking_rate": 0.9,
        "effects_profile_id": ["headphone-class-device"],
        "pitch": 0,
    },
    AUDIO_CONFIG_X_SLOW={
        "audio_encoding": texttospeech.AudioEncoding.MP3,
        "speaking_rate": 0.8,
        "effects_profile_id": ["headphone-class-device"],
        "pitch": 0,
    },
    US_WAVENET_MALE_1={
        "language_code": "en-US",
        "ssml_gender": texttospeech.SsmlVoiceGender.MALE,
        "name": "en-US-Wavenet-I",
    },
    US_WAVENET_FEMALE_1={
        "language_code": "en-US",
        "ssml_gender": texttospeech.SsmlVoiceGender.FEMALE,
        "name": "en-US-Wavenet-E",
    },
)
