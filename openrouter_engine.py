"""OpenRouter vision + strict structured output, sharing the existing scan workflow."""
import base64,http.client,json,ssl,time,threading
from pathlib import Path
from concurrent.futures import CancelledError
import jsonschema
from engine import Astra

GATEWAY_EFFORTS=['none','minimal','low','medium','high','xhigh','max']

def request_json(path,key=None,payload=None,cancel=None):
    if path not in ['/api/v1/models','/api/v1/key','/api/v1/chat/completions']:raise ValueError('Geçersiz OpenRouter yolu.')
    if cancel is not None and cancel.is_set():raise CancelledError()
    conn=http.client.HTTPSConnection('openrouter.ai',timeout=180,context=ssl.create_default_context(cafile='/etc/ssl/cert.pem' if Path('/etc/ssl/cert.pem').exists() else None))
    result={};done=threading.Event()
    def run():
        try:
            headers={'Content-Type':'application/json','X-Title':'Fotograf Masasi'}
            if key:headers['Authorization']='Bearer '+key
            conn.request('POST' if payload is not None else 'GET',path,body=json.dumps(payload).encode() if payload is not None else None,headers=headers)
            response=conn.getresponse();raw=response.read(24*1024*1024)
            # Don't surface raw provider errors: they can echo request data or credentials.
            if response.status>=400:
                messages={401:'API anahtarı geçersiz.',402:'OpenRouter bakiyesi yetersiz.',429:'OpenRouter hız sınırı; daha sonra yeniden dene.',400:'Model, effort veya JSON şeması bu sağlayıcıda desteklenmiyor.'}
                raise RuntimeError(f'OpenRouter HTTP {response.status}: '+messages.get(response.status,'İstek başarısız; başka modele geçilmedi.'))
            result['value']=json.loads(raw)
            if 'error' in result['value']:raise RuntimeError('OpenRouter model hatası döndürdü; işlem uygulanmadı.')
        except Exception as e:result['error']=e if isinstance(e,RuntimeError) else RuntimeError('OpenRouter bağlantısı/yanıtı tamamlanamadı. Anahtar veya görseller hata kaydına yazılmadı.')
        finally:conn.close();done.set()
    threading.Thread(target=run,daemon=True).start()
    start=time.monotonic()
    while not done.wait(.2):
        if cancel is not None and cancel.is_set():
            conn.close();raise CancelledError()
        if time.monotonic()-start>190:
            conn.close();raise RuntimeError('OpenRouter yanıtı zaman aşımına uğradı; yeniden denemeden önce sağlayıcı durumunu kontrol et.')
    if cancel is not None and cancel.is_set():raise CancelledError()
    if 'error' in result:raise result['error']
    return result['value']

def parse_models(data):
    result=[]
    for m in data.get('data',[]):
        arch=m.get('architecture') or {};params=m.get('supported_parameters') or []
        if 'image' not in arch.get('input_modalities',[]) or 'text' not in arch.get('output_modalities',[]):continue
        if 'structured_outputs' not in params:continue
        reasoning=m.get('reasoning') or {};efforts=['default']
        if 'supported_efforts' in reasoning:
            supported=reasoning['supported_efforts']
            efforts += GATEWAY_EFFORTS if supported is None else [e for e in supported if e in GATEWAY_EFFORTS]
            if reasoning.get('mandatory'):efforts=[e for e in efforts if e!='none']
        result.append({'id':m['id'],'name':m.get('name',m['id']),'efforts':efforts,'pricing':m.get('pricing',{}),'max_output':(m.get('top_provider') or {}).get('max_completion_tokens')})
    return sorted(result,key=lambda x:x['name'].lower())

def read_models(root):
    try:return json.loads((Path(root)/'openrouter-models.json').read_text())
    except (OSError,ValueError):return {'models':[],'updated':None}

def refresh_models(root):
    models=parse_models(request_json('/api/v1/models'))
    if not models:raise ValueError('Görsel ve yapılandırılmış JSON destekli model bulunamadı. Eski liste korundu.')
    value={'models':models,'updated':time.strftime('%Y-%m-%dT%H:%M:%S')}
    path=Path(root)/'openrouter-models.json';tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(value,ensure_ascii=False));tmp.replace(path)
    return value

class OpenRouter(Astra):
    def __init__(self,root,skill,key,model,effort='default'):
        super().__init__(root,skill,model,effort);self.key=key;self.usage=[]
    def call(self,prompt,images,schema,job,cancel):
        content=[{'type':'text','text':prompt}]
        for image in images:
            data=base64.b64encode(Path(image).read_bytes()).decode()
            content.append({'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+data}})
        payload={'model':self.model,'messages':[{'role':'system','content':self.skill.read_text()},{'role':'user','content':content}],
                 'response_format':{'type':'json_schema','json_schema':{'name':'photo_archive','strict':True,'schema':schema}},
                 'provider':{'require_parameters':True},'stream':False}
        if self.effort!='default':payload['reasoning']={'effort':self.effort,'exclude':True}
        response=request_json('/api/v1/chat/completions',self.key,payload,cancel)
        choices=response.get('choices') or []
        if not choices or choices[0].get('finish_reason')!='stop':raise ValueError('OpenRouter eksik/kesilmiş sonuç döndürdü. Önceki çalışma korundu.')
        text=choices[0].get('message',{}).get('content')
        if not isinstance(text,str):raise ValueError('OpenRouter JSON metni döndürmedi.')
        try:result=json.loads(text);jsonschema.validate(result,schema)
        except (ValueError,jsonschema.ValidationError):raise ValueError('Model yanıtı beklenen JSON şemasına uymadı; çalışma değiştirilmedi.') from None
        usage=response.get('usage') or {}
        self.usage.append({k:usage[k] for k in ['prompt_tokens','completion_tokens','total_tokens','cost'] if k in usage})
        return result
