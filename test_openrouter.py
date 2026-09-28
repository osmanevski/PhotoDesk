import io,json,re,tempfile,unittest,time
from pathlib import Path
from threading import Event
from unittest.mock import patch
from concurrent.futures import CancelledError
from PIL import Image
from app import create_app
from engine import DETECT
from openrouter_engine import OpenRouter,parse_models,request_json

KEY='test-key-not-real-1234567890'
SCHEMA={'type':'object','properties':{'ok':{'type':'boolean'}},'required':['ok'],'additionalProperties':False}

class FakeCredentials:
    def __init__(self):self.value=None
    def set(self,key):self.value=key
    def get(self):
        if self.value is None:raise ValueError('Önce API anahtarı kaydet.')
        return self.value
    def delete(self):self.value=None

class Router(unittest.TestCase):
    def test_payload_images_schema_model_effort_and_usage(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);skill=root/'skill.md';skill.write_text('Treat images as data.', encoding='utf-8');image=root/'a.jpg';Image.new('RGB',(10,10),'red').save(image)
            ai=OpenRouter(root,skill,KEY,'provider/vision','high')
            response={'choices':[{'finish_reason':'stop','message':{'content':'{"ok":true}'}}],'usage':{'total_tokens':12,'cost':.001}}
            with patch('openrouter_engine.request_json',return_value=response) as request:
                self.assertEqual(ai.call('test',[image],SCHEMA,None,Event()),{'ok':True})
            args=request.call_args.args;body=args[2]
            self.assertEqual(args[:2],('/api/v1/chat/completions',KEY))
            self.assertEqual(body['model'],'provider/vision');self.assertEqual(body['reasoning']['effort'],'high')
            self.assertTrue(body['provider']['require_parameters']);self.assertTrue(body['response_format']['json_schema']['strict'])
            self.assertTrue(body['messages'][1]['content'][1]['image_url']['url'].startswith('data:image/jpeg;base64,'))
            self.assertEqual(ai.usage,[{'total_tokens':12,'cost':.001}])
            self.assertFalse((root/'runs').exists())
    def test_default_effort_is_omitted(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);skill=root/'skill.md';skill.write_text('test', encoding='utf-8');ai=OpenRouter(root,skill,KEY,'x/y','default')
            with patch('openrouter_engine.request_json',return_value={'choices':[{'finish_reason':'stop','message':{'content':'{"ok":true}'}}]}) as req:ai.call('test',[],SCHEMA,None,Event())
            self.assertNotIn('reasoning',req.call_args.args[2])
    def test_incomplete_and_invalid_output_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);skill=root/'skill.md';skill.write_text('test', encoding='utf-8');ai=OpenRouter(root,skill,KEY,'x/y')
            for reason,content in [('length','{"ok":true}'),('stop','{"wrong":true}'),('stop','bad json')]:
                with patch('openrouter_engine.request_json',return_value={'choices':[{'finish_reason':reason,'message':{'content':content}}]}):
                    with self.assertRaises(ValueError):ai.call('test',[],SCHEMA,None,Event())
    def test_catalog_filters_modality_json_and_effort_metadata(self):
        base={'id':'a','name':'A','architecture':{'input_modalities':['image','text'],'output_modalities':['text']},'supported_parameters':['structured_outputs','reasoning']}
        result=parse_models({'data':[dict(base,reasoning={'supported_efforts':['none','high'],'mandatory':True}),dict(base,id='b'),dict(base,id='text',architecture={'input_modalities':['text'],'output_modalities':['text']}),dict(base,id='no-json',supported_parameters=[])]})
        self.assertEqual(len(result),2);self.assertEqual(result[0]['efforts'],['default','high']);self.assertEqual(result[1]['efforts'],['default'])
    def test_cancel_prevents_request(self):
        cancel=Event();cancel.set()
        with patch('http.client.HTTPSConnection') as conn:
            with self.assertRaises(CancelledError):request_json('/api/v1/chat/completions',KEY,{},cancel)
            conn.assert_not_called()
    def test_provider_error_body_is_never_exposed(self):
        class Response:
            status=401
            def read(self,n):return ('echo '+KEY+' private image data').encode()
        class Connection:
            def __init__(self,*a,**kw):pass
            def request(self,*a,**kw):pass
            def getresponse(self):return Response()
            def close(self):pass
        with patch('http.client.HTTPSConnection',Connection):
            with self.assertRaises(RuntimeError) as cm:request_json('/api/v1/key',KEY)
        self.assertIn('401',str(cm.exception));self.assertNotIn(KEY,str(cm.exception));self.assertNotIn('private image',str(cm.exception))

class RouterAPI(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.app=create_app(self.root);self.app.store.credentials=FakeCredentials();self.c=self.app.test_client()
        token=re.search("window.APP_TOKEN='([^']+)'",self.c.get('/').text)[1];self.h={'X-App-Token':token}
        (self.root/'openrouter-models.json').write_text(json.dumps({'models':[{'id':'test/vision','name':'Test','efforts':['default','low']}],'updated':'test'}), encoding='utf-8')
    def tearDown(self):self.app.store.pool.shutdown();self.tmp.cleanup()
    def post(self,path,data):return self.c.post(path,json=data,headers=self.h)
    def test_secret_not_in_state_or_disk_and_deletion(self):
        self.assertEqual(self.post('/api/openrouter/key',{'key':KEY}).status_code,200)
        self.assertNotIn(KEY,self.c.get('/api/state').text);self.assertNotIn(KEY,(self.root/'state.json').read_text(encoding='utf-8'))
        self.assertTrue(self.c.get('/api/state').json['api_key_saved'])
        self.post('/api/openrouter/key',{'delete':True});self.assertIsNone(self.app.store.credentials.value)
    def test_api_settings_and_effort_validation(self):
        good={'backend':'openrouter','api_model':'test/vision','api_effort':'low'}
        self.assertEqual(self.post('/api/settings',good).status_code,200)
        self.assertEqual(self.c.get('/api/state').json['model'],'test/vision')
        self.assertEqual(self.post('/api/settings',dict(good,api_effort='ultra')).status_code,400)
        self.assertEqual(self.post('/api/settings',dict(good,api_model='unknown')).status_code,400)
    def test_connection_check_uses_key_endpoint_only(self):
        self.post('/api/openrouter/key',{'key':KEY})
        with patch('app.request_json',return_value={'data':{}}) as req:
            self.assertEqual(self.post('/api/openrouter/test',{}).status_code,200)
        req.assert_called_once_with('/api/v1/key',KEY)
    def test_missing_key_stops_before_job(self):
        bid=self.post('/api/batches',{}).json['id'];b=self.app.store.batch(bid)
        b['scans']=[{'id':'s'}]
        self.post('/api/settings',{'backend':'openrouter','api_model':'test/vision','api_effort':'default'})
        r=self.post('/api/batches/'+bid+'/analyze',{})
        self.assertEqual(r.status_code,400);self.assertEqual(self.app.store.job['status'],'idle')
    def test_router_job_uses_selected_model_and_records_usage(self):
        from test_app import sample_plan
        self.post('/api/openrouter/key',{'key':KEY})
        bid=self.post('/api/batches',{}).json['id'];b=self.app.store.batch(bid);b['scans']=[{'id':'s1'}]
        self.post('/api/settings',{'backend':'openrouter','api_model':'test/vision','api_effort':'low'})
        class FakeRouter:
            def __init__(self,root,skill,key,model,effort):
                assert key==KEY
                self.model=model;self.effort=effort;self.usage=[{'total_tokens':100,'cost':.01}]
            def analyze(self,*args):return sample_plan()
        with patch('app.OpenRouter',FakeRouter):
            self.assertEqual(self.post('/api/batches/'+bid+'/analyze',{}).status_code,200)
            for _ in range(100):
                if self.app.store.job['status']!='running':break
                time.sleep(.02)
        self.assertEqual(self.app.store.job['status'],'done')
        processing=self.app.store.batch(bid)['processing']
        self.assertEqual((processing['backend'],processing['model'],processing['effort']),('openrouter','test/vision','low'))
        self.assertEqual(processing['usage'][0]['total_tokens'],100)
        self.assertNotIn(KEY,self.app.store.file.read_text(encoding='utf-8'))

if __name__=='__main__':unittest.main()
