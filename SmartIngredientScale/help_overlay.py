
# help_overlay.py
# Displays a simple help overlay within the Smart Ingredient Scale UI

import tkinter as tk

def show_help_overlay(root):
    overlay = tk.Toplevel(root)
    overlay.title("Help")
    overlay.geometry("400x300")
    overlay.configure(bg="black")

    help_text = (
        "Welcome to the Smart Ingredient Scale!\n\n"
        "- Use the dropdowns to select an ingredient.\n"
        "- Choose the unit and quantity you want to measure.\n"
        "- The slider simulates live weight input.\n"
        "- Toggle between percent and fraction display.\n"
        "- Sounds indicate progress and completion.\n"
        "- Use the Tare button to reset at any time."
    )

    label = tk.Label(overlay, text=help_text, bg="black", fg="white", justify="left", font=("Arial", 12))
    label.pack(padx=20, pady=20)

    dismiss_button = tk.Button(overlay, text="Close", command=overlay.destroy)
    dismiss_button.pack(pady=10)

    overlay.transient(root)
    overlay.grab_set()
    root.wait_window(overlay)
