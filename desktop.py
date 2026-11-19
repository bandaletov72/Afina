"""Afina Windows desktop report. All ad mutation capabilities intentionally absent."""
import csv
import io
import json
import queue
import threading
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
import tkinter as tk
from tkinter import ttk
from report_core import build_request, parse_report
from result_ui import report_text

BG, NAV, INK, MUTED, PURPLE = '#f3f4f9', '#152238', '#1b263d', '#6c7b95', '#7762e7'

def previous_week(today=None):
    today = today or date.today()
    end = today - timedelta(days=today.weekday()+1)
    return {'dateFrom': (end-timedelta(days=6)).isoformat(), 'dateTo': end.isoformat()}

def period_from_start(value):
    start = date.fromisoformat(value)
    result = {'dateFrom': start.isoformat(), 'dateTo': (start+timedelta(days=6)).isoformat()}
    build_request(result)
    return result

def number(value, decimals=0):
    return f'{Decimal(str(value)):,.{decimals}f}'.replace(',', ' ').replace('.', ',')

def cpc(result):
    clicks = result['totals']['clicks']
    return Decimal(result['totals']['costExact'])/clicks if clicks else None

def csv_text(account, result, delimiter=";"):
    # Whitelist first. Formula-looking external names are escaped for Excel.
    safe = json.loads(report_text(account, result))
    out = io.StringIO(newline='')
    w = csv.writer(out, delimiter=delimiter)
    w.writerow(['Период', safe['period']['dateFrom'], safe['period']['dateTo']])
    w.writerow(['Валюта', safe['currency'], 'С НДС'])
    w.writerow(['ID кампании', 'Кампания', 'Клики', 'Расход с НДС', 'Расход без копеек'])
    for row in safe['rows']:
        name=row['campaignName']
        if name.lstrip().startswith(('=', '+', '-', '@')): name="'"+name
        w.writerow([row['campaignId'], name, row['clicks'], row['costExact'], row['costWholeUnits']])
    t=safe['totals'];w.writerow(['', 'ИТОГО', t['clicks'], t['costExact'], t['costWholeUnits']])
    return out.getvalue()

class CredentialUnavailable(Exception):
    """No credential details are carried to the UI."""


def prepare_authorization(client_id, store_factory=None):
    from windows_credentials import CredentialStore
    from oauth_screen import begin_screen
    (store_factory or CredentialStore)(client_id)  # Check Windows backend before opening browser.
    return begin_screen(client_id)


class Dashboard:
    def __init__(self, root, demo=False):
        self.root=root;self.demo=demo;self.busy=False;self.generation=0
        self.result=None;self.account=None;self.session_provider=None;self.events=queue.Queue();self.closed=False
        root.title('Афина · Недельный отчёт Яндекс Директа');root.geometry('1280x880');root.minsize(1060,760);root.configure(bg=BG)
        root.protocol('WM_DELETE_WINDOW', self.close)
        style=ttk.Style();style.theme_use('clam');style.configure('Treeview',rowheight=30,font=('Segoe UI',10),background='white',fieldbackground='white')
        style.configure('Treeview.Heading',font=('Segoe UI',10,'bold'),background='#e9edf5')
        nav=tk.Frame(root,bg=NAV,width=205);nav.pack(side='left',fill='y');nav.pack_propagate(False)
        self.avatar=tk.PhotoImage(file=str(Path(__file__).parent/'assets/afina_avatar.png')).subsample(6,6)
        root.iconphoto(False,self.avatar)
        tk.Label(nav,image=self.avatar,bg=NAV).pack(pady=(25,4))
        self.label(nav,'Афина',26,'white',NAV).pack();self.label(nav,'Рекламная аналитика',11,'#b2bfd3',NAV).pack(pady=(5,28))
        ttk.Button(nav,text='Директ · Недельный отчёт',command=lambda:self.switch_view('direct')).pack(fill='x',padx=12,pady=6)
        ttk.Button(nav,text='Метрика · Посетители',command=lambda:self.switch_view('metrica')).pack(fill='x',padx=12,pady=6)
        ttk.Button(nav,text='Объявления · Каталог',command=lambda:self.switch_view('ads')).pack(fill='x',padx=12,pady=6)
        for text in ['Биддинг','Ключевые слова','Баннеры']:
            self.label(nav,text+'\nПланируется',11,'#a7b3c8',NAV).pack(anchor='w',padx=23,pady=16)
        self.label(nav,'Только чтение API\nБез изменения рекламы',10,'#a7b3c8',NAV).pack(side='bottom',pady=24)
        self.metrica=None;self.ads=None;self.active_view='direct'
        main=tk.Frame(root,bg=BG);self.main=main;main.pack(fill='both',expand=True,padx=24,pady=20)
        self.label(main,'Недельный отчёт',27).pack(anchor='w')
        self.label(main,'Расходы и клики · Яндекс Директ · с НДС',11,MUTED).pack(anchor='w',pady=(4,16))
        auth=tk.Frame(main,bg='#eae5ff');auth.pack(fill='x',pady=(0,12))
        self.label(auth,'Авторизация хранится только в Windows',10,'#51458f','#eae5ff').pack(side='left',padx=10,pady=12)
        self.auth=ttk.Button(auth,text='Авторизация / войти снова',command=self.authorize);self.auth.pack(side='right',padx=10)
        self.client_id=None;self.pending_auth=None
        self.panel=tk.Frame(main,bg='#eae5ff')
        controls=tk.Frame(main,bg=BG);controls.pack(fill='x',pady=(0,12))
        self.label(controls,'Понедельник:',11).pack(side='left')
        self.start=tk.StringVar(value=previous_week()['dateFrom'])
        self.entry=ttk.Entry(controls,textvariable=self.start,width=13);self.entry.pack(side='left',padx=8)
        self.prev=ttk.Button(controls,text='Прошлая неделя',command=lambda:self.start.set(previous_week()['dateFrom']));self.prev.pack(side='left')
        self.load=ttk.Button(controls,text='Получить отчёт',command=self.fetch);self.load.pack(side='left',padx=8)
        self.export=ttk.Button(controls,text='Экспорт CSV',command=self.save,state='disabled');self.export.pack(side='right')
        self.copy=ttk.Button(controls,text='Копировать',command=self.copy_report,state='disabled');self.copy.pack(side='right',padx=8)
        self.status=tk.StringVar(value='Выберите авторизацию, затем получите отчёт. Запросов при запуске нет.')
        self.label(main,'',10,MUTED,textvariable=self.status,wraplength=950).pack(anchor='w',pady=(0,10))
        self.period_label=self.label(main,'Неделя ещё не загружена',13);self.period_label.pack(anchor='w',pady=(0,12))
        cards=tk.Frame(main,bg=BG);cards.pack(fill='x');self.metrics=[]
        for i,title in enumerate(['РАСХОД С НДС','КЛИКИ','СРЕДНЯЯ ЦЕНА КЛИКА']):
            card=tk.Frame(cards,bg='white');card.grid(row=0,column=i,sticky='nsew',padx=(0,12 if i<2 else 0));cards.columnconfigure(i,weight=1)
            self.label(card,title,10,MUTED,'white').pack(anchor='w',padx=16,pady=(14,4))
            metric=self.label(card,'—',24,INK,'white');metric.pack(anchor='w',padx=16,pady=(0,16));self.metrics.append(metric)
        self.chart=tk.Canvas(main,bg='white',height=175,highlightthickness=0);self.chart.pack(fill='x',pady=14);self.chart.bind('<Configure>',lambda e:self.draw_chart())
        table=tk.Frame(main);table.pack(fill='both',expand=True)
        self.tree=ttk.Treeview(table,columns=('name','clicks','cost','whole'),show='headings',height=6)
        for key,title,width in [('name','Кампания',360),('clicks','Клики',95),('cost','Расход с НДС',140),('whole','Без копеек',120)]:
            self.tree.heading(key,text=title);self.tree.column(key,width=width,anchor='w' if key=='name' else 'e')
        scroll=ttk.Scrollbar(table,orient='vertical',command=self.tree.yview);scroll.pack(side='right',fill='y');self.tree.configure(yscrollcommand=scroll.set);self.tree.pack(fill='both',expand=True)
        self.label(main,'Итог считается из точных сумм; копейки отбрасываются после сложения.\nРоль аккаунта не проверена. Приложение вызывает только методы чтения.',9,MUTED).pack(anchor='w',pady=(12,0))
        root.after(100,self.poll)
        if demo:self.show_demo()
    def label(self,parent,text,size=12,fg=INK,bg=BG,**kw):
        return tk.Label(parent,text=text,font=('Segoe UI',size,'bold' if size>=13 else 'normal'),fg=fg,bg=bg,justify='left',**kw)
    def switch_view(self,target):
        current={'direct':self,'metrica':self.metrica,'ads':self.ads}[self.active_view]
        if current.busy:
            current.status.set('Сначала завершите или отмените текущее действие.');return
        if target=='metrica' and self.metrica is None:
            from metrica_ui import MetricaView
            self.metrica=MetricaView(self)
        if target=='ads' and self.ads is None:
            from ads_ui import AdsView
            self.ads=AdsView(self)
        self.main.pack_forget()
        if self.metrica:self.metrica.hide()
        if self.ads:self.ads.hide()
        if target=='direct':self.main.pack(fill='both',expand=True,padx=24,pady=20)
        elif target=='metrica':self.metrica.show()
        elif target=='ads':self.ads.show()
        self.active_view=target
    def close(self):
        self.closed=True;self.generation+=1;self.session_provider=None
        if getattr(self,'metrica',None):self.metrica.close()
        if getattr(self,'ads',None):self.ads.close()
        self.root.destroy()
    def set_busy(self,value):
        self.busy=value
        for widget in (self.auth,self.load,self.prev,self.entry):widget.configure(state='disabled' if value else 'normal')
        for widget in (self.export,self.copy):widget.configure(state='normal' if not value and self.result is not None else 'disabled')
    def clear_panel(self):
        for child in self.panel.winfo_children():child.destroy()
        self.panel.pack_forget()
    def panel_text(self,text):
        self.clear_panel();self.panel.pack(fill='x',before=self.period_label,pady=(0,10))
        self.label(self.panel,text,10,'#51458f','#eae5ff',wraplength=900).pack(anchor='w',padx=10,pady=8)
    def confirm_inline(self,text,yes,no):
        self.panel_text(text)
        def finish(action):self.clear_panel();action()
        ttk.Button(self.panel,text='Продолжить',command=lambda:finish(yes)).pack(side='left',padx=10,pady=8)
        ttk.Button(self.panel,text='Отмена',command=lambda:finish(no)).pack(side='left',padx=10,pady=8)
    def cancel_authorization(self):
        if self.pending_auth:
            self.pending_auth.consumed=True;self.pending_auth.verifier='';self.pending_auth=None
        self.clear_panel();self.set_busy(False);self.status.set('Вход отменён.')
    def authorize(self):
        if self.busy or self.demo:return
        self.set_busy(True)
        from verify_direct import KNOWN_CLIENT_ID
        self.panel_text('Выберите сохранённую авторизацию или новый вход. Токен не показывается и не копируется.')
        def existing():
            self.client_id=KNOWN_CLIENT_ID;self.clear_panel();self.set_busy(False);self.status.set('Выбрана сохранённая авторизация: '+KNOWN_CLIENT_ID)
        ttk.Button(self.panel,text='Использовать '+KNOWN_CLIENT_ID,command=existing).pack(anchor='w',padx=10,pady=5)
        def reauth():
            def delete():
                try:
                    from windows_credentials import CredentialStore
                    CredentialStore(KNOWN_CLIENT_ID).delete();self.client_id=None;self.enter_id()
                except Exception:self.clear_panel();self.set_busy(False);self.status.set('Не удалось удалить локальную авторизацию. Новый вход не начат.')
            self.confirm_inline('Авторизироваться снова: удалить локальный токен Афины для '+KNOWN_CLIENT_ID+'? Отмена после удаления не восстановит токен. Это не отзыв доступа на стороне Яндекса.',delete,self.cancel_authorization)
        ttk.Button(self.panel,text='Авторизироваться снова',command=reauth).pack(side='left',padx=10,pady=8)
        ttk.Button(self.panel,text='Закрыть',command=self.cancel_authorization).pack(side='left',padx=10,pady=8)
    def enter_id(self):
        from verify_direct import KNOWN_CLIENT_ID
        self.panel_text('Client ID приложения. Новый токен будет сохранён в Windows (заменит прежний для этого ID).')
        value=tk.StringVar(value=KNOWN_CLIENT_ID)
        ttk.Entry(self.panel,textvariable=value,width=40).pack(side='left',padx=10,pady=8)
        def begin():
            from oauth_screen import begin_screen
            import webbrowser
            try:
                pending,url=prepare_authorization(value.get().strip())
                if not webbrowser.open(url):raise ValueError()
                self.pending_auth=pending;self.enter_code()
            except Exception:self.status.set('Не удалось начать вход. Проверьте Client ID, доступность хранилища Windows и браузер.')
        ttk.Button(self.panel,text='Открыть Яндекс и войти',command=begin).pack(side='left',padx=8)
        ttk.Button(self.panel,text='Отмена',command=self.cancel_authorization).pack(side='left',padx=8)
    def enter_code(self):
        self.panel_text('Вставьте полный код из Яндекса. Он скрыт, не попадает в отчёт или журнал. Срок попытки — 10 минут.')
        code=tk.StringVar();entry=ttk.Entry(self.panel,textvariable=code,show='•',width=45);entry.pack(side='left',padx=10,pady=8)
        def paste():
            try:code.set(self.root.clipboard_get())
            except tk.TclError:self.status.set('Буфер обмена недоступен.')
        def cancel():
            if self.pending_auth:self.pending_auth.consumed=True;self.pending_auth.verifier='';self.pending_auth=None
            code.set('');self.clear_panel();self.set_busy(False);self.status.set('Вход отменён.')
        def submit():
            from local_input import normalize_code
            try:entered=normalize_code(code.get())
            except ValueError:self.status.set('Вставьте полный код, не ссылку.');return
            pending=self.pending_auth;code.set('');self.clear_panel();self.set_busy(True);self.status.set('Завершаю авторизацию…')
            def exchange():
                from oauth_screen import finish_screen
                from network_adapter import FixedHTTPS
                from windows_credentials import CredentialStore
                try:
                    tokens=finish_screen(pending,entered,http=FixedHTTPS(live_enabled=True))
                    CredentialStore(pending.client_id).save(tokens)
                    return pending.client_id
                finally:pending.verifier='';pending.consumed=True
            self.background('authorized',exchange)
        ttk.Button(self.panel,text='Вставить',command=paste).pack(side='left',padx=4)
        ttk.Button(self.panel,text='Подтвердить',command=submit).pack(side='left',padx=4)
        ttk.Button(self.panel,text='Отмена',command=cancel).pack(side='left',padx=4)
    def background(self,kind,fn):
        generation=self.generation
        def run():
            try:self.events.put((generation,kind,fn()))
            except CredentialUnavailable:self.events.put((generation,'credential_error',None))
            except Exception:self.events.put((generation,'auth_error' if kind=='authorized' else 'error',None))
        threading.Thread(target=run,daemon=True).start()
    def fetch(self):
        if self.busy:return
        if self.demo:self.show_demo();return
        try:period=period_from_start(self.start.get().strip())
        except Exception:
            self.status.set('Введите дату понедельника в формате ГГГГ-ММ-ДД.');return
        if not self.client_id:self.authorize()
        if not self.client_id:return
        self.set_busy(True);self.status.set('Проверяю кабинет… Предыдущий отчёт, если есть, остаётся на экране.')
        from windows_credentials import CredentialStore
        from network_adapter import FixedHTTPS
        from verify_direct import identity
        try:store=CredentialStore(self.client_id)
        except Exception:
            self.set_busy(False);self.status.set('Хранилище авторизации недоступно. Запустите приложение в Windows.');return
        self.http=FixedHTTPS(live_enabled=True);self.pending_period=period
        # Take one immutable credential snapshot for both identity and this report.
        # A later Windows-store replacement cannot switch the confirmed account.
        def identify():
            try:token=store.access_token()
            except Exception:raise CredentialUnavailable() from None
            provider=lambda:token
            return identity(provider,self.http),provider
        self.background('identity',identify)
    def poll(self):
        if self.closed:return
        try:
            while True:
                generation,kind,value=self.events.get_nowait()
                if generation!=self.generation:continue
                if kind=='identity':
                    account,self.session_provider=value
                    def cancel():self.session_provider=None;self.set_busy(False);self.status.set('Запрос отчёта отменён.')
                    def accept(account=account):
                        self.pending_account=account;self.status.set('Загружаю отчёт с НДС…')
                        from network_adapter import ReportsTransport
                        provider=self.session_provider
                        def request():
                            result=parse_report(ReportsTransport(provider,http=self.http).fetch(build_request(self.pending_period)))
                            result.update(period=dict(self.pending_period),currency=self.pending_account['currency'])
                            return (dict(self.pending_account),result)
                        self.background('report',request)
                    self.confirm_inline(f"Кабинет: {account['login']} · {account['clientId']} · {account['currency']}. Получить отчёт {self.pending_period['dateFrom']} — {self.pending_period['dateTo']} с НДС? Реклама не изменяется.",accept,cancel)
                elif kind=='authorized':
                    self.client_id=value;self.pending_auth=None;self.set_busy(False);self.status.set('Авторизация сохранена. Можно получить отчёт.')
                elif kind=='report':self.session_provider=None;self.display(*value);self.set_busy(False)
                elif kind=='credential_error':
                    self.session_provider=None;self.set_busy(False);self.status.set('Сохранённая авторизация отсутствует, истекла или недоступна. Нажмите «Авторизация / войти снова».')
                elif kind=='auth_error':
                    self.pending_auth=None;self.set_busy(False);self.status.set('Авторизация не подтверждена. При ошибке сохранения новый токен мог сохраниться. Повторите вход или выберите сохранённую авторизацию.')
                else:
                    self.session_provider=None;self.set_busy(False);self.status.set('Не удалось получить новый отчёт. Данные на экране не обновлены. Можно повторить запрос.')

        except queue.Empty:pass
        if not self.closed:self.root.after(100,self.poll)
    def display(self,account,result):
        report_text(account,result) # Require complete VAT-included data before replacing view.
        self.account,self.result=account,result
        symbol='₽' if result['currency']=='RUB' else result['currency']
        self.metrics[0].configure(text=number(result['totals']['costWholeUnits'])+' '+symbol)
        self.metrics[1].configure(text=number(result['totals']['clicks']))
        average=cpc(result);self.metrics[2].configure(text='—' if average is None else number(average,2)+' '+symbol)
        p=result['period'];week=date.fromisoformat(p['dateFrom']).isocalendar().week
        self.period_label.configure(text=f"{week}-я неделя · {p['dateFrom']} — {p['dateTo']}")
        self.status.set(('ДЕМОНСТРАЦИЯ · синтетические данные · API не вызывается' if self.demo else 'Отчёт получен: '+account['login'])+' · '+result['currency'])
        self.tree.delete(*self.tree.get_children())
        for row in result['rows']:
            self.tree.insert('', 'end',values=(row['campaignName'],number(row['clicks']),number(row['costExact'],2),number(row['costWholeUnits'])))
        self.export.configure(state='normal');self.copy.configure(state='normal');self.draw_chart()
    def draw_chart(self):
        self.chart.delete('all');self.chart.create_text(18,20,text='Расходы по кампаниям · с НДС',anchor='w',fill=INK,font=('Segoe UI',13,'bold'))
        if not self.result:return
        rows=sorted(self.result['rows'],key=lambda r:Decimal(r['costExact']),reverse=True)[:3]
        if not rows:self.chart.create_text(18,70,text='За выбранную неделю нет строк отчёта.',anchor='w',fill=MUTED);return
        max_value=max(Decimal(r['costExact']) for r in rows) or Decimal(1)
        width=max(100,self.chart.winfo_width()-440)
        for i,row in enumerate(rows):
            y=48+i*38;name=row['campaignName'];name=name if len(name)<=28 else name[:26]+'…'
            self.chart.create_text(18,y+12,text=name,anchor='w',fill=MUTED,font=('Segoe UI',10))
            length=float(Decimal(row['costExact'])/max_value)*width
            self.chart.create_rectangle(235,y,235+length,y+25,fill=PURPLE if i==0 else '#b3a7ed',outline='')
            self.chart.create_text(245+length,y+12,text=number(row['costWholeUnits'])+' '+self.result['currency'],anchor='w',fill=INK,font=('Segoe UI',10,'bold'))
        if len(self.result['rows'])>3:self.chart.create_text(18,165,text='Показаны 3 крупнейшие кампании; все строки в таблице и экспорте.',anchor='w',fill=MUTED,font=('Segoe UI',9))
    def copy_report(self):
        if self.busy or not self.result:return
        try:
            self.root.clipboard_clear();self.root.clipboard_append(csv_text(self.account,self.result,delimiter='\t'));self.status.set('Отчёт скопирован. Данных авторизации в нём нет.')
        except tk.TclError:self.status.set('Буфер обмена недоступен. Попробуйте ещё раз или сохраните CSV.')
    def save(self):
        if self.busy or not self.result:return
        self.panel_text('Сохранить отчёт CSV (Excel, UTF-8). Укажите путь к файлу:')
        folder=Path.home()/'Documents'
        if not folder.is_dir():folder=Path.home()
        value=tk.StringVar(value=str(folder/('Afina_'+self.result['period']['dateFrom']+'.csv')))
        ttk.Entry(self.panel,textvariable=value,width=75).pack(side='left',padx=10,pady=8)
        payload=csv_text(self.account,self.result)
        def write(target):
            try:target.write_text(payload,encoding='utf-8-sig');self.clear_panel();self.status.set('Отчёт сохранён в CSV с НДС.')
            except OSError:self.status.set('Не удалось записать файл. Проверьте путь и права записи.')
        def submit():
            target=Path(value.get().strip())
            if target.suffix.lower()!='.csv':self.status.set('Укажите имя файла с расширением .csv.');return
            if target.exists():self.confirm_inline('Файл уже существует. Заменить его текущим отчётом?',lambda:write(target),lambda:None)
            else:write(target)
        ttk.Button(self.panel,text='Сохранить',command=submit).pack(side='left',padx=4)
        ttk.Button(self.panel,text='Отмена',command=self.clear_panel).pack(side='left',padx=4)
    def show_demo(self):
        result=parse_report(b'CampaignId\tCampaignName\tClicks\tCost\n1\tDemo Campaign A\t800\t12000.50\n2\tDemo Campaign B\t200\t4000.25\n')
        result.update(period={'dateFrom':'2026-11-09','dateTo':'2026-11-15'},currency='RUB')
        self.start.set('2026-11-09');self.display({'clientId':'DEMO','login':'demo-offline','currency':'RUB'},result)
        self.auth.configure(state='disabled')

if __name__=='__main__':
    import sys
    root=tk.Tk();Dashboard(root,demo='--demo' in sys.argv);root.mainloop()
