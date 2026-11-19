"""Explicit Windows GUI launcher. No secrets in arguments, stdout or files.
Running this file intentionally starts OAuth only after local confirmation.
"""
import sys
import secrets
from report_core import InvalidReport
from network_adapter import FixedHTTPS
from oauth_prepare import TokenBundle
from oauth_screen import authorize_windows
from windows_credentials import CredentialStore

def storage_self_test():
    """Use a unique synthetic target, never an existing real credential."""
    store = CredentialStore(secrets.token_hex(16))
    try:
        store.save(TokenBundle('SYNTHETIC_STORAGE_PROBE_ONLY', 300))
        if store.access_token() != 'SYNTHETIC_STORAGE_PROBE_ONLY':
            raise InvalidReport('Storage self-test failed.')
    finally:
        store.delete()

def native_error():
    # Fixed diagnostic only: no exception text, clipboard or credentials.
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None,
            'Не удалось открыть окно Афины. Нужен Python с tkinter. Секреты не выводятся.',
            'Афина: запуск не завершён', 16)
    except Exception:
        pass

def main():
    if sys.platform != 'win32':
        return 2
    root = None
    stage = "Открытие локального окна"
    try:
        import tkinter as tk
        from tkinter import simpledialog, messagebox
        root = tk.Tk()
        root.withdraw()
        from local_input import ask_local_value
        stage = 'Ввод Client ID'
        client_id = ask_local_value(root)
        if client_id is None:
            return 0
        # Validate and check native backend before any browser/network action.
        stage = 'Проверка Windows-хранилища'
        CredentialStore(client_id)
        if not messagebox.askokcancel('Афина: подтвердите вход',
            'Откроется официальный Яндекс OAuth. Выберите нужный аккаунт.\n'
            'Код введите только в локальном окне, не отправляйте в чат.\n'
            'Токен будет сохранён в Диспетчере учётных данных Windows.\n'
            'Предыдущая авторизация этого приложения будет заменена.\n'
            'Доступ приложения direct:api не ограничен чтением: для отчётов\n'
            'используйте отдельного представителя с правами только чтения.\n'
            'Этот запуск не меняет кампании и не проверяет отчёты.',
            parent=root):
            return 0
        stage = 'Тест сохранения в Windows'
        storage_self_test()
        stage = 'Авторизация Яндекса или сохранение токена'
        success = authorize_windows(client_id, http=FixedHTTPS(live_enabled=True))
        if success:
            messagebox.showinfo('Афина', 'Токен сохранён и считан обратно.\n'
                'Личность пользователя, права и доступ к API Директа ещё не проверены.', parent=root)
        return 0
    except Exception:
        if root is not None:
            try:
                from tkinter import messagebox
                messagebox.showerror('Афина', 'Подключение не завершено. Этап: ' + stage + '.\n'
                    'Проверьте интернет, аккаунт, Client ID и повторите запуск.\n'
                    'Если сбой произошёл после записи, токен мог сохраниться.\n'
                    'Не пересылайте код или токен в чат.', parent=root)
            except Exception:
                native_error()
        else:
            native_error()
        return 1
    finally:
        if root is not None:
            root.destroy()

if __name__ == '__main__':
    raise SystemExit(main())
