"""Read-only Direct catalogue and local draft preparation, no ad write operations."""
import json
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk
from banner_plan import inspect_image,make_plan,replacement_route
BG='#f3f4f9';INK='#1b263d';MUTED='#6c7b95'

class AdsView:
    def __init__(self,app):
        self.app=app;self.root=app.root;self.demo=app.demo;self.busy=False;self.closed=False;self.provider=None;self.data=None;self.account=None;self.plan=None;self.events=queue.Queue()
        self.frame=tk.Frame(self.root,bg=BG)
        self.label('Объявления и баннеры',25).pack(anchor='w')
        self.label('Каталог: только чтение. Замена баннера: локальный черновик, без отправки в Яндекс.',11,MUTED).pack(anchor='w',pady=8)
        self.label('ID кампаний (через пробел, запятую или по строкам):',11).pack(anchor='w')
        initial=' '.join(r['campaignId'] for r in (app.result or {}).get('rows',[]))
        self.campaigns=tk.StringVar(value=initial);self.entry=ttk.Entry(self.frame,textvariable=self.campaigns);self.entry.pack(fill='x',pady=6)
        self.load_button=ttk.Button(self.frame,text='Получить список объявлений',command=self.fetch);self.load_button.pack(anchor='w')
        self.status=tk.StringVar(value='Запрос начнётся после выбора кампаний и подтверждения кабинета.')
        self.status_label=self.label('',10,MUTED,textvariable=self.status,wraplength=950);self.status_label.pack(anchor='w',pady=8)
        self.panel=tk.Frame(self.frame,bg='#eae5ff')
        table=tk.Frame(self.frame);table.pack(fill='both',expand=True)
        self.tree=ttk.Treeview(table,columns=('id','type','title','images','status'),show='headings',height=9)
        for key,title,width in [('id','Объявление',105),('type','Тип',150),('title','Заголовок',320),('images','Изображений',95),('status','Состояние',160)]:
            self.tree.heading(key,text=title);self.tree.column(key,width=width)
        scroll=ttk.Scrollbar(table,command=self.tree.yview);scroll.pack(side='right',fill='y');self.tree.configure(yscrollcommand=scroll.set);self.tree.pack(fill='both',expand=True)
        self.tree.bind('<<TreeviewSelect>>',self.select)
        self.detail=tk.StringVar(value='Выберите объявление.');self.label('',10,textvariable=self.detail,wraplength=950).pack(anchor='w',pady=8)
        controls=tk.Frame(self.frame,bg=BG);controls.pack(fill='x')
        tk.Label(controls,text='Текущее изображение:',bg=BG).pack(side='left')
        self.slot=ttk.Combobox(controls,state='readonly',width=45);self.slot.pack(side='left',padx=6)
        self.preview_button=ttk.Button(controls,text='Превью в браузере',command=self.preview,state='disabled');self.preview_button.pack(side='left')
        self.label('Путь к новому PNG/JPEG (пока только локальная подготовка):',10,MUTED).pack(anchor='w',pady=(8,3))
        self.file_path=tk.StringVar();self.file_entry=ttk.Entry(self.frame,textvariable=self.file_path);self.file_entry.pack(fill='x')
        actions=tk.Frame(self.frame,bg=BG);actions.pack(fill='x',pady=8)
        self.prepare_button=ttk.Button(actions,text='Подготовить черновик замены',command=self.prepare,state='disabled');self.prepare_button.pack(side='left')
        self.save_button=ttk.Button(actions,text='Сохранить черновик',command=self.save,state='disabled');self.save_button.pack(side='left',padx=8)
        self.label('Отправка изменений отключена. Бюджеты, ставки, статусы и объявления не изменяются.',10,MUTED).pack(anchor='w',pady=8)
        self.root.after(100,self.poll)
        if self.demo:self.demo_data()
    def label(self,text,size=11,fg=INK,**kw):return tk.Label(self.frame,text=text,font=('Segoe UI',size,'bold' if size>=13 else 'normal'),bg=BG,fg=fg,justify='left',**kw)
    def show(self):self.frame.pack(fill='both',expand=True,padx=24,pady=20)
    def hide(self):self.frame.pack_forget()
    def close(self):self.closed=True;self.provider=None
    def clear_panel(self):
        for child in self.panel.winfo_children():child.destroy()
        self.panel.pack_forget()
    def panel_text(self,text):
        self.clear_panel();self.panel.pack(fill='x',before=self.status_label,pady=5)
        tk.Label(self.panel,text=text,bg='#eae5ff',wraplength=930,justify='left').pack(anchor='w',padx=10,pady=8)
    def set_busy(self,value):
        self.busy=value
        for w in (self.entry,self.load_button,self.file_entry):w.configure(state='disabled' if value else 'normal')
        ad=self.selected()
        ready=ad and ad.get('images') and replacement_route(ad) not in ('UNSUPPORTED','EXISTING_CREATIVE_ONLY')
        self.prepare_button.configure(state='normal' if ready and not value else 'disabled');self.save_button.configure(state='normal' if self.plan and not value else 'disabled')
        self.preview_button.configure(state='normal' if ad and ad.get('images') and not value else 'disabled')
    def background(self,kind,fn):
        def run():
            try:self.events.put((kind,fn()))
            except Exception:self.events.put(('error',None))
        threading.Thread(target=run,daemon=True).start()
    def fetch(self):
        if self.busy:return
        if self.demo:self.demo_data();return
        try:
            from ads_catalog import parse_campaign_ids
            ids=parse_campaign_ids(self.campaigns.get())
        except ValueError as e:self.status.set(str(e));return
        self.clear_panel();self.set_busy(True);self.status.set('Проверяю кабинет Direct…')
        def identify():
            from windows_credentials import CredentialStore
            from verify_direct import KNOWN_CLIENT_ID,identity
            from network_adapter import FixedHTTPS
            token=CredentialStore(self.app.client_id or KNOWN_CLIENT_ID).access_token();provider=lambda:token
            return identity(provider,FixedHTTPS(live_enabled=True)),provider,ids
        self.background('identity',identify)
    def poll(self):
        if self.closed:return
        try:
            while True:
                kind,value=self.events.get_nowait()
                if kind=='identity':
                    account,self.provider,ids=value
                    self.panel_text('Кабинет '+account['login']+' · '+account['clientId']+'. Получить объявления выбранных кампаний? Только чтение.')
                    def cancel():self.provider=None;self.clear_panel();self.set_busy(False);self.status.set('Загрузка отменена.')
                    def accept(account=account,ids=ids,provider=self.provider):
                        self.clear_panel();self.status.set('Загружаю каталог объявлений…')
                        def request():
                            from ads_catalog import catalog
                            from catalog_http import CatalogHTTP
                            return account,catalog(provider,CatalogHTTP(live_enabled=True),ids)
                        self.background('catalog',request)
                    ttk.Button(self.panel,text='Получить каталог',command=accept).pack(side='left',padx=10,pady=8)
                    ttk.Button(self.panel,text='Отмена',command=cancel).pack(side='left',padx=10,pady=8)
                elif kind=='catalog':self.provider=None;self.display(*value);self.set_busy(False)
                else:self.provider=None;self.set_busy(False);self.status.set('Каталог не получен. Проверьте авторизацию Direct и доступ к кампаниям. Предыдущие данные не обновлены.')
        except queue.Empty:pass
        if not self.closed:self.root.after(100,self.poll)
    def display(self,account,data):
        self.account=account;self.data=data;self.plan=None;self.tree.delete(*self.tree.get_children())
        for i,ad in enumerate(data['ads']):self.tree.insert('','end',iid=str(i),values=(ad['id'],ad['type']+' / '+str(ad.get('subtype') or ''),ad.get('title') or '—',len(ad['images']),str(ad.get('state') or '')+' / '+str(ad.get('status') or '')))
        self.detail.set('Выберите объявление.');self.slot.configure(values=());self.status.set(('ДЕМОНСТРАЦИЯ · ' if self.demo else '')+'Каталог загружен: '+str(len(data['ads']))+' объявлений. Ничего не изменено.')
    def selected(self):
        ids=self.tree.selection()
        if not ids or not self.data:return None
        try:return self.data['ads'][int(ids[0])]
        except (ValueError,IndexError):return None
    def select(self,event=None):
        if self.busy:return
        self.clear_panel();ad=self.selected();self.plan=None;self.save_button.configure(state='disabled')
        if not ad:return
        self.slot.configure(values=ad['images'])
        if ad['images']:self.slot.current(0)
        self.detail.set('Кампания '+ad['campaignId']+' · группа '+ad['adGroupId']+' · '+str(ad.get('href') or '')+'\nМаршрут: '+replacement_route(ad)+'. Типы с CreativeId и неизвестные типы пока только просмотр.')
        self.prepare_button.configure(state='normal' if ad['images'] and replacement_route(ad) not in ('UNSUPPORTED','EXISTING_CREATIVE_ONLY') else 'disabled')
        self.preview_button.configure(state='normal' if ad['images'] else 'disabled')
    def preview(self):
        if self.busy:return
        ad=self.selected();idx=self.slot.current()
        if not ad or not 0<=idx<len(ad['images']):return
        hash_value=ad['images'][idx]
        images=self.data.get('images',[])
        metadata=next((x for x in images if x.get('hash')==hash_value),None)
        url=(metadata or {}).get('previewUrl') or (metadata or {}).get('originalUrl')
        if not url:self.status.set('Ссылка на превью недоступна. Не заменяю её догадкой.');return
        from ads_catalog import safe_url
        import webbrowser
        url=safe_url(url)
        if not url:self.status.set('Ссылка превью не прошла безопасную проверку.');return
        try:
            if not webbrowser.open(url):raise ValueError()
        except Exception:self.status.set('Не удалось открыть превью.')
    def prepare(self):
        if self.busy:return
        ad=self.selected()
        if not ad:self.status.set('Выберите объявление.');return
        try:
            image=inspect_image(self.file_path.get().strip());plan=make_plan(self.account,ad,image,self.slot.current())
        except (ValueError,OSError) as e:self.status.set(str(e) if isinstance(e,ValueError) else 'Не удалось прочитать выбранный файл.');return
        self.plan=plan;self.save_button.configure(state='normal')
        self.panel_text('ЧЕРНОВИК, НЕ ОТПРАВЛЕН. Объявление '+ad['id']+'; заменяемый хэш '+plan['replaceHash']+'\nНовый файл: '+image['fileName']+' · '+str(image['width'])+'×'+str(image['height'])+' · '+image['format']+'\nSHA256: '+image['sha256']+'\nОстальные изображения сохраняются. Совместимость API и модерация ещё не проверены. Выполнена только проверка заголовка файла.')
        self.status.set('Черновик готов локально. Запросов загрузки/замены нет.')
    def save(self):
        if self.busy or not self.plan:return
        payload=json.dumps(self.plan,ensure_ascii=False,indent=2)
        self.panel_text('Сохранить локальный JSON-черновик (не отправка в Яндекс):')
        path=tk.StringVar(value=str(Path.home()/('Afina_Banner_Draft_'+self.plan['ad']['id']+'.json')));ttk.Entry(self.panel,textvariable=path,width=75).pack(side='left',padx=10,pady=8)
        def write(target):
            try:target.write_text(payload,encoding='utf-8');self.clear_panel();self.status.set('Черновик сохранён. Объявление не изменено.')
            except OSError:self.status.set('Не удалось сохранить черновик.')
        def submit():
            target=Path(path.get().strip())
            if target.suffix.lower()!='.json':self.status.set('Укажите файл .json.');return
            if target.exists():
                self.panel_text('Файл существует. Заменить локальный черновик?')
                ttk.Button(self.panel,text='Заменить',command=lambda:write(target)).pack(side='left',padx=10,pady=8)
                ttk.Button(self.panel,text='Отмена',command=self.clear_panel).pack(side='left',padx=10,pady=8)
            else:write(target)
        ttk.Button(self.panel,text='Сохранить',command=submit).pack(side='left',padx=5)
        ttk.Button(self.panel,text='Отмена',command=self.clear_panel).pack(side='left',padx=5)
    def demo_data(self):
        self.display({'clientId':'DEMO','login':'demo-offline'},{'ads':[{'id':'1','campaignId':'10','adGroupId':'20','type':'TEXT_AD','subtype':None,'state':'ON','status':'ACCEPTED','title':'Демонстрационное объявление','images':['demo-image-hash'],'creativeIds':[],'href':'https://example.com'}],'images':[],'creatives':[],'complete':True})
