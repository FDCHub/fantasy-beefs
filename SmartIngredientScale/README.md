# Smart Ingredient Scale – MVP

This is the README for the Smart Ingredient Scale MVP – a voice- and touch-enabled kitchen scale system designed for accurate, intuitive cooking and baking.

## Features
- Converts recipe instructions like “1 cup of honey” into weight
- Real-time visual feedback while weighing (percent or cooking fraction)
- Audio cues as you approach and reach the target
- Touchscreen interface with dropdowns and interactive controls
- Voice command support using Whisper running locally on Raspberry Pi 5
- Ingredient-aware overage handling with friendly prompts

## Hardware Requirements
- Raspberry Pi 5 (4GB or 8GB)
- HX711 Load Cell Amplifier + 1kg/5kg Load Cell
- LIELONGREN USB Speaker (Model LLR055)
- Dungzduz USB-A Microphone
- Miuzei 4” HDMI Capacitive Touchscreen
- MicroSD Card (16GB+), USB-C Power Supply, jumper wires

## Software Overview
- Python 3.x
- Tkinter (UI), Whisper (voice recognition), custom modules
- Modular architecture with support for manual overrides and calibration
- Ingredient reference data in local JSON file

## Setup
1. Flash Raspberry Pi OS and enable SSH, SPI, I2C, and Autologin with `raspi-config`
2. Wire HX711 to GPIO pins and connect touchscreen, speaker, and microphone
3. Install required Python libraries (see `requirements.txt`)
4. Clone or copy source files to Pi and run:  
   ```bash
   python3 SmartIngredientScale.py
   ```

## Voice Command Example
Say:
> “Two cups of flour”  
The system will convert to grams, play progress sound, and display percent.

## Roadmap
- Recipe scaling
- Recipe step mode
- Cloud backup and import
