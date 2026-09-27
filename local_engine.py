"""Offline geometry suggestions. Never calls a model or infers names/people."""
from pathlib import Path
from concurrent.futures import CancelledError
import math
import cv2
import numpy as np
from PIL import Image
from engine import validate_plan,validate_groups
from localization import translate

LAYOUTS={'auto':'Otomatik','2x2':'4 fotoğraf · 2 × 2','2x1':'2 fotoğraf · yan yana','1x2':'2 fotoğraf · alt alta','1x1':'Tek fotoğraf','3x2':'6 fotoğraf · 3 × 2'}

def ordered(points):
    p=np.asarray(points,dtype=np.float32)
    # Clockwise from the upper-left in image coordinates; handles modest scan skew.
    center=p.mean(axis=0);p=p[np.argsort(np.arctan2(p[:,1]-center[1],p[:,0]-center[0]))]
    return np.roll(p,-np.argmin(p.sum(axis=1)),axis=0)

def paper_mask(image):
    gray=cv2.cvtColor(image,cv2.COLOR_RGB2GRAY)
    hsv=cv2.cvtColor(image,cv2.COLOR_RGB2HSV)
    # A scanner lid is usually near white. Keep faint paper and ink; discard specks.
    mask=np.uint8((gray<246)|(hsv[:,:,1]>14))*255
    return cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))

def ink_score(image):
    """Dark/chromatic strokes relative to local paper; conservative blank classifier."""
    if min(image.shape[:2])<12:return 1.0
    gray=cv2.cvtColor(image,cv2.COLOR_RGB2GRAY)
    h,w=gray.shape;gray=gray[max(2,h//20):-max(2,h//20),max(2,w//20):-max(2,w//20)]
    color=image[max(2,h//20):-max(2,h//20),max(2,w//20):-max(2,w//20)]
    background=cv2.GaussianBlur(gray,(0,0),max(3,min(gray.shape)/30))
    contrast=background.astype(float)-gray.astype(float)
    hsv=cv2.cvtColor(color,cv2.COLOR_RGB2HSV)
    strokes=(contrast>13)|((hsv[:,:,1]>65)&(hsv[:,:,2]<220))|(gray<110)
    return float(np.mean(strokes))

def quad_for_crop(image,offset=(0,0)):
    h,w=image.shape[:2];mask=paper_mask(image)
    contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    contours=[c for c in contours if cv2.contourArea(c)>h*w*.008]
    if not contours:return None
    # Enclose all significant markings inside a grid cell; don't crop to one ink line.
    points=np.concatenate(contours);hull=cv2.convexHull(points)
    perimeter=cv2.arcLength(hull,True);approx=cv2.approxPolyDP(hull,perimeter*.018,True)
    if len(approx)==4 and cv2.isContourConvex(approx):quad=ordered(approx[:,0,:])
    else:quad=ordered(cv2.boxPoints(cv2.minAreaRect(hull)))
    # Small outward allowance avoids shaving border pixels/faint writing.
    center=quad.mean(axis=0);quad=center+(quad-center)*1.006
    quad[:,0]=np.clip(quad[:,0],0,w-1);quad[:,1]=np.clip(quad[:,1],0,h-1)
    if cv2.contourArea(quad)<h*w*.045:return None
    return quad+np.array(offset)

def grid_boxes(w,h,layout):
    cols,rows=map(int,layout.split('x'))
    return [(round(x*w/cols),round(y*h/rows),round((x+1)*w/cols),round((y+1)*h/rows)) for y in range(rows) for x in range(cols)]

def detect(image,layout):
    h,w=image.shape[:2]
    if layout!='auto':
        boxes=grid_boxes(w,h,layout)
    else:
        mask=paper_mask(image)
        contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        boxes=[]
        for c in contours:
            if cv2.contourArea(c)<w*h*.025:continue
            x,y,cw,ch=cv2.boundingRect(c)
            # Joined long columns/rows usually contain touching prints. Offer a split,
            # always reviewable; a true panorama can be reprocessed as one photograph.
            if ch>cw*2.35 and ch>h*.65:
                boxes += [(x,y,x+cw,y+ch//2),(x,y+ch//2,x+cw,y+ch)]
            elif cw>ch*2.35 and cw>w*.65:
                boxes += [(x,y,x+cw//2,y+ch),(x+cw//2,y,x+cw,y+ch)]
            else:boxes.append((x,y,x+cw,y+ch))
        boxes.sort(key=lambda b:(round((b[1]+b[3])/h*2),b[0]))
    result=[]
    for index,(x1,y1,x2,y2) in enumerate(boxes):
        # Padding can recover a light border outside the threshold mask.
        if layout=='auto':x1=max(0,x1-3);y1=max(0,y1-3);x2=min(w,x2+3);y2=min(h,y2+3)
        crop=image[y1:y2,x1:x2];quad=quad_for_crop(crop,(x1,y1))
        if quad is None:continue
        points=(quad/np.array([w-1,h-1])).clip(0,1).tolist()
        result.append((points,ink_score(crop),index))
    return result

def center_size(region):
    q=np.asarray(region['corners']);return q.mean(axis=0),np.max(q,axis=0)-np.min(q,axis=0)

def cost(front,back):
    fc,fs=center_size(front);bc,bs=center_size(back)
    distance=float(np.linalg.norm(fc-bc))
    size=float(np.mean(np.abs(np.log((fs+.001)/(bs+.001)))))
    return distance+size*.18,distance,size

class LocalProcessor:
    def __init__(self,root,language='en'):self.root=Path(root);self.language=language
    def analyze(self,batch,layout,update,cancel):
        if layout not in LAYOUTS:raise ValueError('Bilinmeyen yerleşim.')
        regions=[];notes=[];images={};scanmap={s['id']:s for s in batch['scans']}
        for n,s in enumerate(batch['scans'],1):
            if cancel.is_set():raise CancelledError()
            update(f'Yerel sınır tespiti · {n} / {len(batch["scans"])}')
            with Image.open(self.root/s['preview']) as source:im=np.asarray(source.convert('RGB'))
            images[s['id']]=im
            hint=s.get('role_hint','auto')
            if hint=='auto':notes.append(s['name']+': yüz türü belirtilmedi; ön kabul edildi, kontrol et.')
            found=detect(im,layout)
            if not found:notes.append(s['name']+': belirgin kâğıt sınırı bulunamadı; gerekirse elle sınır ekle.')
            for i,(corners,ink,cell) in enumerate(found,1):
                role=('blank' if ink<.0007 else 'back') if hint=='back' else 'front'
                regions.append({'id':s['id']+'-local-'+str(i),'scan_id':s['id'],'role':role,
                                'label':f'{s["name"]} · {i}. '+('boş arka adayı' if role=='blank' else 'arka' if role=='back' else 'fotoğraf'),
                                'corners':corners,'rotation_clockwise':0,'confidence':.7})
        if not regions:raise ValueError('Sınır bulunamadı. Yerleşimi seç veya elle dört köşe ekle.')
        if len(regions)>200:raise ValueError('200 yüz sınırı aşıldı; işi böl.')
        fronts=[r for r in regions if r['role']=='front'];backs=[r for r in regions if r['role'] in ['back','blank']]
        used=set();pairs=[]
        update('Yerel konum ve boyut eşleştirmesi')
        for front in fronts:
            if cancel.is_set():raise CancelledError()
            scan=scanmap[front['scan_id']];group=scan.get('group_key','')
            candidates=[]
            for back in backs:
                bs=scanmap[back['scan_id']]
                # Without an explicit scan group, no silent pairing between unrelated scans.
                if back['id'] in used or not group or bs.get('group_key')!=group or bs.get('page')!=scan.get('page'):continue
                candidates.append((cost(front,back),back))
            candidates.sort(key=lambda x:x[0][0]);match=None;status='not_provided';reason='Eşleşen arka bulunamadı. Eksik arka boş sayılmadı.'
            back_scans=[s for s in batch['scans'] if group and s.get('group_key')==group and s.get('role_hint')=='back' and s.get('page')==scan.get('page')]
            if candidates:
                (value,distance,size),candidate=candidates[0]
                margin=(candidates[1][0][0]-value) if len(candidates)>1 else 1
                if distance<.24 and size<.65 and margin>.07:
                    used.add(candidate['id']);match=candidate if candidate['role']=='back' else None
                    status='matched' if match else 'blank'
                    reason='Konum ve boyut benzerliğine göre yerel öneri. Yönü ve dört köşeyi kontrol et.' if match else 'Arka bölgede belirgin yazı bulunmadı; boş adayını kontrol et. Boş arka çıktıya eklenmez.'
                else:status='uncertain';reason='Arka konumu/boyutu belirsiz. Otomatik birleştirilmedi.'
            elif back_scans:
                # Absence of ink is a tentative suggestion, never an automatic approval.
                q=np.asarray(front['corners']);im=images[back_scans[0]['id']];h,w=im.shape[:2]
                low=np.floor(q.min(axis=0)*[w-1,h-1]).astype(int);high=np.ceil(q.max(axis=0)*[w-1,h-1]).astype(int)
                crop=im[low[1]:high[1]+1,low[0]:high[0]+1]
                if ink_score(crop)<.0007:status='blank';reason='Aynı konumdaki arka alan yazısız görünüyor. Boş olduğunu onayla; çıktıya eklenmeyecek.'
                else:status='uncertain';reason='Arka taraması var ancak kâğıt/eşleşme belirsiz; elle kontrol et.'
            pairs.append({'id':'p-'+front['id'],'front_id':front['id'],'back_id':match['id'] if match else None,
                          'name':f'tarama-{group or scan["order"]}-fotograf-{len(pairs)+1:03d}',
                          'back_rotation_clockwise':0,'back_status':status,'confidence':.7,'needs_review':True,'matching_notes':reason})
        notes.insert(0,'Yerel işlem: hiçbir model veya ağ çağrısı yapılmadı. Görselin konu/yönü anlaşılmaz; adlar sıralıdır. Bütün öneriler kontrol bekler. Soluk yazı ve birbirine değen fotoğraf sınırlarını özellikle kontrol et.')
        if self.language=='en':
            notes=[translate(note) for note in notes]
            for region in regions:
                role=region['role'];index=region['id'].rsplit('-',1)[-1]
                region['label']=scanmap[region['scan_id']]['name']+' · '+index+'. '+{'front':'photo','back':'back','blank':'blank back candidate'}[role]
            for pair in pairs:
                pair['matching_notes']=translate(pair['matching_notes'])
                pair['name']=pair['name'].replace('tarama-','scan-').replace('-fotograf-','-photo-')
        plan={'regions':regions,'pairs':pairs,'notes':'\n'.join(notes)}
        validate_plan(plan,set(scanmap));validate_groups(plan,batch['scans']);return plan
