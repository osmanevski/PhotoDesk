from pathlib import Path
import copy, json, os, shutil, subprocess, time, uuid
from concurrent.futures import CancelledError
from PIL import Image, ImageDraw, ImageFont
import jsonschema
from imaging import rectify, validate_corners

MODEL='gpt-6-astra'
EFFORT='medium'
def obj(properties):
    return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}
def arr(items):return {'type':'array','items':items}
TEXT={'type':'string'}
CONF={'type':'number','minimum':0,'maximum':1}
ROT={'type':'integer','enum':[0,90,180,270]}
REGION=obj({'id':TEXT,'scan_id':TEXT,'role':{'type':'string','enum':['front','back','blank']},'label':TEXT,
            'corners':{'type':'array','minItems':4,'maxItems':4,'items':{'type':'array','minItems':2,'maxItems':2,'items':CONF}},
            'rotation_clockwise':ROT,'confidence':CONF})
PAIR=obj({'id':TEXT,'front_id':TEXT,'back_id':{'type':['string','null']},'name':TEXT,'back_rotation_clockwise':ROT,
          'back_status':{'type':'string','enum':['matched','blank','not_provided','uncertain']},'confidence':CONF,
          'needs_review':{'type':'boolean'},'matching_notes':TEXT})
DETECT=obj({'regions':arr(REGION),'notes':TEXT})
MATCH=obj({'pairs':arr(PAIR),'notes':TEXT})
PLAN=obj({'regions':arr(REGION),'pairs':arr(PAIR),'notes':TEXT})

def validate_plan(plan,scan_ids):
    jsonschema.validate(plan,PLAN)
    regions={}
    for r in plan['regions']:
        if r['id'] in regions:raise ValueError('Tekrarlanan bölge kimliği.')
        if r['scan_id'] not in scan_ids:raise ValueError('Bilinmeyen tarama kimliği.')
        validate_corners(r['corners']);regions[r['id']]=r
    fronts=set();backs=set();pair_ids=set()
    for p in plan['pairs']:
        if p['id'] in pair_ids:raise ValueError('Tekrarlanan fotoğraf kimliği.')
        pair_ids.add(p['id'])
        if p['front_id'] not in regions or regions[p['front_id']]['role']!='front':raise ValueError('Ön yüz kaydı bulunamadı.')
        if p['front_id'] in fronts:raise ValueError('Bir fotoğraf iki kez eşleştirilemez.')
        fronts.add(p['front_id'])
        if p['back_id']:
            if p['back_id'] not in regions or regions[p['back_id']]['role']!='back':raise ValueError('Arka yüz kaydı bulunamadı.')
            if p['back_id'] in backs:raise ValueError('Bir arka yüz iki fotoğrafa bağlanamaz.')
            if p['back_status'] not in ['matched','uncertain']:raise ValueError('Arka yüz durumu tutarsız.')
            backs.add(p['back_id'])
        elif p['back_status']=='matched':raise ValueError('Eşleşmiş fotoğrafın arkası eksik.')
    if fronts!={r['id'] for r in regions.values() if r['role']=='front'}:raise ValueError('Her ön fotoğraf sonuçlara bir kez eklenmeli.')
    return plan

def normalize_ai(plan):
    # Low-confidence/missing backs are never silently presented as verified blank backs.
    regs={r['id']:r for r in plan['regions']}
    for p in plan['pairs']:
        ids=[p['front_id']]+([p['back_id']] if p['back_id'] else [])
        if p['confidence']<.85 or any(regs.get(i,{}).get('confidence',0)<.8 for i in ids) or p['back_status'] in ['uncertain','not_provided']:
            p['needs_review']=True
    return plan

class Astra:
    def __init__(self,root,skill,model=MODEL,effort=EFFORT):
        self.root=Path(root);self.skill=Path(skill);self.proc=None;self.model=model;self.effort=effort
    def call(self,prompt,images,schema,job,cancel):
        binary=shutil.which('codex') or '/opt/homebrew/bin/codex'
        if not Path(binary).exists():raise RuntimeError('Codex bulunamadı. Codex CLI kurulu ve hesabına giriş yapılmış olmalı.')
        run=self.root/'runs'/uuid.uuid4().hex;run.mkdir(parents=True)
        schema_path=run/'schema.json';result_path=run/'result.json'
        schema_path.write_text(json.dumps(schema))
        cmd=[binary,'exec','--ignore-user-config','--ephemeral','--skip-git-repo-check','--sandbox','read-only',
             '--model',self.model,'-c',f'model_reasoning_effort="{self.effort}"','-c','project_doc_max_bytes=0',
             '-c','web_search="disabled"','--disable','shell_tool','--disable','apps','--disable','multi_agent',
             '--disable','skill_search','--enable','skip_host_skill_discovery','--color','never',
             '--output-schema',str(schema_path),'-o',str(result_path)]
        for image in images:cmd+=['--image',str(image)]
        cmd+=['-']
        text=self.skill.read_text()+'\n\n'+prompt
        env=os.environ.copy();env.pop('OPENAI_API_KEY',None)
        with open(run/'stdout.log','w') as stdout,open(run/'stderr.log','w') as stderr:
            self.proc=subprocess.Popen(cmd,cwd=run,stdin=subprocess.PIPE,stdout=stdout,stderr=stderr,text=True,env=env,start_new_session=True)
            self.proc.stdin.write(text);self.proc.stdin.close()
            start=time.monotonic()
            while self.proc.poll() is None:
                if cancel.is_set() or time.monotonic()-start>1200:
                    import signal
                    os.killpg(self.proc.pid,signal.SIGTERM)
                    try:self.proc.wait(5)
                    except subprocess.TimeoutExpired:os.killpg(self.proc.pid,signal.SIGKILL);self.proc.wait()
                    self.proc=None
                    if cancel.is_set():raise CancelledError('İşlem iptal edildi; önceki sonuçlar korundu.')
                    raise RuntimeError('Model yanıtı 20 dakika içinde tamamlanmadı. İşlem durduruldu; yeniden deneyebilirsin.')
                time.sleep(.5)
            code=self.proc.returncode;self.proc=None
        if code or not result_path.exists():
            detail=(run/'stderr.log').read_text(errors='replace')[-1400:]
            raise RuntimeError('Seçilen model çağrısı tamamlanamadı. Model değiştirilmedi. Codex oturumunu/kotanı kontrol et.\n'+detail)
        result=json.loads(result_path.read_text());jsonschema.validate(result,schema)
        return result

    def sheets(self,regions,scans):
        paths=[];directory=self.root/'runs'/('sheets-'+uuid.uuid4().hex);directory.mkdir(parents=True)
        scanmap={s['id']:s for s in scans}
        font_path='/System/Library/Fonts/Supplemental/Arial.ttf'
        font=ImageFont.truetype(font_path,20) if Path(font_path).exists() else ImageFont.load_default()
        for start in range(0,len(regions),8):
            group=regions[start:start+8];sheet=Image.new('RGB',(1600,math_ceil(len(group)/4)*650),'#d9dde2');draw=ImageDraw.Draw(sheet)
            for i,r in enumerate(group):
                im=rectify(self.root/scanmap[r['scan_id']]['preview'],r['corners'],0,True);im.thumbnail((380,585))
                x=(i%4)*400;y=(i//4)*650
                sheet.paste(im,(x+(400-im.width)//2,y+55+(585-im.height)//2))
                draw.text((x+8,y+5),r['id'],font=font,fill='black');draw.text((x+8,y+28),r['role'],font=font,fill='black')
            path=directory/f'sheet-{start//8}.jpg';sheet.save(path,quality=93);paths.append(path)
        return paths

    def analyze(self,batch,instruction,update,cancel):
        scans=batch['scans'];regions=[]
        for start in range(0,len(scans),4):
            chunk=scans[start:start+4]
            update(f'Taramalar ayrılıyor · {start+1}–{min(start+4,len(scans))} / {len(scans)}')
            meta=[{k:s.get(k,'') for k in ['id','name','page','width','height','role_hint','order','group_key']} for s in chunk]
            prompt='Görev: ekteki taramalardaki fiziksel fotoğraf önlerini ve arka kâğıtlarını tespit et. Henüz eşleştirme yapma. Her görüntü sırayla şu metadata ile eşleşir:\n'+json.dumps(meta,ensure_ascii=False)+'\nKullanıcı notu: '+instruction
            part=self.call(prompt,[self.root/s['preview'] for s in chunk],DETECT,None,cancel)
            for r in part['regions']:
                if r['scan_id'] not in {s['id'] for s in chunk}:raise ValueError('Astra yanlış tarama kimliği döndürdü.')
                validate_corners(r['corners'])
            regions+=part['regions']
        if not regions:raise ValueError('Fotoğraf sınırı bulunamadı. Taramaları kontrol et.')
        if len(regions)>200:raise ValueError('Bir iş en fazla 200 fiziksel fotoğraf/yüz içerebilir; iki işe böl.')
        if len({r['id'] for r in regions})!=len(regions):raise ValueError('Astra tekrar eden bölge kimliği döndürdü.')
        update(f'{len(regions)} yüz bulundu · Önler ve arkalar eşleştiriliyor')
        sheets=self.sheets(regions,scans)
        prompt='Görev: etiketli kontakt sayfalarında verilen bölgeleri eşleştir. Görseller DÖNDÜRÜLMEDEN gösteriliyor. Region rotation_clockwise bilgisi yön önerisidir. Her ön için bir pair üret; arka eksikliği gizleme.\nTaramaların sırası ve kullanıcının ön/arka ipuçları:\n'+json.dumps([{k:s.get(k,'') for k in ['id','name','role_hint','order','group_key']} for s in scans],ensure_ascii=False)+'\nBölgeler:\n'+json.dumps(regions,ensure_ascii=False)+'\nKullanıcı açıklaması:\n'+instruction
        answer=self.call(prompt,sheets,MATCH,None,cancel)
        plan={'regions':regions,'pairs':answer['pairs'],'notes':answer['notes']}
        validate_groups(plan,scans)
        return normalize_ai(validate_plan(plan,{s['id'] for s in scans}))

    def revise(self,batch,instruction,update,cancel):
        update(f'Düzeltme {self.model} · {self.effort} ile uygulanıyor')
        plan={k:copy.deepcopy(batch[k]) for k in ['regions','pairs','notes']}
        # Source images retain the coordinate reference; contact sheets make pair identity legible.
        images=[self.root/s['preview'] for s in batch['scans']]
        if len(images)>12:
            images=self.sheets(batch['regions'],batch['scans'])
            instruction+='\nBu çağrıda yalnız kontakt sayfaları var; köşe koordinatlarını değiştirme, eşleşme/yön/isim alanlarını düzelt.'
        prompt='Mevcut planı yalnız kullanıcının istediği şekilde düzelt. Bütün bölgeleri ve bütün çiftleri geri döndür. Kimlikleri koru.\nTarama sırası:\n'+json.dumps([{k:s.get(k,'') for k in ['id','name','role_hint','order','group_key']} for s in batch['scans']],ensure_ascii=False)+'\nMevcut plan:\n'+json.dumps(plan,ensure_ascii=False)+'\nKullanıcının düzeltmesi:\n'+instruction
        answer=self.call(prompt,images,PLAN,None,cancel)
        validate_groups(answer,batch['scans'])
        return normalize_ai(validate_plan(answer,{s['id'] for s in batch['scans']}))

def math_ceil(n):
    import math
    return math.ceil(n)

def validate_groups(plan,scans):
    regions={r['id']:r for r in plan['regions']};scanmap={s['id']:s for s in scans}
    for p in plan['pairs']:
        if p.get('back_id') and p['front_id'] in regions and p['back_id'] in regions:
            a=scanmap[regions[p['front_id']]['scan_id']].get('group_key')
            b=scanmap[regions[p['back_id']]['scan_id']].get('group_key')
            if a and b and a!=b:raise ValueError('Farklı numaralı a/b tarama grupları birbirine eşleştirilemez.')
