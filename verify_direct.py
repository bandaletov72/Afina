"""Explicit read-only Windows verifier. No tokens in output, files or CLI args."""
import json
import re
from network_adapter import FixedHTTPS, ReportsTransport, CLIENTS_ENDPOINT, CLIENTS_BODY, valid_token
from report_core import InvalidReport, build_request, parse_report
from windows_credentials import CredentialStore
from local_input import ask_local_value

# Public distribution: set your own OAuth application ID (not a secret).
import os
KNOWN_CLIENT_ID = os.environ.get('AFINA_CLIENT_ID', '0' * 32)

def stored_authorization_available(client_id, store_factory=CredentialStore):
    try:
        # Check locally only. Never return/display/store the token elsewhere.
        store_factory(client_id).access_token()
        return True
    except Exception:
        return False

def reauthorize_local(parent, *, prompt=None, confirm=None, authorize=None,
                      confirm_delete=None, delete_saved=None):
    """Latest user policy: delete known saved authorization ONLY after consent.
    Decline deletion changes nothing. Cancel after deletion does NOT restore it.
    """
    from oauth_screen import authorize_windows
    if confirm_delete is None:
        from tkinter import messagebox
        confirm_delete = lambda: messagebox.askyesno('Афина: удалить сохранённую авторизацию?',
            'Будет удалён локальный токен Афины для Client ID\n' + KNOWN_CLIENT_ID + '.\n'
            'После этого откроется ввод ID и новый вход.\n'
            'Если затем отменить вход, прежний токен уже не восстановится.\n'
            'Это удаление из Windows, не отзыв доступа на стороне Яндекса. Удалить?',
            parent=parent)
    if not confirm_delete():
        return None
    if delete_saved is None:
        delete_saved = lambda: CredentialStore(KNOWN_CLIENT_ID).delete()
    delete_saved()
    if prompt is None:
        prompt = lambda: ask_local_value(parent)
    if confirm is None:
        from tkinter import messagebox
        confirm = lambda: messagebox.askokcancel('Афина: новая авторизация',
            'Откроется Яндекс OAuth для указанного Client ID.\n'
            'После успешного входа токен для указанного ID будет записан заново\n'
            '(если другой токен уже есть, он будет заменён).\n'
            'Вводите код только в локальном окне. Продолжить?',
            parent=parent)
    client_id = prompt()
    if client_id is None or not confirm():
        return None
    if authorize is None:
        authorize = lambda value: authorize_windows(value, http=FixedHTTPS(live_enabled=True))
    return client_id if authorize(client_id) else None

def select_client_id(parent):
    import tkinter as tk
    selection = [None]
    window = tk.Toplevel(parent)
    window.title('Афина: выбор авторизации')
    from avatar_ui import add_avatar
    add_avatar(window)
    available = stored_authorization_available(KNOWN_CLIENT_ID)
    tk.Label(window, text=('Сохранённая авторизация Афины доступна.'
        if available else 'Сохранённая авторизация отсутствует или истекла.'),
        wraplength=440).pack(padx=16,pady=12)
    tk.Label(window, text='Запрос к Яндексу начнётся только после вашего выбора.',
        wraplength=440).pack(padx=16,pady=6)
    def use_existing():
        selection[0] = KNOWN_CLIENT_ID
        window.destroy()
    def another():
        value = ask_local_value(window)
        if value is not None:
            selection[0] = value
            window.destroy()
    existing_button = tk.Button(window,text='Использовать сохранённую авторизацию Афины',
        state='normal' if available else 'disabled', command=use_existing)
    existing_button.pack(padx=16,pady=6)
    def reauthorize():
        from tkinter import messagebox
        try:
            value = reauthorize_local(window)
            if value is not None:
                selection[0] = value
                window.destroy()
            else:
                existing_button.configure(state='normal' if stored_authorization_available(KNOWN_CLIENT_ID) else 'disabled')
        except Exception:
            existing_button.configure(state='normal' if stored_authorization_available(KNOWN_CLIENT_ID) else 'disabled')
            messagebox.showerror('Афина: авторизация не завершена',
                'Авторизация или проверка сохранения не завершена.\n'
                'При ошибке после записи новый токен мог сохраниться.\n'
                'Секреты не выводятся. Можно отменить или повторить попытку.',
                parent=window)
    tk.Button(window,text='Указать другой Client ID',command=another).pack(padx=16,pady=6)
    tk.Button(window,text='Авторизироваться снова',command=reauthorize).pack(padx=16,pady=6)
    tk.Button(window,text='Отмена',command=window.destroy).pack(pady=12)
    window.protocol('WM_DELETE_WINDOW',window.destroy)
    window.grab_set()
    parent.wait_window(window)
    return selection[0]

PERIOD = {'dateFrom':'2026-11-09','dateTo':'2026-11-15'}

def identity(provider, http):
    token = provider()
    if not valid_token(token): raise InvalidReport('CREDENTIAL_INVALID')
    response = http.post(CLIENTS_ENDPOINT, {'Authorization':'Bearer '+token,
        'Content-Type':'application/json; charset=utf-8','Accept-Language':'en',
        'Accept-Encoding':'identity'}, json.dumps(CLIENTS_BODY).encode(), 65536, 15)
    if response.status != 200:
        raise InvalidReport('IDENTITY_HTTP_' + str(response.status))
    try:
        if len(response.body) > 65536: raise ValueError()
        obj = json.loads(response.body)
        if 'error' in obj: raise ValueError()
        clients = obj['result']['Clients']
        if type(clients) is not list or len(clients) != 1: raise ValueError()
        c = clients[0]
        if type(c['ClientId']) is not int or c['ClientId'] <= 0: raise ValueError()
        if type(c['Login']) is not str or not re.fullmatch(r'[A-Za-z0-9_.@-]{1,100}',c['Login']): raise ValueError()
        if c['Currency'] not in ('RUB','BYN','CHF','EUR','KZT','TRY','UAH','USD'): raise ValueError()
        # Explicit allowlist; never return raw response, extra fields or server errors.
        return {'clientId':str(c['ClientId']), 'login':c['Login'], 'currency':c['Currency']}
    except Exception:
        raise InvalidReport('IDENTITY_UNAVAILABLE_OR_UNEXPECTED_RESPONSE') from None

def report(provider, http, account):
    transport = ReportsTransport(provider,http=http)
    result = parse_report(transport.fetch(build_request(PERIOD)))
    result['currency'] = account['currency']
    result['period'] = dict(PERIOD)
    result['provenance'] = 'Yandex Direct Reports API'
    return result

def main():
    root = None
    stage = 'LOCAL_WINDOW'
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk();root.withdraw()
        client_id = select_client_id(root)
        if client_id is None: return 0
        stage = 'CREDENTIAL_READ'
        store = CredentialStore(client_id)
        http = FixedHTTPS(live_enabled=True)
        stage = 'CLIENTS_GET'
        account = identity(store.access_token,http)
        if not messagebox.askokcancel('Афина: подтвердите кабинет',
            'API вернул пользователя: '+account['login']+'\n'
            'ClientId: '+account['clientId']+'; валюта: '+account['currency']+'\n'
            'Это нужный кабинет? Получить расходы/клики за 9–15 ноября 2026 с НДС?\n'
            'Права только чтения не подтверждены. Этот скрипт не меняет рекламу.',
            parent=root): return 0
        stage = 'WEEKLY_REPORT'
        result = report(store.access_token,http,account)
        from result_ui import show_result
        show_result(root,account,result)
        return 0
    except Exception:
        if root is not None:
            from tkinter import messagebox
            messagebox.showerror('Афина: проверка не завершена',
                'Этап: '+stage+'.\nРезультат не подтверждён. Токен и ответ сервера не выводятся.\n'
                'При очереди отчёта можно повторить запуск позже. Реклама не изменялась.',
                parent=root)
        return 1
    finally:
        if root is not None:root.destroy()

if __name__ == '__main__':
    raise SystemExit(main())
