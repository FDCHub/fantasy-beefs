
# ingredient_reference_loader.py
# Loads and provides access to the ingredient reference JSON file

import json

INGREDIENT_DB_PATH = "ingredients_reference.json"
_ingredient_data = {}

def load_ingredient_reference(path=INGREDIENT_DB_PATH):
    global _ingredient_data
    with open(path, "r") as f:
        _ingredient_data = json.load(f)

def get_ingredient_data(ingredient_name):
    return _ingredient_data.get(ingredient_name.lower(), None)

def get_all_ingredients():
    return list(_ingredient_data.keys())
