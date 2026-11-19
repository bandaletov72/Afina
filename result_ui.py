"""Allowlisted report display/copy; no credentials, raw responses or errors accepted."""
import json

def report_text(account, result):
    if result.get('complete') is not True or result.get('vatIncluded') is not True:
        raise ValueError('Only complete VAT-included reports may be copied.')
    safe = {
        'account': {k: account[k] for k in ('clientId','login','currency')},
        'period': {k: result['period'][k] for k in ('dateFrom','dateTo')},
        'vatIncluded': True,
        'currency': result['currency'],
        'rows': [{k: row[k] for k in ('campaignId','campaignName','clicks','costExact','costWholeUnits')}
                 for row in result['rows']],
        'totals': {k: result['totals'][k] for k in ('clicks','costExact','costWholeUnits')},
        'permissions': 'Read-only role NOT verified; only read methods called',
    }
    # Extra source keys, error bodies, tokens, debug context never enter export.
    return json.dumps(safe,ensure_ascii=False,indent=2)

def install_copy(window, text, payload, status):
    def copy_value(value):
        try:
            window.clipboard_clear()
            window.clipboard_append(value)
            status.configure(text='Скопировано. Буфер содержит отчёт, без данных авторизации.')
        except Exception:
            status.configure(text='Не удалось скопировать. Попробуйте выделить текст и Ctrl+C.')
    def copy_all():
        copy_value(payload)
    def key(event):
        code=getattr(event,'keycode',None)
        name=getattr(event,'keysym','').lower()
        if code==67 or name in ('c','cyrillic_es'):
            try:
                selected=text.get('sel.first','sel.last')
            except Exception:
                selected=payload
            copy_value(selected)
            return 'break'
        if code==65 or name in ('a','cyrillic_ef'):
            text.tag_add('sel','1.0','end-1c')
            return 'break'
        return None
    text.bind('<Control-KeyPress>',key)
    return copy_all

def show_result(root, account, result):
    import tkinter as tk
    from avatar_ui import add_avatar
    payload=report_text(account,result)
    window=tk.Toplevel(root);window.title('Афина: отчёт с НДС')
    add_avatar(window)
    frame=tk.Frame(window);frame.pack(fill='both',expand=True)
    scroll=tk.Scrollbar(frame);scroll.pack(side='right',fill='y')
    text=tk.Text(frame,width=100,height=25,wrap='word',yscrollcommand=scroll.set,
                 exportselection=False,takefocus=True)
    text.pack(side='left',fill='both',expand=True)
    scroll.configure(command=text.yview)
    text.insert('1.0',payload)
    text.configure(state='disabled')
    status=tk.Label(window,text='Выделите текст мышью; Ctrl+A / Ctrl+C работают и в русской раскладке.')
    status.pack(padx=10,pady=5)
    copy_all=install_copy(window,text,payload,status)
    tk.Button(window,text='Копировать результат',command=copy_all).pack(pady=5)
    tk.Button(window,text='Закрыть',command=window.destroy).pack(pady=5)
    text.focus_set()
    window.protocol('WM_DELETE_WINDOW',window.destroy)
    root.wait_window(window)
