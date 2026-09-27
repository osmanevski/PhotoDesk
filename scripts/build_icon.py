"""Render the two-stroke PhotoDesk crop mark; matches static/icon.svg."""
from pathlib import Path
from PIL import Image, ImageDraw

def build():
    root=Path(__file__).resolve().parents[1]/'static'
    scale=4
    im=Image.new('RGBA',(1024*scale,1024*scale))
    d=ImageDraw.Draw(im)
    d.rounded_rectangle(tuple(v*scale for v in (64,64,960,960)),radius=196*scale,fill='#222629')
    # Rectangles give the two strokes square ends and exact mitered corners.
    for box in [(320,224,384,704),(320,640,800,704),(224,320,704,384),(640,320,704,800)]:
        d.rectangle(tuple(v*scale for v in box),fill='#fafafa')
    im=im.resize((1024,1024),Image.Resampling.LANCZOS)
    im.save(root/'icon.png');im.save(root/'AppIcon.icns')
    im.resize((32,32),Image.Resampling.LANCZOS).save(root/'favicon.png')

if __name__=='__main__':build()
