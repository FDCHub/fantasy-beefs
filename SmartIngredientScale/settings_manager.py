
# settings_manager.py
# Loads and saves user settings like display mode and voice on/off

import json
import os

SETTINGS_PATH = "settings.json"

default_settings = {
    "display_mode": "percent",  # or "fraction"
    "voice_enabled": False,
    "dark_mode": True
}

def load_settings():
    if not os.path.exists(SETTINGS_PATH):
        save_settings(default_settings)
    with open(SETTINGS_PATH, "r") as f:
        return json.load(f)

def save_settings(settings):
    with open(SETTINGS_PATH, "w") as f:
        json.dump(settings, f, indent=4)
