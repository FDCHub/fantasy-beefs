
# ui_interface.py
# UI module for Smart Ingredient Scale (MVP version)
import tkinter as tk
from tkinter import ttk

def launch_ui():
    root = tk.Tk()
    root.title("Smart Ingredient Scale")

    # Dropdown placeholders
    tk.Label(root, text="Category").pack()
    tk.Label(root, text="Ingredient").pack()
    tk.Label(root, text="Unit").pack()
    tk.Entry(root).pack()

    # Simulated slider
    tk.Label(root, text="Simulated Weight").pack()
    tk.Scale(root, from_=0, to=100, orient=tk.HORIZONTAL).pack()

    # Display mode toggle
    tk.Label(root, text="Display Mode").pack()
    ttk.Combobox(root, values=["Percent", "Fraction"]).pack()

    # Buttons
    tk.Button(root, text="Tare").pack()
    tk.Button(root, text="Help").pack()

    root.mainloop()
