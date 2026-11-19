"""Editable, public counter IDs only. No OAuth/credential dependency."""
import json
import hashlib
import os
from pathlib import Path
import tempfile
from metrica_core import parse_counter_ids

HISTORICAL_IDS=[]
HISTORICAL_NOTE='Введите ID своих счётчиков или загрузите доступные из Метрики.'

def counter_path():
    return Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'AppData'/'Local')))/'Afina'/'metrica_counters.json'

def load_counter_list(path=None):
    path=Path(path) if path is not None else counter_path()
    try:
        with path.open('rb') as stream:
            raw=stream.read(65537)
        if len(raw)>65536:raise ValueError()
        obj=json.loads(raw)
        if type(obj) is not dict or set(obj)!={'version','ids'} or type(obj['version']) is not int or obj['version']!=1 or type(obj['ids']) is not list:raise ValueError()
        values=obj['ids']
        if any(type(x) is not str for x in values):raise ValueError()
        ids=parse_counter_ids('\n'.join(values)) if values else []
        return {'ids':ids,'source':'saved','error':None,'revision':hashlib.sha256(raw).hexdigest()}
    except FileNotFoundError:
        return {'ids':list(HISTORICAL_IDS),'source':'historical','error':None,'revision':None}
    except Exception:
        # Corruption is not permission to replace a user's list with defaults.
        return {'ids':[],'source':'error','revision':hashlib.sha256(raw).hexdigest() if 'raw' in locals() else 'UNREADABLE','error':'Сохранённый список не удалось прочитать. Он не изменён. Введите ID и сохраните список заново.'}

_UNSET=object()
def payload(ids):return json.dumps({'version':1,'ids':ids},ensure_ascii=False)
def saved_revision(ids):return hashlib.sha256(payload(ids).encode('utf-8')).hexdigest()

def save_counter_list(text,path=None,*,expected_revision=_UNSET):
    if type(text) is not str:raise ValueError('Введите список ID.')
    ids=parse_counter_ids(text) if text.strip() else []
    path=Path(path) if path is not None else counter_path()
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=None;lock=path.with_name(path.name+'.lock')
    try:
        descriptor=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(descriptor)
    except FileExistsError:raise ValueError('Список сейчас сохраняется другим экземпляром. Повторите позже; если приложение аварийно закрывалось, потребуется проверка файла блокировки.') from None
    try:
        if expected_revision is not _UNSET:
            try:
                with path.open('rb') as current:revision=hashlib.sha256(current.read(65537)).hexdigest()
            except FileNotFoundError:revision=None
            if revision!=expected_revision:raise ValueError('Список изменён другим экземпляром. Нажмите «Загрузить сохранённые», затем повторите изменения. Ваш ввод пока оставлен на экране.')
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,prefix='.metrica_counters_',suffix='.tmp',delete=False) as stream:
            temp=Path(stream.name)
            stream.write(payload(ids))
            stream.flush();os.fsync(stream.fileno())
        os.replace(temp,path)
    finally:
        try:lock.unlink(missing_ok=True)
        except OSError:pass
        if temp is not None:
            try:temp.unlink(missing_ok=True)
            except OSError:pass
    return ids
