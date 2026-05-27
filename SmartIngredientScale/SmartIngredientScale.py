# SmartIngredientScale.py
# Main controller for the Smart Ingredient Scale MVP

from ui_interface import run_ui
from voice_command_handler import handle_voice_command
from ingredient_resolver import resolve_ingredient
from ingredient_logger import log_ingredient
from settings_manager import load_settings
from audio_feedback import play_feedback_sound
from live_scale_reader import get_live_weight
from ingredient_reference_loader import load_ingredient_data

def main():
    print("Initializing Smart Ingredient Scale...")

    settings = load_settings()
    ingredient_data = load_ingredient_data()
    
    # Launch UI
    run_ui(settings, ingredient_data)

if __name__ == "__main__":
    main()
