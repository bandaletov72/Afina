"""Saved profile avatar, packaged locally; no runtime networking."""
from pathlib import Path
def add_avatar(window):
    import tkinter as tk
    source = tk.PhotoImage(file=str(Path(__file__).resolve().parent / 'assets' / 'afina_avatar.png'))
    image = source.subsample(4, 4)  # Original 512x512 -> 128x128, aspect preserved.
    window._afina_avatar = image  # Tk image lifetime must cover window lifetime.
    window.iconphoto(False, image)
    label = tk.Label(window, image=image, borderwidth=0)
    label.pack(padx=12, pady=(12, 4))
    return label
