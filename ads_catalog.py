"""Atomic read-only Direct catalog. No write request builders or image downloads."""
import re
import ipaddress
from urllib.parse import urlsplit

LIMIT=1000
MAX_PAGES=100
MAX_OBJECTS=100000
FIELDS={'ads':['Id','CampaignId','AdGroupId','Type','Subtype','State','Status'], 'adimages':['AdImageHash','Name','Type','Subtype','PreviewUrl','OriginalUrl'],'creatives':['Id','Type','Name','PreviewUrl','ThumbnailUrl','Width','Height','IsAdaptive']}
EXTRA={'TextAdFieldNames':['Title','AdImageHash','Href'],'TextImageAdFieldNames':['AdImageHash','Href'],'ResponsiveAdFieldNames':['Titles','AdImages','Href'],'TextAdBuilderAdFieldNames':['Creative','Href'],'CpmBannerAdBuilderAdFieldNames':['Creative','Href']}
class CatalogError(ValueError):
    def __init__(self,code='INVALID_RESPONSE'):
        messages={'INVALID_INPUT':'Укажите хотя бы один положительный ID кампании; максимум 100 кампаний.','INVALID_RESPONSE':'Каталог не подтверждён: неожиданный ответ API.','PAGINATION':'Каталог не подтверждён: неполная или изменившаяся выборка.','LIMIT':'Каталог превысил безопасный объём.','FORBIDDEN':'Разрешены только выбранные методы чтения каталога.','DISABLED':'Живые запросы отключены.','AUTH':'Авторизация недействительна или доступ запрещён.','NETWORK':'Не удалось получить каталог. Повторите позже.'}
        self.code=code if code in messages else 'INVALID_RESPONSE';super().__init__(messages[self.code])
def ident(value):
    if type(value) is int:value=str(value)
    if type(value) is not str or not re.fullmatch('[0-9]+',value) or len(value)>16384:raise CatalogError('INVALID_INPUT')
    value=value.lstrip('0')
    # API declares long, so enforce representable numeric range, not a digit-count UI limit.
    if not value or len(value)>19 or (len(value)==19 and value>'9223372036854775807'):raise CatalogError('INVALID_INPUT')
    return value

def campaign_ids(value):
    if type(value) is str:
        if len(value.encode())>16384:raise CatalogError('INVALID_INPUT')
        value=[v for v in re.split(r'[\s,;]+',value.strip()) if v]
    if type(value) is not list or not value or len(value)>100:raise CatalogError('INVALID_INPUT')
    return list(dict.fromkeys(ident(v) for v in value))
def text(value,optional=False):
    if value is None and optional:return None
    if type(value) is not str or len(value)>4096 or any(ord(c)<32 for c in value):raise CatalogError()
    return value

def image_hash(value):
    if type(value) is not str or not re.fullmatch(r'[A-Za-z0-9_-]{1,512}',value):raise CatalogError()
    return value

def safe_url(value):
    if value is None:return None
    if type(value) is not str or len(value)>8192 or any(c.isspace() or ord(c)<32 for c in value) or '\\' in value:return None
    try:
        p=urlsplit(value);host=p.hostname
        if p.scheme!='https' or not host or p.username or p.password or p.port not in (None,443):return None
        if host.lower()=='localhost' or '.' not in host or host.lower().endswith(('.local','.localhost')):return None
        try:
            if not ipaddress.ip_address(host).is_global:return None
        except ValueError:pass
        return value
    except ValueError:return None

def params_for(service,selection,offset=0):
    p={'SelectionCriteria':selection,'FieldNames':list(FIELDS[service]),'Page':{'Limit':LIMIT,'Offset':offset}}
    if service=='ads':p.update({k:list(v) for k,v in EXTRA.items()})
    return p

def normalize_ad(obj):
    if type(obj) is not dict:raise CatalogError()
    try:
        result={k:ident(obj[v]) for k,v in [('id','Id'),('campaignId','CampaignId'),('adGroupId','AdGroupId')]}
        result.update({k:text(obj[v]) for k,v in [('type','Type'),('subtype','Subtype'),('state','State'),('status','Status')]})
        result.update(title=None,images=[],creativeIds=[],href=None,supported=False)
        kind=result['type'];sub=result['subtype'];key=None
        if kind=='TEXT_AD' and sub=='NONE':key='TextAd'
        elif kind=='IMAGE_AD' and sub=='TEXT_IMAGE_AD':key='TextImageAd'
        elif kind=='RESPONSIVE_AD' and sub=='NONE':key='ResponsiveAd'
        elif kind=='IMAGE_AD' and sub=='TEXT_AD_BUILDER_AD':key='TextAdBuilderAd'
        elif kind=='CPM_BANNER_AD' and sub=='NONE':key='CpmBannerAdBuilderAd'
        if key is None:return result
        details=obj[key]
        if type(details) is not dict:raise CatalogError()
        result['href']=safe_url(details.get('Href'));result['supported']=True
        if key=='ResponsiveAd':
            titles=details.get('Titles')
            if type(titles) is not list or len(titles)>100:raise CatalogError()
            result['title']=' | '.join(text(t['Title']) for t in titles)
            images=details.get('AdImages')
            if images is not None:
                if type(images) is not dict or type(images.get('Items')) is not list or len(images['Items'])>100:raise CatalogError()
                result['images']=list(dict.fromkeys(image_hash(i['ImageHash']) for i in images['Items']))
        elif key in ('TextAd','TextImageAd'):
            if key=='TextAd':result['title']=text(details.get('Title'),True)
            value=details.get('AdImageHash')
            if value is not None:result['images']=[image_hash(value)]
        else:result['creativeIds']=[ident(details['Creative']['CreativeId'])]
        return result
    except CatalogError:raise
    except Exception:raise CatalogError() from None

def normalize_image(obj):
    try:return {'hash':image_hash(obj['AdImageHash']),'name':text(obj['Name']),'type':text(obj['Type']),'subtype':text(obj['Subtype']),'previewUrl':safe_url(obj.get('PreviewUrl')),'originalUrl':safe_url(obj.get('OriginalUrl'))}
    except CatalogError:raise
    except Exception:raise CatalogError() from None

def normalize_creative(obj):
    try:
        result={'id':ident(obj['Id']),'type':text(obj['Type']),'name':text(obj['Name']),'previewUrl':safe_url(obj.get('PreviewUrl')),'thumbnailUrl':safe_url(obj.get('ThumbnailUrl')),'isAdaptive':text(obj['IsAdaptive'])}
        for key,source in [('width','Width'),('height','Height')]:
            value=obj[source]
            if type(value) is not int or not 0<=value<=100000:raise CatalogError()
            result[key]=value
        return result
    except CatalogError:raise
    except Exception:raise CatalogError() from None

def pages(provider,http,service,selection,normalizer,key):
    result=[];seen=set();offset=0;array={'ads':'Ads','adimages':'AdImages','creatives':'Creatives'}[service]
    for _ in range(MAX_PAGES):
        obj=http.get(service,params_for(service,selection,offset),provider())
        if type(obj) is not dict or 'error' in obj or type(obj.get('result')) is not dict:raise CatalogError()
        data=obj['result'];rows=data.get(array)
        if type(rows) is not list or len(rows)>LIMIT:raise CatalogError()
        for row in rows:
            value=normalizer(row)
            if value[key] in seen:raise CatalogError('PAGINATION')
            seen.add(value[key]);result.append(value)
            if len(result)>MAX_OBJECTS:raise CatalogError('LIMIT')
        limited=data.get('LimitedBy')
        if limited is None:return result
        if type(limited) is not int or not rows or limited!=offset+len(rows):raise CatalogError('PAGINATION')
        offset=limited
    raise CatalogError('PAGINATION')

def catalog(provider,http,campaign_ids_value):
    campaigns=campaign_ids(campaign_ids_value)
    try:
        ads=pages(provider,http,'ads',{'CampaignIds':[int(v) for v in campaigns]},normalize_ad,'id')
        if any(a['campaignId'] not in campaigns for a in ads):raise CatalogError()
        hashes=list(dict.fromkeys(h for a in ads for h in a['images']));cids=list(dict.fromkeys(c for a in ads for c in a['creativeIds']))
        if len(hashes)>MAX_OBJECTS or len(cids)>MAX_OBJECTS:raise CatalogError('LIMIT')
        images=[];creatives=[]
        for start in range(0,len(hashes),1000):images+=pages(provider,http,'adimages',{'AdImageHashes':hashes[start:start+1000]},normalize_image,'hash')
        for start in range(0,len(cids),1000):creatives+=pages(provider,http,'creatives',{'Ids':[int(v) for v in cids[start:start+1000]]},normalize_creative,'id')
        if {i['hash'] for i in images}!=set(hashes) or len(images)!=len(hashes) or {c['id'] for c in creatives}!=set(cids) or len(creatives)!=len(cids):raise CatalogError('PAGINATION')
        return {'ads':ads,'images':images,'creatives':creatives,'complete':True,'campaignIds':campaigns}
    except CatalogError:raise
    except Exception:raise CatalogError('NETWORK') from None

# UI-facing parser name.
parse_campaign_ids=campaign_ids
