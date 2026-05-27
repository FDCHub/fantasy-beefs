
# ingredient_resolver.py
# Converts selected ingredient + unit + quantity into expected weight (grams)

from ingredient_reference_loader import get_ingredient_data

def resolve_ingredient(ingredient_name, unit, quantity):
    ingredient = get_ingredient_data(ingredient_name)
    if not ingredient:
        raise ValueError(f"Ingredient '{ingredient_name}' not found")

    unit_data = ingredient.get("units", {})
    if unit not in unit_data:
        raise ValueError(f"Unit '{unit}' not found for ingredient '{ingredient_name}'")

    grams_per_unit = unit_data[unit]
    total_grams = grams_per_unit * quantity
    return total_grams
