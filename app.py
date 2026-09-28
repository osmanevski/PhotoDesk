from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, CancelledError
from threading import RLock, Event
import argparse, copy, hashlib, io, json, os, re, secrets, shutil, subprocess, time, uuid, zipfile
from flask import Flask, request, jsonify, send_file, Response
from PIL import Image, ImageDraw
from engine import Astra, MODEL, EFFORT, validate_plan, validate_groups
from local_engine import LocalProcessor, LAYOUTS
from model_config import DEFAULTS, catalog, validate_settings
from credentials import Credentials
from contextlib import closing
from platform_support import data_dir, data_id, instance_lock, open_folder
from openrouter_engine import OpenRouter,read_models,refresh_models,request_json
from localization import translate,localize_response
from imaging import heic_supported, SUPPORTED, raster_pages, render_pair, slug, validate_corners

HERE=Path(__file__).resolve().parent
def now():return time.strftime('%Y-%m-%dT%H:%M:%S')
def uid():return uuid.uuid4().hex[:12]
def atomic(path,value):
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2), encoding='utf-8');tmp.replace(path)

class Store:
    def __init__(self,root,credentials=None):
        self.root=Path(root).expanduser().resolve();self.root.mkdir(parents=True,exist_ok=True)
        self.file=self.root/'state.json';self.lock=RLock()
        self.state=json.loads(self.file.read_text(encoding='utf-8')) if self.file.exists() else {'batches':[],'exports':[]}
        self.state['settings']={**DEFAULTS,**self.state.get('settings',{})}
        self.credentials=credentials if credentials is not None else Credentials();self.credential_lock=RLock()
        self.job={'status':'idle','message':'Hazır'};self.cancel=Event();self.pool=ThreadPoolExecutor(max_workers=1)
        self.ai=Astra(self.root,HERE/'skills/fotograf-arsivi/SKILL.md')
    def save(self):atomic(self.file,self.state)
    def batch(self,bid):
        for b in self.state['batches']:
            if b['id']==bid:return b
        raise ValueError('İş bulunamadı.')
    def checkpoint(self,b):
        snap={k:copy.deepcopy(b.get(k)) for k in ['regions','pairs','notes','processing']}
        b.setdefault('history',[]).append(snap);b['history']=b['history'][-30:]
    def update(self,msg):
        with self.lock:self.job['message']=msg
    def busy(self,bid=None):return self.job['status']=='running' and (bid is None or self.job.get('batch_id')==bid)

def create_app(root, credentials=None):
    app=Flask(__name__,static_folder=str(HERE/'static'));app.config['MAX_CONTENT_LENGTH']=512*1024*1024
    store=Store(root, credentials);token=secrets.token_urlsafe(32);app.store=store
    @app.before_request
    def local_only():
        if request.host.split(':')[0] not in ['127.0.0.1','localhost','[::1]']:
            return jsonify(error='Yalnız yerel bağlantı kabul edilir.'),403
        if request.method not in ['GET','HEAD','OPTIONS'] and request.headers.get('X-App-Token')!=token:
            return jsonify(error='Oturum yenilendi; sayfayı yenile.'),403
    def language():return 'tr' if request.cookies.get('photo-desk-language')=='tr' else 'en'
    @app.after_request
    def headers(resp):
        resp.headers['Content-Language']=language()
        if resp.is_json:
            resp.set_data(app.json.dumps(localize_response(resp.get_json(),language())))
        resp.headers['X-Content-Type-Options']='nosniff';resp.headers['Cache-Control']='no-store'
        resp.headers['Content-Security-Policy']="default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self' 'nonce-"+token+"'; connect-src 'self'; frame-ancestors 'none'"
        return resp
    @app.errorhandler(Exception)
    def err(e):
        code=getattr(e,'code',400)
        return jsonify(error=str(e)),code if isinstance(code,int) else 400
    @app.get('/')
    def index():
        lang=language();name='index.tr.html' if lang=='tr' else 'index.html'
        html=(HERE/'static'/name).read_text(encoding='utf-8').replace('__TOKEN__',token).replace('__LANG__',lang).replace('__SCRIPT__','/static/app.tr.js' if lang=='tr' else '/static/app.js')
        return Response(html,mimetype='text/html')
    @app.get('/api/state')
    def state():
        with store.lock:
            result=copy.deepcopy(store.state)
            for b in result['batches']:b['undo_available']=bool(b.pop('history',[]))
            return jsonify(**result,job=store.job,model=(store.state['settings']['api_model'] if store.state['settings']['backend']=='openrouter' else store.state['settings']['model']) if store.state['settings']['backend']!='local' else None,effort=(store.state['settings']['api_effort'] if store.state['settings']['backend']=='openrouter' else store.state['settings']['effort']) if store.state['settings']['backend']!='local' else None,export_default=str(Path.home()/'Downloads'/'Fotograf-Masasi'),version='1.4.0',models=catalog(),layouts=LAYOUTS,openrouter=read_models(store.root),api_key_saved=store.state.get('openrouter_key_saved',False))
    @app.post('/api/settings')
    def settings():
        data=request.get_json() or {}
        with store.lock:
            if store.busy():raise ValueError('İşlem sürerken ayarlar değiştirilemez.')
            store.state['settings']=validate_settings(data,read_models(store.root)['models']);store.save()
        return jsonify(store.state['settings'])
    @app.post('/api/openrouter/key')
    def router_key():
        data=request.get_json() or {}
        with store.lock:
            if store.busy():raise ValueError('Önce devam eden işlemin bitmesini bekle.')
        with store.credential_lock:
            if data.get('delete'):store.credentials.delete()
            else:store.credentials.set(data.get('key',''))
            with store.lock:
                store.state['openrouter_key_saved']=not bool(data.get('delete'))
                store.save()
        return jsonify(saved=store.state['openrouter_key_saved'])
    @app.post('/api/openrouter/test')
    def router_test():
        request_json('/api/v1/key',store.credentials.get())
        return jsonify(ok=True,message='OpenRouter anahtarı doğrulandı. Fotoğraf gönderilmedi; model çağrısı yapılmadı.')
    @app.post('/api/openrouter/models')
    def router_models():
        with store.lock:
            if store.busy():raise ValueError('Önce devam eden işlemin bitmesini bekle.')
            result=refresh_models(store.root)
        return jsonify(result)
    @app.post('/api/batches')
    def add_batch():
        data=request.get_json() or {}
        b={'id':uid(),'name':str(data.get('name') or translate('Yeni tarama işi',language()))[:150],'created':now(),'revision':0,'scans':[],
           'regions':[],'pairs':[],'notes':'','instruction':'','history':[]}
        with store.lock:store.state['batches'].insert(0,b);store.save()
        return jsonify(b)
    def mutable(bid,data=None):
        b=store.batch(bid)
        if store.busy(bid):raise ValueError('Bu iş üzerinde işlem sürüyor. Önce tamamlanmasını bekle veya iptal et.')
        if data and 'revision' in data and data['revision']!=b['revision']:raise ValueError('İş başka bir pencerede değişti. Sayfayı yenile.')
        return b
    @app.post('/api/batches/<bid>/upload')
    def upload(bid):
        files=request.files.getlist('files');added=[];errors=[]
        with store.lock:
            b=mutable(bid)
            if len(b['scans'])>=100:raise ValueError('Bir işte en fazla 100 tarama sayfası bulunabilir.')
            for f in files:
                filename=Path(f.filename or 'tarama.jpg').name
                ext=Path(filename).suffix.lower()
                if ext not in SUPPORTED:errors.append(filename+': desteklenmeyen biçim');continue
                if ext in {'.heic','.heif'} and not heic_supported():errors.append(filename+': HEIC yalnız macOS üzerinde destekleniyor. Dosyayı JPEG olarak yükle.');continue
                raw=f.read()
                if not raw:errors.append(filename+': boş dosya');continue
                digest=hashlib.sha256(raw).hexdigest()
                if any(s['hash']==digest for s in b['scans']):errors.append(filename+': bu işte zaten var');continue
                directory=store.root/'sources'/bid/uid();directory.mkdir(parents=True)
                original=directory/('original'+ext);original.write_bytes(raw)
                try:
                    records=[]
                    with closing(raster_pages(original)) as pages:
                        for page,(im,dpi,method) in enumerate(pages,1):
                            if len(b['scans'])+len(records)>=100:raise ValueError('100 sayfa sınırı aşıldı.')
                            if im.width*im.height>100_000_000:raise ValueError('Tarama 100 megapiksel sınırını aşıyor.')
                            sid='s'+uid()[:7];raster=directory/f'{sid}.png';preview=directory/f'{sid}-preview.jpg'
                            im.save(raster,dpi=(dpi,dpi));p=im.copy();p.thumbnail((2100,2100));p.save(preview,quality=95)
                            grouping=re.fullmatch(r'(\d+)\s*([ab])',Path(filename).stem.strip(),re.I)
                            records.append({'id':sid,'name':filename,'page':page,'width':im.width,'height':im.height,'dpi':dpi,
                                'hash':digest,'method':method,'raster':raster.relative_to(store.root).as_posix(),
                                'preview':preview.relative_to(store.root).as_posix(),'original':original.relative_to(store.root).as_posix(),
                                'role_hint':('front' if grouping[2].lower()=='a' else 'back') if grouping else 'auto',
                                'group_key':str(int(grouping[1])) if grouping else '', 'order':len(b['scans'])+len(records)+1})
                    b['scans']+=records;added+=records
                except Exception as e:
                    errors.append(filename+': '+str(e));shutil.rmtree(directory)
            b['revision']+=1;store.save()
        return jsonify(added=len(added),errors=errors)
    @app.post('/api/batches/<bid>/scan/<sid>')
    def scan_edit(bid,sid):
        data=request.get_json()
        with store.lock:
            b=mutable(bid,data);s=next(s for s in b['scans'] if s['id']==sid)
            role=data.get('role_hint','auto')
            if role not in ['auto','front','back']:raise ValueError('Geçersiz yüz ipucu.')
            s['role_hint']=role;b['revision']+=1;store.save()
        return jsonify(ok=True)
    @app.post('/api/batches/<bid>/remove-scan/<sid>')
    def scan_remove(bid,sid):
        with store.lock:
            b=mutable(bid)
            # Retain files on disk and don't silently destroy an analyzed matching plan.
            if any(r['scan_id']==sid for r in b['regions']):raise ValueError('Analiz edilmiş taramayı kaldırmak için yeni iş aç; mevcut eşleşmeler korunur.')
            b['scans']=[s for s in b['scans'] if s['id']!=sid];b['revision']+=1;store.save()
        return jsonify(ok=True)
    @app.get('/api/batches/<bid>/scan/<sid>')
    def scan_image(bid,sid):
        with store.lock:s=next(s for s in store.batch(bid)['scans'] if s['id']==sid);p=store.root/s['preview']
        return send_file(p,mimetype='image/jpeg')
    @app.post('/api/batches/<bid>/analyze')
    def analyze(bid):
        data=request.get_json() or {};instruction=str(data.get('instruction',''))[:20000];mode=data.get('mode','analyze')
        with store.lock:
            key_needed=store.state['settings']['backend']=='openrouter'
            settings_before=copy.deepcopy(store.state['settings'])
        with store.credential_lock:
            api_key=store.credentials.get() if key_needed else None
        with store.lock:
            if store.state['settings']!=settings_before:raise ValueError('İş başka bir pencerede değişti. Sayfayı yenile.')
            if store.busy():raise ValueError('Başka bir iş çalışıyor. Bitince bu işi başlatabilirsin.')
            b=store.batch(bid)
            if not b['scans']:raise ValueError('Önce tarama dosyalarını ekle.')
            if mode=='revise' and not b['pairs']:raise ValueError('Önce fotoğrafları ayır ve eşleştir.')
            snapshot=copy.deepcopy(b);store.cancel.clear();job_language=language()
            config=validate_settings(store.state['settings'],read_models(store.root)['models'])
            if config['backend']=='local' and mode=='revise':raise ValueError('Serbest metinle düzeltme için yapay zekâ modunu seç; yerel modda köşe/eşleşme alanlarını kullan.')
            store.ai.model=config['model'];store.ai.effort=config['effort']
            model_instruction = instruction + '\nOutput labels, notes and new descriptive filenames in '+('Turkish' if job_language=='tr' else 'English')+'. Preserve existing user names and instructions.'
            processor=store.ai
            if config['backend']=='openrouter':
                if not config['api_model']:raise ValueError('Önce OpenRouter model listesini yenile ve model seç.')
                processor=OpenRouter(store.root,HERE/'skills/fotograf-arsivi/SKILL.md',api_key,config['api_model'],config['api_effort'])
            store.job={'status':'running','batch_id':bid,'message':('Yerel işlem başlatılıyor' if config['backend']=='local' else processor.model+' · '+processor.effort+' başlatılıyor'),'started':now()}
        def run():
            try:
                if config['backend']=='local':result=LocalProcessor(store.root,language=job_language).analyze(snapshot,config['layout'],store.update,store.cancel)
                else:result=processor.revise(snapshot,model_instruction,store.update,store.cancel) if mode=='revise' else processor.analyze(snapshot,model_instruction,store.update,store.cancel)
                with store.lock:
                    if store.cancel.is_set():raise CancelledError('İptal edildi.')
                    b=store.batch(bid);store.checkpoint(b);b.update(result);b['processing']={**config,'model':processor.model if config['backend']!='local' else None,'effort':processor.effort if config['backend']!='local' else None,'usage':getattr(processor,'usage',[]) if config['backend']=='openrouter' else []};b['instruction']=instruction;b['revision']+=1;store.save()
                    store.job={'status':'done','batch_id':bid,'message':f"{len(b['pairs'])} fotoğraf hazır · Eşleşmeleri gözden geçir"}
            except CancelledError:
                with store.lock:store.job={'status':'cancelled','batch_id':bid,'message':'İptal edildi. Önceki sonuçlar korundu.'}
            except Exception as e:
                with store.lock:store.job={'status':'error','batch_id':bid,'message':str(e)}
        store.pool.submit(run)
        return jsonify(ok=True)
    @app.post('/api/cancel')
    def cancel():store.cancel.set();return jsonify(ok=True)
    @app.post('/api/batches/<bid>/plan')
    def plan_edit(bid):
        data=request.get_json()
        with store.lock:
            b=mutable(bid,data);plan={k:data[k] for k in ['regions','pairs','notes']}
            validate_plan(plan,{s['id'] for s in b['scans']});validate_groups(plan,b['scans']);store.checkpoint(b);b.update(plan);b['revision']+=1;store.save()
        return jsonify(ok=True)
    @app.post('/api/batches/<bid>/undo')
    def undo(bid):
        with store.lock:
            b=mutable(bid)
            if not b['history']:raise ValueError('Geri alınacak değişiklik yok.')
            old=b['history'].pop();b.update(old);b['revision']+=1;store.save()
        return jsonify(ok=True)
    @app.get('/api/batches/<bid>/pair/<pid>/preview')
    def preview(bid,pid):
        with store.lock:b=copy.deepcopy(store.batch(bid));p=next(p for p in b['pairs'] if p['id']==pid)
        im=render_pair(b,p,store.root,True);im.thumbnail((1500,1500));out=io.BytesIO();im.save(out,format='JPEG',quality=92);out.seek(0)
        return send_file(out,mimetype='image/jpeg')
    @app.post('/api/batches/<bid>/export')
    def export(bid):
        data=request.get_json() or {}
        with store.lock:b=copy.deepcopy(mutable(bid,data))
        requested=data.get('pair_ids');pairs=[p for p in b['pairs'] if (requested is None or p['id'] in requested) and not p['needs_review']]
        if not pairs:raise ValueError('Kaydetmek için en az bir eşleşmeyi onayla.')
        base=Path(str(data.get('directory') or Path.home()/'Downloads'/'Fotograf-Masasi')).expanduser().resolve()
        base.mkdir(parents=True,exist_ok=True)
        directory=base/(slug(b['name'])+'-'+time.strftime('%Y%m%d-%H%M%S')+'-'+uid()[:4]);directory.mkdir()
        exports=[]
        try:
            for i,p in enumerate(pairs,1):
                store.update(f"Kaydediliyor · {i} / {len(pairs)}") if store.busy(bid) else None
                im=render_pair(b,p,store.root)
                name=f"{i:03d}-{slug(p['name'])}"+(('-on-arka' if language()=='tr' else '-front-back') if p['back_id'] else '')+'.jpg'
                target=directory/name
                s=next(s for s in b['scans'] if s['id']==next(r for r in b['regions'] if r['id']==p['front_id'])['scan_id'])
                im.save(target,quality=100,subsampling=0,dpi=(s['dpi'],s['dpi']))
                with Image.open(target) as verify:verify.verify()
                exports.append({'name':name,'pair_id':p['id'],'width':im.width,'height':im.height,'bytes':target.stat().st_size})
            processing=b.get('processing') or {'backend':'ai','model':MODEL,'effort':EFFORT}
            manifest={'created':now(),'processing':processing,'model':processing.get('model'),'effort':processing.get('effort'),'batch_id':bid,'revision':b['revision'],'files':exports,
                      'regions':b['regions'],'pairs':pairs,'sources':[{k:s[k] for k in ['id','name','page','hash','dpi']} for s in b['scans']]}
            atomic(directory/'arsiv-kaydi.json',manifest)
            eid=uid();record={'id':eid,'batch_id':bid,'directory':str(directory),'files':exports,'created':now()}
            with store.lock:store.state['exports'].insert(0,record);store.save()
        except Exception:
            # Only the newly-created incomplete export directory is removed. Originals are immutable.
            shutil.rmtree(directory);raise
        return jsonify(record)
    @app.get('/api/exports/<eid>/zip')
    def export_zip(eid):
        with store.lock:record=next(e for e in store.state['exports'] if e['id']==eid)
        directory=Path(record['directory']);buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w',zipfile.ZIP_STORED) as z:
            for f in record['files']:z.write(directory/f['name'],f['name'])
            z.write(directory/'arsiv-kaydi.json','arsiv-kaydi.json')
        buffer.seek(0);return send_file(buffer,mimetype='application/zip',as_attachment=True,download_name=directory.name+'.zip')
    @app.post('/api/exports/<eid>/reveal')
    def reveal(eid):
        with store.lock:record=next(e for e in store.state['exports'] if e['id']==eid)
        open_folder(record['directory']);return jsonify(ok=True)
    @app.get('/api/health')
    def health():
        config=store.state['settings']
        return jsonify(ok=True,app='fotograf-masasi',data_id=data_id(store.root),version='1.4.0',backend=config['backend'],model=(config['api_model'] if config['backend']=='openrouter' else config['model']) if config['backend']!='local' else None,effort=(config['api_effort'] if config['backend']=='openrouter' else config['effort']) if config['backend']!='local' else None)
    return app

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8874)
    parser.add_argument('--data',default=str(data_dir()))
    args=parser.parse_args()
    from waitress import serve
    with instance_lock(Path(args.data).expanduser().resolve()/'server.lock', timeout=0):
        app=create_app(args.data)
        print(f'PhotoDesk · http://127.0.0.1:{args.port}',flush=True)
        serve(app,host='127.0.0.1',port=args.port,threads=4,max_request_body_size=512*1024*1024)
