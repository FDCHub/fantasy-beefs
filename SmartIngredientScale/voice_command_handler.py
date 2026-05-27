
# voice_command_handler.py
# Uses audio capture + Whisper transcription to parse ingredient commands

from whisper_parser import transcribe_and_parse
from audio_capture import record_audio

def get_voice_command():
    print("[Voice] Listening for ingredient command...")
    audio_file = record_audio("voice_input.wav", duration=4)
    result = transcribe_and_parse(audio_file)

    if result:
        print(f"[Voice] Parsed: {result}")
        return result
    else:
        print("[Voice] Could not understand input.")
        return None
