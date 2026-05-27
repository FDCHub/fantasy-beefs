
# fraction_converter.py
# Converts a decimal percentage to a cooking-friendly fraction string

from fractions import Fraction

COMMON_FRACTIONS = [
    Fraction(0, 1), Fraction(1, 8), Fraction(1, 6), Fraction(1, 5),
    Fraction(1, 4), Fraction(1, 3), Fraction(3, 8), Fraction(2, 5),
    Fraction(1, 2), Fraction(3, 5), Fraction(5, 8), Fraction(2, 3),
    Fraction(3, 4), Fraction(4, 5), Fraction(5, 6), Fraction(7, 8),
    Fraction(1, 1)
]

def fractionify(decimal_percent):
    frac = Fraction(decimal_percent).limit_denominator(100)
    closest = min(COMMON_FRACTIONS, key=lambda x: abs(x - frac))
    return f"{closest.numerator}/{closest.denominator}" if closest.denominator != 1 else f"{closest.numerator}"
