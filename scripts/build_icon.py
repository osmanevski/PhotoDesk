"""Render the app's simple geometric mark at native macOS icon resolutions.

Matches static/icon.svg; no photographs or generated image content are used.
Requires Pillow (already an application dependency).
"""
from pathlib import Path
from PIL import Image, ImageDraw

def build():
    root=Path(__file__).resolve().parents[1]/'static'
    # Supersample edges, then generate ICNS with Pillow's standard size table.
    scale=2
    im=Image.new('RGBA',(1024*scale,1024*scale))
    d=ImageDraw.Draw(im)
    def box(v): return tuple(int(x*scale) for x in v)
    def rounded(v,r,c): d.rounded_rectangle(box(v),radius=r*scale,fill=c)
    def line(points,c,w):
        d.line([(x*scale,y*scale) for x,y in points],fill=c,width=w*scale,joint='curve')
        for x,y in points:d.ellipse(box((x-w/2,y-w/2,x+w/2,y+w/2)),fill=c)
    navy='#244f68';blue='#9dc3d4';paper='#f8f5ec';gold='#eeb965'
    rounded((64,64,960,960),196,navy)
    rounded((206,198,660,752),24,blue)
    line([(262,264),(394,264)],navy,18);line([(262,310),(472,310)],navy,18)
    rounded((334,326,818,830),24,paper)
    d.rectangle(box((378,370,774,694)),fill=blue)
    d.ellipse(box((632,414,708,490)),fill=paper)
    d.polygon([(x*scale,y*scale) for x,y in [(378,694),(502,514),(590,624),(654,548),(774,694)]],fill=navy)
    line([(174,406),(174,334),(246,334)],gold,24)
    line([(778,230),(850,230),(850,302)],gold,24)
    im=im.resize((1024,1024),Image.Resampling.LANCZOS)
    im.save(root/'icon.png');im.save(root/'AppIcon.icns')

if __name__=='__main__':build()
