"""Local-only validated entry with explicit paste. Clipboard is never read by Python."""
import re
import unicodedata

def normalize_code(value):
    if type(value) is not str: raise ValueError()
    value = value.strip()
    if not value or len(value) > 512 or len(value.encode("utf-8")) > 2048:
        raise ValueError()
    if any(c.isspace() or unicodedata.category(c).startswith("C") for c in value):
        raise ValueError()
    if "://" in value: raise ValueError()
    return value


def install_paste(entry):
    def paste(event=None):
        entry.focus_set()
        entry.event_generate('<<Paste>>')
        return 'break'
    def control_key(event):
        # Windows virtual key V is 86 even when Russian layout reports 'м'.
        if getattr(event, 'keycode', None) == 86 or getattr(event, 'keysym', '').lower() in ('v', 'cyrillic_em'):
            return paste(event)
        return None
    entry.bind('<Control-KeyPress>', control_key)
    entry.bind('<Shift-Insert>', paste)
    return paste

def ask_local_value(parent, *, code=False):
    import tkinter as tk
    from tkinter import simpledialog, messagebox
    class Input(simpledialog.Dialog):
        def body(self, master):
            label = ('Вставьте полный код подтверждения Яндекса. Не отправляйте его в чат.'
                     if code else 'Client ID: 32 шестнадцатеричных символа. Не Client Secret.')
            tk.Label(master, text=label, wraplength=420, justify='left').pack(padx=10,pady=10)
            self.entry = tk.Entry(master, width=48, show='*' if code else '')
            self.entry.pack(padx=10,pady=5)
            paste = install_paste(self.entry)
            tk.Button(master, text='Вставить из буфера', command=paste).pack(pady=5)
            tk.Label(master, text='Ctrl+V (в том числе русская раскладка) или Shift+Insert',
                     wraplength=420).pack(padx=10,pady=5)
            return self.entry
        def validate(self):
            value = self.entry.get().strip()
            try:
                if code:
                    value = normalize_code(value)
                elif not re.fullmatch(r'[a-fA-F0-9]{32}', value):
                    raise ValueError()
            except ValueError:
                messagebox.showerror('Проверьте формат',
                    'Вставьте полный код без внутренних пробелов, не ссылку (до 512 символов).' if code else 'Нужен Client ID из 32 символов 0-9, a-f.',
                    parent=self)
                return False
            self.result = value
            return True
        def apply(self):
            self.entry.delete(0, 'end')
    return Input(parent, 'Афина: код Яндекса' if code else 'Афина: Client ID').result
