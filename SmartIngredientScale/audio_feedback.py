
# audio_feedback.py
# Provides audio feedback (gurgling, rattling, ping) based on ingredient type and progress

import simpleaudio as sa

AUDIO_FILES = {
    "liquid": "assets/audio/gurgle.wav",
    "dry": "assets/audio/rattle.wav",
    "ping": "assets/audio/ping.wav"
}

def play_sound(file_path):
    try:
        wave_obj = sa.WaveObject.from_wave_file(file_path)
        play_obj = wave_obj.play()
        play_obj.wait_done()
    except Exception as e:
        print(f"Audio error: {e}")

def provide_feedback(ingredient_type, percent):
    if percent >= 1.0:
        play_sound(AUDIO_FILES["ping"])
    elif ingredient_type == "liquid":
        play_sound(AUDIO_FILES["liquid"])
    elif ingredient_type == "dry":
        play_sound(AUDIO_FILES["dry"])
