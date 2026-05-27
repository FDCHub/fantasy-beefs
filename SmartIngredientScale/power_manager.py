
# power_manager.py
# Manages screen dimming and sleep/wake logic for Smart Ingredient Scale

import time

# Placeholder values for inactivity
INACTIVITY_THRESHOLD = 300  # seconds (5 minutes)

last_activity_timestamp = time.time()

def update_activity():
    global last_activity_timestamp
    last_activity_timestamp = time.time()

def is_idle():
    return (time.time() - last_activity_timestamp) > INACTIVITY_THRESHOLD

def check_sleep_mode():
    if is_idle():
        print("[Sleep Mode] Trigger screen dimming or shutdown sequence.")
        # Insert screen dimming logic here
    else:
        print("[Active Mode] User activity detected.")
