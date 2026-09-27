import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app import create_app
from localization import localize_response
from scripts.build_locales import build

class Localization(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.app=create_app(self.tmp.name);self.c=self.app.test_client()
    def tearDown(self):
        self.app.store.pool.shutdown(wait=True);self.tmp.cleanup()
    def test_english_default_and_turkish_cookie(self):
        response=self.c.get('/');self.assertIn('lang="en"',response.text)
        self.assertIn('New batch',response.text);self.assertIn('/static/app.js',response.text)
        self.assertEqual(self.c.get('/api/state').json['job']['message'],'Ready')
        self.c.set_cookie('photo-desk-language','tr')
        response=self.c.get('/');self.assertIn('lang="tr"',response.text)
        self.assertIn('Yeni iş',response.text);self.assertIn('/static/app.tr.js',response.text)
        self.assertEqual(self.c.get('/api/state').json['job']['message'],'Hazır')
    def test_errors_localized_but_saved_user_data_untouched(self):
        self.assertIn('reload',self.c.post('/api/batches',json={}).json['error'])
        payload={'batches':[{'name':'Hazır','notes':'İş bulunamadı.','scans':[{'name':'Önce tarama dosyalarını ekle.jpeg'}]}], 'job':{'message':'Yerel işlem başlatılıyor'}}
        result=localize_response(payload,'en')
        self.assertEqual(result['batches'],payload['batches'])
        self.assertEqual(result['job']['message'],'Starting local processing')
        self.assertEqual(payload['job']['message'],'Yerel işlem başlatılıyor')
    def test_ai_language_instruction_does_not_pollute_user_note(self):
        token=re.search("window.APP_TOKEN='([^']+)'",self.c.get('/').text)[1]
        headers={'X-App-Token':token}
        bid=self.c.post('/api/batches',json={'name':'Özel ad'},headers=headers).json['id']
        batch=self.app.store.batch(bid);batch['scans']=[{'id':'s1'}]
        self.app.store.state['settings']['backend']='ai'
        result={'regions':[],'pairs':[],'notes':'No photos'}
        with patch.object(self.app.store.ai,'analyze',return_value=result) as analyze:
            self.c.post(f'/api/batches/{bid}/analyze',json={'instruction':'Notumu koru'},headers=headers)
            self.app.store.pool.shutdown(wait=True)
        self.assertIn('in English',analyze.call_args.args[1])
        self.assertEqual(batch['instruction'],'Notumu koru')
        self.assertEqual(batch['name'],'Özel ad')
    def test_generated_assets_are_current(self):build(check=True)

if __name__=='__main__':unittest.main()
