import json
import re
from pathlib import Path
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app import create_app
from localization import localize_response

class Localization(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.app=create_app(self.tmp.name);self.c=self.app.test_client()
    def tearDown(self):
        self.app.store.pool.shutdown(wait=True);self.tmp.cleanup()
    def test_english_default_and_turkish_cookie(self):
        response=self.c.get('/');self.assertIn('lang="en"',response.text)
        self.assertIn('Save JPEGs',response.text);self.assertIn('/static/app.js',response.text)
        self.assertNotIn('{{',response.text)
        strings=json.loads(re.search(r'<script type="application/json" id="strings">(.*?)</script>',response.text,re.S)[1])
        self.assertEqual(strings['batch.new'],'+ New batch')
        self.assertEqual(self.c.get('/api/state').json['job']['message'],'Ready')
        self.c.set_cookie('photo-desk-language','tr')
        response=self.c.get('/');self.assertIn('lang="tr"',response.text)
        self.assertIn('JPEG kaydet',response.text);self.assertIn('/static/app.js',response.text)
        self.assertIn('"batch.new": "+ Yeni iş"',response.text)
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
    def test_ui_strings_complete(self):
        static=Path(__file__).resolve().parent/'static'
        strings=json.loads((static/'strings.json').read_text(encoding='utf-8'))
        self.assertEqual(set(strings['en']),set(strings['tr']))
        used=set(re.findall(r"\bt\('([\w.]+)'",(static/'app.js').read_text(encoding='utf-8')))
        used|=set(re.findall(r'\{\{t:([\w.]+)\}\}',(static/'index.html').read_text(encoding='utf-8')))
        self.assertEqual(used-set(strings['en']),set())
        for language in strings.values():
            for value in language.values():
                for text in ([value] if isinstance(value,str) else value.values()):
                    self.assertNotIn('</script',text.lower())
    def test_previews_cacheable_only_when_versioned(self):
        with self.c.get('/static/style.css?v=1') as r:self.assertEqual(r.headers['Cache-Control'],'private, max-age=31536000, immutable')
        with self.c.get('/static/style.css') as r:self.assertEqual(r.headers['Cache-Control'],'no-store')
        self.assertEqual(self.c.get('/api/state').headers['Cache-Control'],'no-store')

if __name__=='__main__':unittest.main()
