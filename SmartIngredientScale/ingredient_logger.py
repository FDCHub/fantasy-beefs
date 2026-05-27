
# ingredient_logger.py
# Logs each ingredient measured for recipe or session tracking

import json
import os
from datetime import datetime

LOG_FILE = "ingredient_log.json"

def log_ingredient(ingredient, unit, quantity, grams):
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "ingredient": ingredient,
        "unit": unit,
        "quantity": quantity,
        "grams": grams
    }
    logs = []
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r") as f:
            logs = json.load(f)
    logs.append(log_entry)
    with open(LOG_FILE, "w") as f:
        json.dump(logs, f, indent=4)

def get_logs():
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r") as f:
            return json.load(f)
    return []
