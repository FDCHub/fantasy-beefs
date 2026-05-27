
# whisper_parser.py
# Transcribes and parses voice command using OpenAI Whisper

import whisper
import re

model = whisper.load_model("base")

def transcribe_and_parse(audio_file):
    print(f"[Whisper] Transcribing {audio_file}...")
    result = model.transcribe(audio_file)
    transcript = result.get("text", "").lower().strip()
    print(f"[Whisper] Transcript: {transcript}")

    # Very simple parser for MVP (expandable later)
    match = re.search(r"(\d+|one|two|three|four|five|six|seven|eight|nine|ten)?\s?(\w+)\s+of\s+(.*)", transcript)
    if match:
        quantity_raw, unit, ingredient = match.groups()
        quantity = word_to_number(quantity_raw.strip()) if quantity_raw else 1
        return {
            "ingredient": ingredient.strip(),
            "unit": unit.strip(),
            "quantity": quantity
        }
    return None

def word_to_number(word):
    word_map = {
        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10
    }
    return word_map.get(word, int(word)) if word.isdigit() or word in word_map else 1
