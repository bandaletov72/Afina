"""Local banner replacement drafts only. No network and no write API payloads."""
from pathlib import Path
import hashlib
import struct

MAX_IMAGE_BYTES=16*1024*1024

def inspect_image(path):
    path=Path(path)
    with path.open('rb') as f:raw=f.read(MAX_IMAGE_BYTES+1)
    if not raw or len(raw)>MAX_IMAGE_BYTES:raise ValueError('Файл пуст или превышает локальный лимит 16 МБ.')
    width=height=None;fmt=None
    if raw.startswith(b'\x89PNG\r\n\x1a\n') and len(raw)>=33 and raw[12:16]==b'IHDR':
        width,height=struct.unpack('>II',raw[16:24]);fmt='PNG'
    elif raw.startswith(b'\xff\xd8'):
        fmt='JPEG';pos=2
        while pos+4<=len(raw):
            if raw[pos]!=255:raise ValueError('Некорректный заголовок JPEG.')
            while pos<len(raw) and raw[pos]==255:pos+=1
            if pos>=len(raw):break
            marker=raw[pos];pos+=1
            if marker in (0xd9,0xda):break
            if marker in (0x01,0xd8) or 0xd0<=marker<=0xd7:continue
            if pos+2>len(raw):break
            size=int.from_bytes(raw[pos:pos+2],'big')
            if size<2 or pos+size>len(raw):raise ValueError('Повреждённый JPEG.')
            if marker in (0xc0,0xc1,0xc2,0xc3,0xc5,0xc6,0xc7,0xc9,0xca,0xcb,0xcd,0xce,0xcf):
                if size<8:raise ValueError('Повреждённый JPEG.')
                height,width=struct.unpack('>HH',raw[pos+3:pos+7]);break
            pos+=size
    if fmt is None or width is None or not 0<width<=100000 or not 0<height<=100000:raise ValueError('Нужен PNG или JPEG с читаемыми размерами.')
    return {'fileName':path.name,'format':fmt,'width':width,'height':height,'sizeBytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'validation':'HEADER_ONLY_API_COMPATIBILITY_NOT_VERIFIED'}

def replacement_route(ad):
    kind=ad.get('type');sub=ad.get('subtype')
    if kind=='TEXT_AD':return 'TEXT_AD_IMAGE'
    if kind=='IMAGE_AD' and sub=='TEXT_IMAGE_AD':return 'FIXED_IMAGE'
    if kind=='RESPONSIVE_AD':return 'RESPONSIVE_IMAGE_SLOT'
    if kind=='IMAGE_AD' and sub=='TEXT_AD_BUILDER_AD' or kind=='CPM_BANNER_AD':return 'EXISTING_CREATIVE_ONLY'
    return 'UNSUPPORTED'

def make_plan(account,ad,image,slot):
    route=replacement_route(ad)
    if route in ('UNSUPPORTED','EXISTING_CREATIVE_ONLY'):raise ValueError('Этот тип объявления пока только для просмотра; замена локальным изображением не подготовлена.')
    images=ad.get('images',[])
    if type(slot) is not int or not 0<=slot<len(images):raise ValueError('Выберите существующее изображение для замены.')
    if len(images)>5 or (route!='RESPONSIVE_IMAGE_SLOT' and len(images)!=1):raise ValueError('Структура изображений требует отдельной проверки.')
    return {'schemaVersion':1,'status':'DRAFT_NOT_SENT','account':{k:account[k] for k in ('clientId','login')},'ad':{k:ad.get(k) for k in ('id','campaignId','adGroupId','type','subtype')},'route':route,'currentImages':list(images),'replaceSlot':slot,'replaceHash':images[slot],'preserveOtherImages':True,'candidate':dict(image),'requires':['Повторно прочитать объявление и сравнить хэши','Проверить требования API к формату/размеру/типу изображения','Проверить текст и содержание нового баннера','Перед загрузкой перечитать файл и сравнить SHA256 с черновиком','Получить подтверждение конкретной замены','Реализовать и проверить обработку модерации и частичных ошибок'],'sentToYandex':False}
