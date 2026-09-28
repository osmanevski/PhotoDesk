"""Optional browser regression check using synthetic scans only.

Install playwright and its Chromium browser in a development environment, run
app.py with an EMPTY temporary data directory on port 8875, then run this file.
"""
from pathlib import Path
import argparse
import tempfile
from PIL import Image,ImageDraw
from playwright.sync_api import sync_playwright,expect

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--url',default='http://127.0.0.1:8875');parser.add_argument('--screenshot');parser.add_argument('--channel',help='e.g. chrome to use the installed browser');args=parser.parse_args()
    with tempfile.TemporaryDirectory() as temporary, sync_playwright() as p:
        root=Path(temporary)
        front=Image.new('RGB',(800,1000),'white');back=front.copy()
        f=ImageDraw.Draw(front);b=ImageDraw.Draw(back)
        for index,(x,y) in enumerate([(30,30),(430,30),(30,530),(430,530)]):
            f.rectangle((x,y,x+330,y+410),fill='#eee9df')
            f.rectangle((x+20,y+20,x+310,y+330),fill=['#9ab5c3','#adc0ac','#a7acb9','#c7b28f'][index])
            f.ellipse((x+220,y+55,x+265,y+100),fill='#f8edcf')
            f.polygon([(x+20,y+330),(x+100,y+160),(x+180,y+260),(x+240,y+210),(x+310,y+330)],fill=['#486377','#526c5a','#656d7f','#847259'][index])
            b.rectangle((x,y,x+330,y+410),fill='#eee9df')
            if index!=1:
                for line in range(5):b.line((x+35,y+70+line*45,x+260-line*12,y+70+line*45),fill='#536779',width=4)
        front.save(root/'1a.png');back.save(root/'1b.png')
        browser=p.chromium.launch(headless=True,channel=args.channel);page=browser.new_page(viewport={'width':1500,'height':1000},device_scale_factor=1)
        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto(args.url);page.wait_for_load_state('networkidle')
        expect(page.locator('html')).to_have_attribute('lang','en')
        # First drop creates a batch automatically.
        page.locator('#fileInput').set_input_files([str(root/'1a.png'),str(root/'1b.png')])
        expect(page.locator('.scan')).to_have_count(2)
        page.locator('#layoutSelect').select_option('2x2')
        page.locator('[data-action=analyze]').click()
        expect(page.locator('.card')).to_have_count(4,timeout=20000)
        expect(page.locator('#jobtext')).to_contain_text('photos ready')
        # Every preview must actually load.
        page.wait_for_function("[...document.querySelectorAll('.card img')].every(i=>i.complete&&i.naturalWidth>0)",timeout=20000)
        # Approve moves to the next photo waiting for review; keyboard A works too.
        page.locator('.card').first.click();page.locator('[data-action=approve]').click()
        expect(page.locator('.card.active .num')).to_have_text('002')
        for _ in range(3):page.keyboard.press('a');page.wait_for_timeout(400)
        expect(page.locator('[data-filter=approved] span')).to_have_text('4')
        # Corner edit stays a draft until saved, then sends the photo back to review.
        page.locator('[data-view=scans]').click();expect(page.locator('.corner')).to_have_count(4)
        page.locator('.corner').first.hover();corner=page.locator('.corner').first.bounding_box()
        page.mouse.move(corner['x']+corner['width']/2,corner['y']+corner['height']/2);page.mouse.down()
        page.mouse.move(corner['x']+30,corner['y']+25,steps=4);page.mouse.up()
        expect(page.locator('.draft-bar')).to_be_visible();expect(page.locator('#exportTop')).to_be_disabled()
        page.locator('.draft-bar [data-action=save-draft]').click();expect(page.locator('.draft-bar')).to_have_count(0)
        page.locator('[data-view=photos]').click();expect(page.locator('[data-filter=review] span')).to_have_text('1')
        page.locator('[data-filter=review]').click();page.locator('.card').first.click();page.locator('[data-action=approve]').click()
        # Switching language reloads the UI but must preserve the working plan.
        page.locator('#languageSelect').select_option('tr');page.wait_for_load_state('networkidle')
        expect(page.locator('html')).to_have_attribute('lang','tr')
        expect(page.locator('#newBatch')).to_contain_text('Yeni iş')
        expect(page.locator('.card')).to_have_count(4)
        page.locator('#languageSelect').select_option('en');page.wait_for_load_state('networkidle')
        expect(page.locator('.card')).to_have_count(4)
        page.locator('#exportTop').click();page.locator('#exportDir').fill(str(root/'export'))
        page.locator('#doExport').click();expect(page.locator('#exportResult .success')).to_contain_text('4 JPEGs saved.',timeout=20000)
        assert len(list((root/'export').rglob('*.jpg')))==4
        page.locator('#exportDialog .close').click()
        if args.screenshot:
            target=Path(args.screenshot);target.parent.mkdir(parents=True,exist_ok=True)
            page.screenshot(path=str(target),full_page=True)
        page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(100)
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),'Mobile horizontal overflow'
        assert not errors,errors
        browser.close();print('PASS: auto batch, 4-photo local processing, approve-and-next, corner draft, EN/TR persistence, JPEG export, responsive layout; no JS errors.')

if __name__=='__main__':main()
