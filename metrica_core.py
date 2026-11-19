"""Read-only Metrica services. Pure parsing and bounded request orchestration."""
import math
import re
from report_core import build_request

MAX_INPUT_BYTES=16384
MAX_COUNTERS=500
PAGE_SIZE=100
MAX_PAGES=1000

class MetricaError(ValueError):
    def __init__(self, code='INVALID_RESPONSE'):
        allowed={'INVALID_INPUT','TOO_MANY_IDS','INVALID_PERIOD','INVALID_RESPONSE','PAGINATION_LIMIT','PAGINATION_CHANGED','LIVE_DISABLED','FORBIDDEN_REQUEST','INVALID_TOKEN','NETWORK_ERROR','HTTP_401','HTTP_403','HTTP_404','HTTP_429','HTTP_ERROR','RESPONSE_LIMIT','REDIRECT_REFUSED'}
        self.code=code if code in allowed else 'INVALID_RESPONSE'
        messages={'INVALID_INPUT':'Введите положительные ID счётчиков цифрами, через пробел, запятую или новую строку (до 16 КБ текста).','TOO_MANY_IDS':'За один раз можно выбрать до 500 счётчиков.','INVALID_PERIOD':'Нужен период с понедельника по воскресенье, даты ГГГГ-ММ-ДД.','HTTP_401':'Авторизация недействительна. Выполните вход снова.','HTTP_403':'У аккаунта нет доступа к счётчику.','HTTP_404':'Счётчик не найден.','HTTP_429':'Лимит запросов. Повторите позже.','PAGINATION_CHANGED':'Список счётчиков изменился во время загрузки. Повторите загрузку.','LIVE_DISABLED':'Живые запросы отключены.','NETWORK_ERROR':'Не удалось получить данные. Проверьте подключение и повторите.'}
        super().__init__(self.code+': '+messages.get(self.code,'Ответ не прошёл проверку. Данные не подтверждены.'))

def counter_id(value):
    if type(value) is int:
        try:value=str(value)
        except ValueError:raise MetricaError('INVALID_INPUT') from None
    if type(value) is not str or len(value)>MAX_INPUT_BYTES or not re.fullmatch(r'[0-9]+',value):
        raise MetricaError('INVALID_INPUT')
    normalized=value.lstrip('0')
    if not normalized:raise MetricaError('INVALID_INPUT')
    return normalized

def parse_counter_ids(text):
    if type(text) is not str or len(text.encode('utf-8'))>MAX_INPUT_BYTES:raise MetricaError('INVALID_INPUT')
    parts=re.split(r'[\s,;]+',text.strip())
    if not parts or not parts[0]:raise MetricaError('INVALID_INPUT')
    result=[];seen=set()
    for part in parts:
        if not part:continue
        value=counter_id(part)
        if value not in seen:seen.add(value);result.append(value)
        if len(result)>MAX_COUNTERS:raise MetricaError('TOO_MANY_IDS')
    return result

def period_params(period):
    try:build_request(period)
    except Exception:raise MetricaError('INVALID_PERIOD') from None
    return {'date1':period['dateFrom'],'date2':period['dateTo'],'metrics':'ym:s:users','accuracy':'full','timezone':'+03:00'}

def safe_counter(obj):
    if type(obj) is not dict:raise MetricaError()
    try:
        cid=counter_id(obj['id']);name=obj['name'];site=obj['site']
        if any(type(x) is not str or len(x)>2048 or any(ord(c)<32 for c in x) for x in (name,site)):raise ValueError()
        return {'id':cid,'name':name,'site':site}
    except Exception:raise MetricaError() from None

def list_counters(provider,http):
    result=[];seen=set();offset=1;expected_total=None
    for _ in range(MAX_PAGES):
        obj=http.get('/management/v1/counters',{'offset':offset,'per_page':PAGE_SIZE},provider())
        if type(obj) is not dict or type(obj.get('counters')) is not list or type(obj.get('rows')) is not int or not 0<=obj['rows']<=100000:raise MetricaError()
        total=obj['rows'];items=obj['counters']
        if expected_total is not None and total!=expected_total:raise MetricaError('PAGINATION_CHANGED')
        expected_total=total
        if len(items)>PAGE_SIZE or (not items and len(result)<total):raise MetricaError('PAGINATION_CHANGED')
        for item in items:
            row=safe_counter(item)
            if row['id'] in seen:raise MetricaError('PAGINATION_CHANGED')
            seen.add(row['id']);result.append(row)
        if len(result)==total:return result
        if len(result)>total:raise MetricaError('PAGINATION_CHANGED')
        offset+=len(items)
    raise MetricaError('PAGINATION_LIMIT')

def parse_users(obj,params):
    if type(obj) is not dict or 'errors' in obj:raise MetricaError()
    query=obj.get('query')
    if type(query) is not dict or any(query.get(k)!=params[k] for k in ('date1','date2','timezone')) or query.get('metrics')!=['ym:s:users']:raise MetricaError()
    try:
        ids=query.get('ids')
        if type(ids) is not list or len(ids)!=1 or counter_id(ids[0])!=counter_id(params['ids']):raise ValueError()
    except Exception:raise MetricaError('INVALID_RESPONSE') from None
    totals=obj.get('totals')
    if type(totals) is not list or len(totals)!=1:raise MetricaError()
    users=totals[0]
    if type(users) not in (int,float) or not math.isfinite(users) or not 0<=users<=10**15:raise MetricaError()
    sampled=obj.get('sampled');share=obj.get('sample_share');lag=obj.get('data_lag')
    if sampled is not None and type(sampled) is not bool:raise MetricaError()
    if share is not None and (type(share) not in (int,float) or not math.isfinite(share) or not 0<=share<=1):raise MetricaError()
    if lag is not None and (type(lag) is not int or lag<0):raise MetricaError()
    exact=sampled is False and share==1
    if exact and users!=int(users):raise MetricaError()
    return {'users':int(users) if users==int(users) else users,'exact':exact,'sampled':sampled,'sampleShare':share,'dataLag':lag}

def weekly_report(provider,http,counter_id_value,period):
    cid=counter_id(counter_id_value);params=period_params(period);params['ids']=cid
    result={'counter':{'id':cid,'name':None,'site':None},'counterId':cid,'counterName':None,'site':None,'users':None,'exact':False,'sampled':None,'sampleShare':None,'dataLag':None,'period':dict(period),'timezone':'Europe/Moscow','status':'error'}
    try:
        info=http.get('/management/v1/counter/'+cid,{},provider())
        counter=safe_counter(info.get('counter') if type(info) is dict else None)
        if counter['id']!=cid:raise MetricaError()
        result.update(counter=counter,counterName=counter['name'],site=counter['site'])
        result.update(parse_users(http.get('/stat/v1/data',params,provider()),params));result['status']='ok'
    except Exception as error:
        code=error.code if isinstance(error,MetricaError) else 'NETWORK_ERROR'
        result['errorCode']=code
        result['error']=result['errorMessage']=str(MetricaError(code))
    return result
