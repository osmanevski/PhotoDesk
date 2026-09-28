import copy,hashlib,io,json,re,tempfile,time,unittest,sys
from pathlib import Path
from concurrent.futures import CancelledError
from unittest.mock import patch
import pymupdf as fitz
from PIL import Image,ImageDraw
from app import create_app
from engine import validate_plan,validate_groups,normalize_ai
from imaging import join,rectify,raster_pages,validate_corners
from local_engine import LocalProcessor,ink_score
from model_config import catalog,validate_settings
import numpy as np
from threading import Event

def sample_region(id='front',scan='s1',role='front'):
    return dict(id=id,scan_id=scan,role=role,label=id,corners=[[0,0],[1,0],[1,1],[0,1]],rotation_clockwise=0,confidence=1)
def sample_pair():
    return dict(id='p1',front_id='front',back_id=None,name='çam-ağacı',back_rotation_clockwise=0,back_status='blank',confidence=1,needs_review=False,matching_notes='Kullanıcı doğruladı.')
def sample_plan():return dict(regions=[sample_region()],pairs=[sample_pair()],notes='')

class Geometry(unittest.TestCase):
    def test_landscape_edges_and_gap(self):
        im=join(Image.new('RGB',(400,200),'red'),Image.new('RGB',(200,100),'blue'))
        self.assertEqual(im.size,(400,424));self.assertEqual(im.getpixel((0,0)),(255,0,0))
        self.assertEqual(im.getpixel((0,210)),(255,255,255));self.assertEqual(im.getpixel((399,423)),(0,0,255))
    def test_portrait_back_direction_matches_photo(self):
        im=join(Image.new('RGB',(100,200),'red'),Image.new('RGB',(200,100),'blue'))
        self.assertEqual(im.size,(224,200));self.assertEqual(im.getpixel((223,199)),(0,0,255))
    def test_blank_keeps_single(self):
        im=Image.new('RGB',(100,200));self.assertIs(join(im,None),im)
    def test_rectification_color_rotation(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'test.png';im=Image.new('RGB',(201,101),'red');im.paste('blue',(101,0,201,101));im.save(p)
            out=rectify(p,[[0,0],[1,0],[1,1],[0,1]],90)
            self.assertEqual(out.size,(100,200));self.assertEqual(out.getpixel((50,10)),(255,0,0));self.assertEqual(out.getpixel((50,190)),(0,0,255))
    def test_crossed_outside_and_zero_rejected(self):
        for points in [[[0,0],[1,1],[1,0],[0,1]],[[-.1,0],[1,0],[1,1],[0,1]],[[0,0]]*4]:
            with self.assertRaises(ValueError):validate_corners(points)
    def test_pdf_embedded_jpeg_keeps_native_size(self):
        with tempfile.TemporaryDirectory() as d:
            im=Image.new('RGB',(600,300),'red');buf=io.BytesIO();im.save(buf,format='JPEG')
            doc=fitz.open();page=doc.new_page(width=72,height=36);page.insert_image(page.rect,stream=buf.getvalue());p=Path(d)/'scan.pdf';doc.save(p);doc.close()
            result=list(raster_pages(p));self.assertEqual(result[0][0].size,(600,300));self.assertEqual(result[0][1],600);self.assertIn('özgün',result[0][2])

class Plans(unittest.TestCase):
    def test_front_must_be_in_result(self):
        p=sample_plan();p['pairs']=[]
        with self.assertRaises(ValueError):validate_plan(p,{'s1'})
    def test_duplicate_back_rejected(self):
        p=sample_plan();p['regions'] += [sample_region('front2'),sample_region('back',role='back')]
        p['pairs'][0].update(back_id='back',back_status='matched');p['pairs'].append(dict(p['pairs'][0],id='p2',front_id='front2'))
        with self.assertRaises(ValueError):validate_plan(p,{'s1'})
    def test_cross_number_pair_rejected(self):
        p=sample_plan();p['regions'].append(sample_region('back','s2','back'));p['pairs'][0].update(back_id='back',back_status='matched')
        with self.assertRaises(ValueError):validate_groups(p,[{'id':'s1','group_key':'1'},{'id':'s2','group_key':'2'}])
    def test_missing_never_auto_approved(self):
        p=sample_plan();p['pairs'][0]['back_status']='not_provided';normalize_ai(p);self.assertTrue(p['pairs'][0]['needs_review'])

class API(unittest.TestCase):
    def setUp(self):
        model_patch=patch('model_config.catalog',return_value=[{'id':'gpt-6-astra','name':'Astra','efforts':['medium']},{'id':'gpt-6-luna','name':'Luna','efforts':['low','medium','high']}]);model_patch.start();self.addCleanup(model_patch.stop)
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.app=create_app(self.root/'state');self.c=self.app.test_client()
        token=re.search("window.APP_TOKEN='([^']+)'",self.c.get('/').text)[1];self.h={'X-App-Token':token}
        self.bid=self.post('/api/batches',{'name':'Test / arşiv'}).json['id'];self.url='/api/batches/'+self.bid
        im=Image.new('RGB',(400,200),'red');buf=io.BytesIO();im.save(buf,format='JPEG',dpi=(600,600));self.raw=buf.getvalue()
        self.c.post(self.url+'/upload',data={'files':(io.BytesIO(self.raw),'1a.jpeg')},headers=self.h)
        b=self.b();self.plan=sample_plan();self.plan['regions'][0]['scan_id']=b['scans'][0]['id']
    def tearDown(self):self.app.store.pool.shutdown(wait=True);self.tmp.cleanup()
    def b(self):return self.c.get('/api/state').json['batches'][0]
    def post(self,url,data):return self.c.post(url,json=data,headers=self.h)
    def save(self):return self.post(self.url+'/plan',dict(self.plan,revision=self.b()['revision']))
    def test_csrf_and_host(self):
        self.assertEqual(self.c.post('/api/batches',json={}).status_code,403)
        self.assertEqual(self.c.get('/api/state',headers={'Host':'evil.example'}).status_code,403)
    def test_upload_grouping_deduplication(self):
        s=self.b()['scans'][0];self.assertEqual((s['group_key'],s['role_hint']),('1','front'))
        r=self.c.post(self.url+'/upload',data={'files':(io.BytesIO(self.raw),'1a.jpeg')},headers=self.h)
        self.assertEqual(r.json['added'],0);self.assertEqual(len(self.b()['scans']),1)
    def test_revision_and_undo(self):
        self.assertEqual(self.save().status_code,200);rev=self.b()['revision']
        self.assertEqual(self.post(self.url+'/plan',dict(self.plan,revision=rev-1)).status_code,400)
        self.assertEqual(self.post(self.url+'/undo',{}).status_code,200);self.assertEqual(self.b()['pairs'],[])
    def test_export_originals_safe_and_jpeg_settings(self):
        self.save();source=self.app.store.root/self.b()['scans'][0]['original'];before=hashlib.sha256(source.read_bytes()).hexdigest()
        data={'directory':str(self.root/'exports'),'revision':self.b()['revision']};r=self.post(self.url+'/export',data)
        self.assertEqual(r.status_code,200,r.json);out=Path(r.json['directory']);jpg=out/r.json['files'][0]['name']
        self.assertEqual(jpg.name,'001-cam-agaci.jpg');self.assertTrue((out/'arsiv-kaydi.json').exists())
        with Image.open(jpg) as im:self.assertEqual(im.info['dpi'],(600,600));self.assertEqual(im.layer[0][1:3],(1,1))
        r2=self.post(self.url+'/export',data);self.assertNotEqual(r2.json['directory'],str(out));self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),before)
        self.assertEqual(self.c.get('/api/exports/'+r.json['id']+'/zip').status_code,200)
    def test_review_not_exported(self):
        self.plan['pairs'][0]['needs_review']=True;self.save();r=self.post(self.url+'/export',{'directory':str(self.root/'exports')});self.assertEqual(r.status_code,400)
    def test_cancel_keeps_previous_plan(self):
        self.save();before=self.b()['pairs']
        self.post('/api/settings',{'backend':'ai','model':'gpt-6-astra','effort':'medium','layout':'auto'})
        def fake(batch,instruction,update,cancel):
            cancel.wait(3);raise CancelledError()
        with patch.object(self.app.store.ai,'analyze',side_effect=fake):
            self.post(self.url+'/analyze',{});self.post('/api/cancel',{})
            for _ in range(100):
                if self.app.store.job['status']!='running':break
                time.sleep(.02)
        self.assertEqual(self.app.store.job['status'],'cancelled');self.assertEqual(self.b()['pairs'],before)

    def test_settings_persist_and_reject_unsupported_effort(self):
        r=self.post('/api/settings',{'backend':'ai','model':'gpt-6-luna','effort':'low','layout':'2x2'})
        self.assertEqual(r.status_code,200,r.json)
        self.assertEqual(self.c.get('/api/state').json['settings']['model'],'gpt-6-luna')
        self.assertEqual(json.loads(self.app.store.file.read_text(encoding='utf-8'))['settings']['effort'],'low')
        self.assertEqual(self.post('/api/settings',{'backend':'ai','model':'gpt-6-luna','effort':'ultra'}).status_code,400)
        self.assertEqual(self.post('/api/settings',{'backend':'ai','model':'not-a-model'}).status_code,400)

    def test_local_api_never_calls_model_and_preserves_provenance(self):
        with patch.object(self.app.store.ai,'analyze',side_effect=AssertionError('Model must not be called')) as ai:
            self.post(self.url+'/analyze',{})
            for _ in range(100):
                if self.app.store.job['status']!='running':break
                time.sleep(.02)
            ai.assert_not_called()
        self.assertEqual(self.app.store.job['status'],'done',self.app.store.job)
        b=self.b();self.assertEqual(b['processing']['backend'],'local');self.assertIsNone(b['processing']['model'])
        self.assertTrue(all(p['needs_review'] for p in b['pairs']))

class Offline(unittest.TestCase):
    def test_four_photos_three_written_backs_and_blank(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);front=Image.new('RGB',(800,1000),'white');back=front.copy()
            f=ImageDraw.Draw(front);b=ImageDraw.Draw(back)
            for index,(x,y) in enumerate([(30,30),(430,30),(30,530),(430,530)]):
                f.rectangle((x,y,x+330,y+410),fill=['#405060','#506030','#405080','#806040'][index])
                b.rectangle((x,y,x+330,y+410),fill='#eeeeee')
                if index!=1:
                    for line in range(5):b.line((x+35,y+50+line*45,x+260,y+50+line*45),fill='#333333',width=4)
            front.save(root/'front.png');back.save(root/'back.png')
            scans=[dict(id='f',name='1a.png',preview='front.png',role_hint='front',group_key='1',page=1,order=1),dict(id='b',name='1b.png',preview='back.png',role_hint='back',group_key='1',page=1,order=2)]
            with patch('subprocess.Popen',side_effect=AssertionError('Offline processing must not launch any model')):
                plan=LocalProcessor(root).analyze({'scans':scans},'2x2',lambda _:None,Event())
            self.assertEqual(len(plan['pairs']),4)
            self.assertEqual(sum(p['back_status']=='matched' for p in plan['pairs']),3)
            blank=next(p for p in plan['pairs'] if p['back_status']=='blank');self.assertIsNone(blank['back_id'])
            self.assertTrue(all(p['needs_review'] for p in plan['pairs']))
    def test_faint_writing_not_blank(self):
        im=Image.new('RGB',(400,500),'#fafafa');draw=ImageDraw.Draw(im)
        for y in range(80,400,50):draw.line((50,y,350,y),fill='#d0d0d0',width=3)
        self.assertGreater(ink_score(np.asarray(im)),.0007)
        self.assertLess(ink_score(np.asarray(Image.new('RGB',(400,500),'#eeeeee'))),.0007)
    def test_cancellation_and_missing_back(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'a.png';Image.new('RGB',(300,400),'#405050').save(p)
            batch={'scans':[dict(id='f',name='1a.png',preview='a.png',role_hint='front',group_key='1',page=1,order=1)]}
            e=Event();e.set()
            with self.assertRaises(CancelledError):LocalProcessor(d).analyze(batch,'auto',lambda _:None,e)
            e.clear();plan=LocalProcessor(d).analyze(batch,'auto',lambda _:None,e)
            self.assertEqual(plan['pairs'][0]['back_status'],'not_provided')
    def test_catalog_reads_supported_efforts_not_fixed_list(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'models.json';p.write_text(json.dumps({'models':[{'slug':'gpt-test','display_name':'Test','input_modalities':['image'],'supported_reasoning_levels':[{'effort':'low'},{'effort':'high'}]}]}), encoding='utf-8')
            self.assertEqual(catalog(p)[0]['efforts'],['low','high'])
    def test_selected_model_and_effort_reach_cli(self):
        from engine import Astra
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);skill=root/'skill.md';skill.write_text('Return JSON', encoding='utf-8')
            captured=[]
            def fake_popen(cmd,**kwargs):
                captured.extend(cmd);raise RuntimeError('stop-before-network')
            ai=Astra(root,skill,model='gpt-6-luna',effort='low')
            with patch('subprocess.Popen',side_effect=fake_popen),patch('engine.codex_command',return_value=[sys.executable]):
                with self.assertRaisesRegex(RuntimeError,'stop-before-network'):ai.call('test',[],{},None,Event())
            self.assertEqual(captured[captured.index('--model')+1],'gpt-6-luna')
            self.assertIn('model_reasoning_effort="low"',captured)

if __name__=='__main__':unittest.main(verbosity=2)
