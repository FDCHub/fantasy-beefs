
# audio_capture.py
# Records short audio clips from the microphone for Whisper transcription

import sounddevice as sd
import soundfile as sf

def record_audio(filename="voice_input.wav", duration=4, samplerate=16000):
    print(f"[Audio] Recording {duration} seconds...")
    recording = sd.rec(int(samplerate * duration), samplerate=samplerate, channels=1)
    sd.wait()
    sf.write(filename, recording, samplerate)
    print(f"[Audio] Saved to {filename}")
    return filename
