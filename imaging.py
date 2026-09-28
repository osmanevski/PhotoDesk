"""Deterministic, source-preserving scan ingestion and geometry."""
from pathlib import Path
import hashlib, io, math, re, subprocess, unicodedata, sys
import numpy as np
import cv2
import pymupdf as fitz
from PIL import Image, ImageOps

Image.MAX_IMAGE_PIXELS = 140_000_000
SUPPORTED = {'.jpg','.jpeg','.png','.tif','.tiff','.heic','.heif','.pdf'}

def heic_supported():return sys.platform == 'darwin'

def slug(value):
    value = value.translate(str.maketrans('ıİşŞğĞüÜöÖçÇ','iIsSgGuUoOcC'))
    value = unicodedata.normalize('NFKD', value).encode('ascii','ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+','-',value).strip('-')[:100] or 'fotograf'

def raster_pages(path):
    path=Path(path)
    if path.suffix.lower()=='.pdf':
        with fitz.open(path) as doc:
            if len(doc)>100: raise ValueError('Bir PDF en fazla 100 sayfa olabilir.')
            for page in doc:
                images=page.get_images(full=True)
                direct=False
                if len(images)==1 and page.rotation==0:
                    xref=images[0][0];rects=page.get_image_rects(xref,transform=True)
                    if len(rects)==1:
                        rect,mat=rects[0]
                        if abs(rect.width-page.rect.width)<2 and abs(rect.height-page.rect.height)<2 and mat.a>0 and mat.d>0 and abs(mat.b)<.01 and abs(mat.c)<.01:
                            info=doc.extract_image(xref)
                            im=ImageOps.exif_transpose(Image.open(io.BytesIO(info['image']))).convert('RGB')
                            dpi=round(im.width/(page.rect.width/72))
                            yield im,dpi,'PDF içindeki özgün görüntü'
                            direct=True
                if not direct:
                    zoom=min(600/72,math.sqrt(60_000_000/(page.rect.width*page.rect.height)))
                    pix=page.get_pixmap(matrix=fitz.Matrix(zoom,zoom),colorspace=fitz.csRGB,alpha=False)
                    yield Image.frombytes('RGB',(pix.width,pix.height),pix.samples),round(zoom*72),'PDF sayfa görüntüsü'
    elif path.suffix.lower() in {'.heic','.heif'}:
        if not heic_supported():raise ValueError('HEIC yalnız macOS üzerinde destekleniyor. Dosyayı JPEG olarak yükle.')
        target=path.with_name(path.stem+'-decode.png')
        subprocess.run(['sips','-s','format','png',str(path),'--out',str(target)],check=True,stdout=subprocess.DEVNULL,timeout=60)
        try:
            with Image.open(target) as source:decoded=ImageOps.exif_transpose(source).convert('RGB')
            yield decoded,600,'HEIC'
        finally:target.unlink(missing_ok=True)
    else:
        with Image.open(path) as im:
            count=getattr(im,'n_frames',1)
            if count>100: raise ValueError('En fazla 100 sayfa destekleniyor.')
            for i in range(count):
                im.seek(i);dpi=im.info.get('dpi',(600,600))[0]
                yield ImageOps.exif_transpose(im).convert('RGB'),int(dpi or 600),'Özgün görüntü'

def validate_corners(corners):
    a=np.asarray(corners,dtype=float)
    if a.shape!=(4,2) or not np.isfinite(a).all() or (a<0).any() or (a>1).any():
        raise ValueError('Dört köşe 0–1 aralığında olmalı.')
    contour=(a*10000).astype(np.float32)
    if not cv2.isContourConvex(contour) or cv2.contourArea(contour,oriented=True)<10000:
        raise ValueError('Köşeler çapraz olamaz; sıra sol üst, sağ üst, sağ alt, sol alt olmalı.')
    return a

def rectify(path,corners,rotation=0,preview=False):
    with Image.open(path) as src:
        im=src.convert('RGB')
    if preview: im.thumbnail((1800,1800))
    p=validate_corners(corners)*[im.width-1,im.height-1]
    tl,tr,br,bl=p
    w=max(2,math.ceil(max(np.linalg.norm(tl-tr),np.linalg.norm(bl-br))))
    h=max(2,math.ceil(max(np.linalg.norm(tl-bl),np.linalg.norm(tr-br))))
    if w*h>80_000_000: raise ValueError('Tek fotoğraf 80 megapiksel sınırını aşıyor.')
    matrix=cv2.getPerspectiveTransform(p.astype(np.float32),np.float32([[0,0],[w-1,0],[w-1,h-1],[0,h-1]]))
    data=cv2.warpPerspective(np.asarray(im),matrix,(w,h),flags=cv2.INTER_CUBIC,borderMode=cv2.BORDER_REPLICATE)
    out=Image.fromarray(data)
    rot={90:Image.Transpose.ROTATE_270,180:Image.Transpose.ROTATE_180,270:Image.Transpose.ROTATE_90}
    if rotation in rot: out=out.transpose(rot[rotation])
    return out

def join(front,back,gap=24):
    if back is None:return front
    landscape=front.width>=front.height
    # Match orientation to the photograph, even when the handwriting remains sideways.
    if landscape!=(back.width>=back.height): back=back.transpose(Image.Transpose.ROTATE_270)
    if landscape:
        width=max(front.width,back.width)
        f,b=[im if im.width==width else im.resize((width,round(im.height*width/im.width)),Image.Resampling.LANCZOS) for im in [front,back]]
        size=(width,f.height+b.height+gap);pos=(0,f.height+gap)
    else:
        height=max(front.height,back.height)
        f,b=[im if im.height==height else im.resize((round(im.width*height/im.height),height),Image.Resampling.LANCZOS) for im in [front,back]]
        size=(f.width+b.width+gap,height);pos=(f.width+gap,0)
    if size[0]*size[1]>150_000_000:raise ValueError('Birleştirilmiş çıktı fazla büyük.')
    out=Image.new('RGB',size,'white');out.paste(f,(0,0));out.paste(b,pos)
    return out

def render_pair(batch,pair,root,preview=False):
    regs={r['id']:r for r in batch['regions']};scans={s['id']:s for s in batch['scans']}
    def get(rid,rotation=None):
        r=regs[rid];s=scans[r['scan_id']]
        return rectify(root/s['preview' if preview else 'raster'],r['corners'],r['rotation_clockwise'] if rotation is None else rotation,preview)
    front=get(pair['front_id']);back=get(pair['back_id'],pair['back_rotation_clockwise']) if pair.get('back_id') else None
    return join(front,back,12 if preview else 24)
