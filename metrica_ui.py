"""Single-window, read-only Metrica tab. Real requests only after explicit actions."""
import json
import os
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk
import csv
import io

BG='#f3f4f9';INK='#1b263d';MUTED='#6c7b95'

def settings_path():
    return Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'AppData'/'Local')))/'Afina'/'metrica_public.json'

def load_client_id():
    try:
        path=settings_path()
        if path.stat().st_size>2048:return ''
        import re
        value=json.loads(path.read_text(encoding='utf-8')).get('clientId','')
        return value if re.fullmatch('[a-fA-F0-9]{32}',value) else ''
    except Exception:return ''

def save_client_id(value):
    import re
    if not re.fullmatch('[a-fA-F0-9]{32}',value):raise ValueError()
    path=settings_path();path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps({'clientId':value}),encoding='utf-8') # Public ID only, no tokens.

def export_results(results,delimiter=';'):
    out=io.StringIO(newline='');w=csv.writer(out,delimiter=delimiter)
    w.writerow(['ID счётчика','Название','Сайт','С','По','Посетители','Точность','Доля выборки','Задержка данных, сек','Статус'])
    def safe(value):
        value=str(value)
        return "'"+value if value.lstrip().startswith(('=','+','-','@')) else value
    for item in results:
        period=item['period'];result=item.get('result')
        if result:
            w.writerow([item['id'],safe(result['counter']['name']),safe(result['counter']['site']),period['dateFrom'],period['dateTo'],result['users'],'Без семплирования' if result['exact'] else ('Оценка / выборка' if result.get('sampled') is True else 'Точность не подтверждена'),result['sampleShare'],result['dataLag'],'Получено'])
        else:w.writerow([item['id'],'','',period['dateFrom'],period['dateTo'],'','','','',item['error']])
    return out.getvalue()

class MetricaView:
    def __init__(self,dashboard):
        self.app=dashboard;self.root=dashboard.root;self.demo=dashboard.demo
        self.frame=tk.Frame(self.root,bg=BG);self.busy=False;self.closed=False;self.pending=None;self.auth_in_flight=False;self.auth_lock=threading.Lock();self.events=queue.Queue();self.stop=threading.Event();self.results=[];self.counters=[]
        self.label('Яндекс Метрика',26).pack(anchor='w',pady=(0,6))
        self.label('Только просмотр · посетители, не визиты · период понедельник–воскресенье',11,MUTED).pack(anchor='w',pady=(0,14))
        self.client=tk.StringVar(value='' if self.demo else load_client_id())
        auth=tk.Frame(self.frame,bg=BG);auth.pack(fill='x')
        tk.Label(auth,text='Client ID приложения Метрики:',bg=BG).pack(side='left')
        self.id_entry=ttk.Entry(auth,textvariable=self.client,width=36);self.id_entry.pack(side='left',padx=8)
        self.auth_button=ttk.Button(auth,text='Подключить / войти снова',command=self.authorize);self.auth_button.pack(side='left')
        self.label('Нужен доступ metrika:read в регистрации приложения. Токен Директа не меняется.',10,MUTED).pack(anchor='w',pady=(5,10))
        self.panel=tk.Frame(self.frame,bg='#eae5ff')
        self.status=tk.StringVar(value='Вставьте ID счётчиков или получите их список. При запуске API не вызывается.')
        self.status_label=self.label('',10,MUTED,textvariable=self.status,wraplength=950);self.status_label.pack(anchor='w',pady=(0,10))
        row=tk.Frame(self.frame,bg=BG);row.pack(fill='x')
        self.label('Счётчики: по строкам, через пробел, запятую или точку с запятой',11).pack(anchor='w',pady=(5,5))
        self.ids=tk.Text(self.frame,height=3,font=('Segoe UI',11),wrap='word');self.ids.pack(fill='x')
        from counter_settings import load_counter_list,HISTORICAL_NOTE
        saved=load_counter_list();self.counter_revision=saved['revision'];self.ids.insert('1.0','\n'.join(saved['ids']))
        list_note=HISTORICAL_NOTE if saved['source']=='historical' else (saved['error'] or 'Сохранённый список загружен. Его можно отредактировать, очистить и сохранить снова.')
        self.ids_note=tk.StringVar(value=list_note)
        self.label('',9,MUTED,wraplength=950,textvariable=self.ids_note).pack(anchor='w',pady=5)
        actions=tk.Frame(self.frame,bg=BG);actions.pack(fill='x',pady=8)
        self.paste=ttk.Button(actions,text='Вставить список ID',command=self.paste_ids);self.paste.pack(side='left')
        self.save_ids_button=ttk.Button(actions,text='Сохранить счётчики',command=self.save_ids);self.save_ids_button.pack(side='left',padx=8)
        self.reload_ids_button=ttk.Button(actions,text='Загрузить сохранённые',command=self.reload_ids);self.reload_ids_button.pack(side='left',padx=4)
        self.list_button=ttk.Button(actions,text='Доступные счётчики',command=self.list_counters);self.list_button.pack(side='left',padx=8)
        self.available=tk.Frame(self.frame,bg=BG)
        self.listbox=tk.Listbox(self.available,height=4,selectmode='extended',exportselection=False);self.listbox.pack(side='left',fill='both',expand=True)
        scroll=ttk.Scrollbar(self.available,command=self.listbox.yview);scroll.pack(side='left',fill='y');self.listbox.configure(yscrollcommand=scroll.set)
        ttk.Button(self.available,text='Добавить выбранные ID',command=self.add_selected).pack(side='left',padx=10)
        period=tk.Frame(self.frame,bg=BG);period.pack(fill='x',pady=10)
        from desktop import previous_week
        self.start=tk.StringVar(value=previous_week()['dateFrom'])
        tk.Label(period,text='Понедельник:',bg=BG).pack(side='left')
        self.date_entry=ttk.Entry(period,textvariable=self.start,width=13);self.date_entry.pack(side='left',padx=8)
        self.fetch_button=ttk.Button(period,text='Получить посетителей',command=self.fetch);self.fetch_button.pack(side='left')
        self.cancel_button=ttk.Button(period,text='Остановить после текущего',command=self.stop.set,state='disabled');self.cancel_button.pack(side='left',padx=8)
        self.copy_button=ttk.Button(period,text='Копировать',command=self.copy,state='disabled');self.copy_button.pack(side='right')
        self.export_button=ttk.Button(period,text='CSV',command=self.export,state='disabled');self.export_button.pack(side='right',padx=8)
        self.period_display=tk.StringVar(value='Период ещё не загружен. Москва (UTC+03:00). Счётчики не суммируются.')
        self.label('',10,MUTED,textvariable=self.period_display).pack(anchor='w',pady=(0,8))
        table=tk.Frame(self.frame);table.pack(fill='both',expand=True)
        self.tree=ttk.Treeview(table,columns=('id','name','users','status'),show='headings',height=10)
        for key,title,width in [('id','ID',110),('name','Счётчик',270),('users','Посетители',110),('status','Статус / точность',390)]:
            self.tree.heading(key,text=title);self.tree.column(key,width=width,anchor='w')
        vs=ttk.Scrollbar(table,command=self.tree.yview);vs.pack(side='right',fill='y');self.tree.configure(yscrollcommand=vs.set);self.tree.pack(fill='both',expand=True)
        self.label('Нет доступа ≠ 0. Выборка и задержка данных отмечаются явно.\nПока реализованы общие посетители; источники и заполнение книги будут отдельным этапом.',10,MUTED).pack(anchor='w',pady=12)
        self.root.after(100,self.poll)
        if self.demo:self.status.set('ДЕМОНСТРАЦИЯ: Метрика не подключается; для подключения запустите без --demo.');self.auth_button.configure(state='disabled');self.fetch_button.configure(state='disabled');self.list_button.configure(state='disabled')
    def label(self,text,size=11,fg=INK,**kwargs):
        return tk.Label(self.frame,text=text,bg=BG,fg=fg,font=('Segoe UI',size,'bold' if size>=13 else 'normal'),justify='left',**kwargs)
    def show(self):self.frame.pack(fill='both',expand=True,padx=24,pady=20)
    def hide(self):self.frame.pack_forget()
    def close(self):
        with self.auth_lock:self.closed=True
        self.stop.set()
        if self.pending and not self.auth_in_flight:
            self.pending.consumed=True;self.pending.verifier='';self.pending=None
    def set_busy(self,value):
        self.busy=value
        for widget in (self.id_entry,self.ids,self.date_entry,self.auth_button,self.fetch_button,self.list_button,self.paste,self.save_ids_button,self.reload_ids_button):widget.configure(state='disabled' if value else 'normal')
        for widget in (self.copy_button,self.export_button):widget.configure(state='normal' if self.results and not value else 'disabled')
        self.cancel_button.configure(state='disabled')
    def clear_panel(self):
        for child in self.panel.winfo_children():child.destroy()
        self.panel.pack_forget()
    def panel_text(self,text):
        self.clear_panel();self.panel.pack(fill='x',before=self.status_label,pady=8)
        tk.Label(self.panel,text=text,bg='#eae5ff',fg='#51458f',wraplength=900,justify='left').pack(anchor='w',padx=10,pady=8)
    def cancel_auth(self):
        if self.pending:self.pending.consumed=True;self.pending.verifier='';self.pending=None
        self.clear_panel();self.set_busy(False);self.status.set('Авторизация отменена. Direct не изменён.')
    def client_id(self):
        import re
        value=self.client.get().strip()
        if not re.fullmatch('[a-fA-F0-9]{32}',value):raise ValueError('Укажите Client ID OAuth-приложения (32 символа), а ID счётчиков вставьте ниже.')
        return value
    def authorize(self):
        if self.demo or self.busy:return
        try:client=self.client_id()
        except ValueError as e:self.status.set(str(e));return
        self.set_busy(True)
        self.panel_text('Метрика: будет удалён локальный токен для этого Client ID и начат новый вход с правом metrika:read. Direct не затрагивается. После удаления отмена не восстановит прежний токен.')
        def begin():
            import webbrowser
            from metrica_auth import MetricaStore,begin as prepare
            try:
                MetricaStore(client).delete();pending,url=prepare(client)
                if not webbrowser.open(url):raise ValueError()
                self.pending=pending;self.enter_code(client)
            except Exception:self.clear_panel();self.set_busy(False);self.status.set('Вход не начат. Проверьте Client ID, разрешение metrika:read и хранилище Windows. После удаления старый токен мог быть утрачен.')
        ttk.Button(self.panel,text='Продолжить',command=begin).pack(side='left',padx=10,pady=8)
        ttk.Button(self.panel,text='Отмена',command=self.cancel_auth).pack(side='left',padx=10,pady=8)
    def enter_code(self,client):
        self.panel_text('Вставьте полный код из Яндекса. Код скрыт и не сохраняется в файлах.')
        code=tk.StringVar();ttk.Entry(self.panel,textvariable=code,show='•',width=45).pack(side='left',padx=10,pady=8)
        def paste():
            try:code.set(self.root.clipboard_get())
            except tk.TclError:self.status.set('Буфер обмена недоступен.')
        def cancel():code.set('');self.cancel_auth()
        def submit():
            from local_input import normalize_code
            try:entered=normalize_code(code.get())
            except ValueError:self.status.set('Вставьте полный код, а не ссылку.');return
            code.set('');pending=self.pending;self.auth_in_flight=True;self.clear_panel();self.status.set('Сохраняю авторизацию Метрики…')
            def exchange():return self.complete_authorization(pending,entered,client)
            self.background('auth',exchange)
        ttk.Button(self.panel,text='Вставить',command=paste).pack(side='left',padx=4)
        ttk.Button(self.panel,text='Подтвердить',command=submit).pack(side='left',padx=4)
        ttk.Button(self.panel,text='Отмена',command=cancel).pack(side='left',padx=4)
    def complete_authorization(self,pending,entered,client,*,http=None,store_factory=None):
        from metrica_auth import finish,MetricaStore
        from network_adapter import FixedHTTPS
        try:
            tokens=finish(pending,entered,http or FixedHTTPS(live_enabled=True))
            # Serialize close vs local commit. If closed while exchanging, do not save.
            with self.auth_lock:
                if self.closed:return None
                (store_factory or MetricaStore)(client).save(tokens)
            return client
        finally:
            pending.consumed=True;pending.verifier='';self.auth_in_flight=False
    def background(self,kind,fn):
        def run():
            try:self.events.put((kind,fn()))
            except Exception:self.events.put((kind+'_error',None))
        threading.Thread(target=run,daemon=True).start()
    def paste_ids(self):
        if self.busy:return
        try:self.ids.insert('end',('\n' if self.ids.get('1.0','end').strip() else '')+self.root.clipboard_get())
        except tk.TclError:self.status.set('Буфер обмена недоступен.')
    def save_ids(self):
        if self.busy:return
        from counter_settings import save_counter_list,saved_revision
        try:
            ids=save_counter_list(self.ids.get('1.0','end'),expected_revision=self.counter_revision)
            self.counter_revision=saved_revision(ids)
            self.ids.delete('1.0','end');self.ids.insert('1.0','\n'.join(ids))
            self.ids_note.set('Список сохранён. Соответствие сайтов и доступ проверяются по Метрике, не фактом сохранения ID.')
            self.status.set(('Сохранено счётчиков: '+str(len(ids))+'. Список автоматически загрузится при следующем запуске.') if ids else 'Пустой список сохранён. Исторические ID при следующем запуске не вернутся.')
        except ValueError as error:self.status.set(str(error))
        except OSError:self.status.set('Не удалось сохранить список. Предыдущее сохранение не изменено; проверьте доступ к папке пользователя.')
    def reload_ids(self):
        if self.busy:return
        self.panel_text('Загрузить сохранённый список? Несохранённый ввод в поле будет заменён.')
        def load():
            from counter_settings import load_counter_list,HISTORICAL_NOTE
            saved=load_counter_list()
            if saved['error']:self.status.set(saved['error']);return
            self.counter_revision=saved['revision'];self.ids.delete('1.0','end');self.ids.insert('1.0','\n'.join(saved['ids']))
            self.ids_note.set(HISTORICAL_NOTE if saved['source']=='historical' else 'Сохранённый список загружен.');self.clear_panel();self.status.set('Список загружен.')
        ttk.Button(self.panel,text='Загрузить',command=load).pack(side='left',padx=10,pady=8)
        ttk.Button(self.panel,text='Отмена',command=self.clear_panel).pack(side='left',padx=10,pady=8)
    def add_selected(self):
        if self.busy:return
        values=[str(self.counters[i]['id']) for i in self.listbox.curselection()]
        if values:self.ids.insert('end','\n'+'\n'.join(values))
    def list_counters(self):
        if self.busy or self.demo:return
        try:client=self.client_id()
        except ValueError as e:self.status.set(str(e));return
        self.clear_panel();self.set_busy(True);self.status.set('Получаю доступные счётчики…')
        def request():
            from metrica_auth import MetricaStore
            from metrica_core import list_counters
            from metrica_http import MetricaHTTP
            token=MetricaStore(client).access_token()
            return list_counters(lambda:token,MetricaHTTP(live_enabled=True))
        self.background('list',request)
    def fetch(self):
        if self.busy or self.demo:return
        try:
            from metrica_core import parse_counter_ids
            from desktop import period_from_start
            client=self.client_id();ids=parse_counter_ids(self.ids.get('1.0','end'));period=period_from_start(self.start.get().strip())
        except ValueError as e:self.status.set(str(e));return
        self.period_display.set('Результаты за '+period['dateFrom']+' — '+period['dateTo']+' · Москва UTC+03:00 · счётчики не суммируются')
        self.clear_panel();self.stop.clear();self.set_busy(True);self.cancel_button.configure(state='normal');self.results=[];self.tree.delete(*self.tree.get_children());self.status.set('Получаю посетителей за '+period['dateFrom']+' — '+period['dateTo']+'…')
        def request():
            from metrica_auth import MetricaStore
            from metrica_core import weekly_report
            from metrica_http import MetricaHTTP,MetricaError
            try:token=MetricaStore(client).access_token()
            except Exception:
                for cid in ids:self.events.put(('row',{'id':cid,'period':period,'error':'Авторизация отсутствует или истекла'}))
                return None
            http=MetricaHTTP(live_enabled=True)
            for cid in ids:
                if self.stop.is_set() or self.closed:
                    self.events.put(('row',{'id':cid,'period':period,'error':'Не запрошено: остановлено'}));continue
                try:
                    result=weekly_report(lambda:token,http,cid,period)
                    item={'id':cid,'period':period,'error':result['error']} if result.get('status')=='error' else {'id':cid,'period':period,'result':result}
                except MetricaError as e:item={'id':cid,'period':period,'error':str(e)}
                except Exception:item={'id':cid,'period':period,'error':'Ошибка данных: результат не подтверждён'}
                self.events.put(('row',item))
            return None
        self.background('batch',request)
    def poll(self):
        if self.closed:return
        try:
            while True:
                kind,value=self.events.get_nowait()
                if kind=='row':
                    self.results.append(value);result=value.get('result')
                    if result:
                        quality='Без семплирования' if result['exact'] else ('Выборка: '+str(result['sampleShare']) if result['sampled'] is True else 'Точность не подтверждена')
                        lag='задержка неизвестна' if result['dataLag'] is None else 'задержка '+str(result['dataLag'])+' с'
                        status=quality+'; '+lag
                        self.tree.insert('','end',values=(value['id'],result['counter']['name'],result['users'],status))
                    else:self.tree.insert('','end',values=(value['id'],'','—',value['error']))
                elif kind=='list':
                    self.counters=value;self.listbox.delete(0,'end')
                    for c in value:self.listbox.insert('end',str(c['id'])+' · '+c['name']+' · '+c['site'])
                    self.available.pack(fill='x',before=self.date_entry.master,pady=5);self.set_busy(False);self.status.set('Выберите счётчики и нажмите «Добавить выбранные ID». Можно также вставить ID вручную.')
                elif kind=='auth':
                    self.pending=None;self.set_busy(False)
                    try:save_client_id(value);self.status.set('Метрика подключена. Client ID сохранён, Direct не изменён.')
                    except Exception:self.status.set('Токен сохранён, но Client ID запомнить не удалось. Скопируйте публичный ID для следующего запуска.')
                elif kind=='batch':self.set_busy(False);self.status.set('Обработка закончена. Проверяйте статус каждой строки; ошибки не заменены нулём.')
                elif kind=='auth_error':self.pending=None;self.set_busy(False);self.status.set('Вход не подтверждён. При сбое после записи токен мог сохраниться. Direct не изменён.')
                else:self.set_busy(False);self.status.set('Запрос не выполнен. Проверьте сохранённую авторизацию и просмотр счётчиков у выбранного аккаунта.')
        except queue.Empty:pass
        if not self.closed:self.root.after(100,self.poll)
    def copy(self):
        if self.busy or not self.results:return
        try:self.root.clipboard_clear();self.root.clipboard_append(export_results(self.results,'\t'));self.status.set('Результаты скопированы без данных авторизации.')
        except tk.TclError:self.status.set('Буфер обмена недоступен.')
    def export(self):
        if self.busy or not self.results:return
        self.panel_text('Путь к CSV. В нём будут все результаты и отдельные статусы ошибок, без токенов.')
        path=tk.StringVar(value=str(Path.home()/'Afina_Metrica.csv'));ttk.Entry(self.panel,textvariable=path,width=75).pack(side='left',padx=10,pady=8)
        payload=export_results(self.results)
        def write(target):
            try:target.write_text(payload,encoding='utf-8-sig');self.clear_panel();self.status.set('CSV сохранён.')
            except OSError:self.status.set('Не удалось записать CSV. Проверьте путь.')
        def submit():
            target=Path(path.get().strip())
            if target.suffix.lower()!='.csv':self.status.set('Укажите расширение .csv.');return
            if target.exists():
                self.panel_text('Этот файл уже существует. Заменить?')
                ttk.Button(self.panel,text='Заменить',command=lambda:write(target)).pack(side='left',padx=10,pady=8)
                ttk.Button(self.panel,text='Отмена',command=self.clear_panel).pack(side='left',padx=10,pady=8)
            else:write(target)
        ttk.Button(self.panel,text='Сохранить',command=submit).pack(side='left',padx=5)
        ttk.Button(self.panel,text='Отмена',command=self.clear_panel).pack(side='left',padx=5)
