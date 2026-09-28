"""Synthetic portability regressions; no model calls or personal credentials."""
from pathlib import Path
from threading import Event
from unittest.mock import patch
import ctypes
import io
import json
import os
import re
import socket
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import uuid

from PIL import Image
from app import create_app
from credentials import Credentials, LinuxCredentials, WindowsCredentials, SERVICE, ACCOUNT
from engine import Astra
import platform_support as platform
from launcher import health

ROOT = Path(__file__).resolve().parent
TEXT = 'Çekilmez Ş — ş ğ ı İ'


class CredentialsTests(unittest.TestCase):
    def test_startup_never_opens_keychain(self):
        with tempfile.TemporaryDirectory() as temporary, patch('ctypes.CDLL', side_effect=AssertionError('No keychain at startup')):
            app = create_app(temporary)
            self.assertEqual(app.test_client().get('/api/health').status_code, 200)
            app.store.pool.shutdown()
        self.assertEqual(SERVICE, 'com.osmanevski.fotografmasasi.openrouter')
        self.assertEqual(ACCOUNT, 'openrouter')

    def test_linux_key_uses_stdin_and_errors_do_not_leak(self):
        key = 'fake-test-key-never-real-1234567890'
        backend = LinuxCredentials()
        with patch('shutil.which', return_value='/usr/bin/secret-tool'), patch('subprocess.run') as run:
            run.return_value = subprocess.CompletedProcess([], 0, '', '')
            backend.set(key)
            self.assertNotIn(key, repr(run.call_args.args))
            self.assertEqual(run.call_args.kwargs['input'], key)
            self.assertEqual(run.call_args.kwargs['timeout'], 30)
            run.return_value = subprocess.CompletedProcess([], 1, '', key)
            with self.assertRaises(RuntimeError) as error:
                backend.set(key)
            self.assertNotIn(key, str(error.exception))

    def test_unavailable_store_does_not_block_jpeg(self):
        with tempfile.TemporaryDirectory() as temporary, patch('shutil.which', return_value=None):
            app = create_app(temporary, credentials=LinuxCredentials())
            try:
                c = app.test_client()
                token = re.search("window.APP_TOKEN='([^']+)'", c.get('/').text)[1]
                headers = {'X-App-Token': token}
                response = c.post('/api/openrouter/key', json={'key': 'fake-test-key-never-real-1234567890'}, headers=headers)
                self.assertEqual(response.status_code, 400)
                self.assertIn('secret-tool', response.json['error'])
                self.assertEqual(c.get('/api/health').status_code, 200)
                bid = c.post('/api/batches', json={'name': TEXT}, headers=headers).json['id']
                image = io.BytesIO()
                Image.new('RGB', (100, 100), 'red').save(image, format='JPEG')
                response = c.post(f'/api/batches/{bid}/upload', data={'files': (io.BytesIO(image.getvalue()), '1a.jpg')}, headers=headers)
                self.assertEqual(response.json['added'], 1)
                c.post(f'/api/batches/{bid}/analyze', json={}, headers=headers)
                app.store.pool.shutdown(wait=True)
                self.assertEqual(app.store.job['status'], 'done')
                self.assertEqual(json.loads((Path(temporary)/'state.json').read_text(encoding='utf-8'))['batches'][0]['name'], TEXT)
            finally:
                app.store.pool.shutdown()

    @unittest.skipUnless(sys.platform == 'win32', 'Native Windows credential API')
    def test_windows_credential_roundtrip(self):
        backend = WindowsCredentials('photodesk-test-' + uuid.uuid4().hex)
        key = 'fake-test-key-never-real-1234567890'
        created = False
        try:
            try:
                backend.set(key)
                created = True
            except RuntimeError as error:
                if '(1312)' in str(error):
                    self.skipTest('Runner has no Windows logon session')
                raise
            self.assertEqual(backend.get(), key)
            backend.delete()
            with self.assertRaises(ValueError):
                backend.get()
        finally:
            if created:backend.delete()


class UploadTests(unittest.TestCase):
    def test_failed_generator_is_closed_before_cleanup_and_heic_is_clear(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = create_app(temporary)
            try:
                c = app.test_client()
                token = re.search("window.APP_TOKEN='([^']+)'", c.get('/').text)[1]
                headers = {'X-App-Token': token}
                bid = c.post('/api/batches', json={'name': TEXT}, headers=headers).json['id']
                image = io.BytesIO()
                Image.new('RGB', (20, 20), 'red').save(image, format='TIFF')
                closed = []
                def pages(path):
                    with open(path, 'rb'):
                        try:
                            yield Image.new('RGB', (20, 20)), 600, 'test'
                        finally:
                            closed.append(True)
                with patch('app.raster_pages', pages), patch.object(Image.Image, 'save', side_effect=OSError('simulated disk error')):
                    response = c.post(f'/api/batches/{bid}/upload', data={'files': (io.BytesIO(image.getvalue()), '1a.tiff')}, headers=headers)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(closed, [True])
                self.assertEqual(response.json['added'], 0)
                self.assertEqual(list((Path(temporary)/'sources'/bid).iterdir()), [])
                with patch('app.heic_supported', return_value=False):
                    response = c.post(f'/api/batches/{bid}/upload', data={'files': (io.BytesIO(b'fake'), 'scan.heic')}, headers=headers)
                self.assertIn('Upload a JPEG', response.json['errors'][0])
                self.assertEqual(list((Path(temporary)/'sources'/bid).iterdir()), [])
            finally:
                app.store.pool.shutdown()


class ProcessTests(unittest.TestCase):
    def test_codex_utf8_input_output_in_unicode_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)/TEXT
            root.mkdir()
            script = root/'fake_codex.py'
            script.write_text("import sys,json\nfrom pathlib import Path\ntext=sys.stdin.buffer.read().decode('utf-8')\nPath(sys.argv[sys.argv.index('-o')+1]).write_text(json.dumps({'text':text},ensure_ascii=False),encoding='utf-8')\n", encoding='utf-8')
            skill = root/'skill.md'
            skill.write_text(TEXT, encoding='utf-8')
            with patch('engine.codex_command', return_value=[sys.executable, str(script)]):
                result = Astra(root, skill).call(TEXT, [], {'type':'object'}, None, Event())
            self.assertEqual(result['text'], TEXT+'\n\n'+TEXT)

    def test_npm_wrapper_uses_node_directly_without_shell(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)/'Ç % & directory'
            root.mkdir()
            cmd = root/'codex.cmd'
            cmd.touch()
            node = root/'node.exe'
            node.touch()
            entry = root/'node_modules/@openai/codex/bin/codex.js'
            entry.parent.mkdir(parents=True)
            entry.touch()
            with patch.object(platform.sys, 'platform', 'win32'), patch.dict(os.environ, {'PHOTODESK_CODEX': str(cmd)}):
                self.assertEqual(platform.codex_command(), [str(node.resolve()), str(entry.resolve())])

    def test_stop_kills_descendant(self):
        with tempfile.TemporaryDirectory() as temporary:
            heartbeat = Path(temporary)/'heartbeat'
            script = Path(temporary)/'tree.py'
            script.write_text("import sys,subprocess,time\nfrom pathlib import Path\nif len(sys.argv)>2:\n while True:\n  Path(sys.argv[1]).write_text(str(time.time()),encoding='ascii');time.sleep(.05)\nelse:\n subprocess.Popen([sys.executable,__file__,sys.argv[1],'child'])\n time.sleep(60)\n", encoding='utf-8')
            proc = subprocess.Popen([sys.executable, str(script), str(heartbeat)], **platform.child_options())
            try:
                deadline = time.monotonic()+10
                while not heartbeat.exists() and time.monotonic()<deadline:
                    time.sleep(.05)
                self.assertTrue(heartbeat.exists())
                platform.stop_process_tree(proc)
                self.assertIsNotNone(proc.poll())
                time.sleep(.2)
                before = heartbeat.read_bytes()
                time.sleep(.3)
                self.assertEqual(heartbeat.read_bytes(), before)
            finally:
                if proc.poll() is None:
                    platform.stop_process_tree(proc)

    def test_lock_is_released_after_process_exit(self):
        with tempfile.TemporaryDirectory() as temporary:
            lock = Path(temporary)/'test.lock'
            command = [sys.executable, '-c', 'from platform_support import instance_lock; import sys;\nwith instance_lock(sys.argv[1],timeout=0):pass', str(lock)]
            with platform.instance_lock(lock):
                busy = subprocess.run(command, cwd=ROOT, capture_output=True)
                self.assertNotEqual(busy.returncode, 0)
            self.assertEqual(subprocess.run(command, cwd=ROOT, capture_output=True).returncode, 0)


class ServerTests(unittest.TestCase):
    def test_launcher_starts_server_and_second_launch_reuses_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)/TEXT
            root.mkdir()
            with socket.socket() as sock:
                sock.bind(('127.0.0.1',0))
                port = sock.getsockname()[1]
            command = [sys.executable, str(ROOT/'launcher.py'), '--no-open', '--port', str(port), '--data', str(root)]
            pid = None
            try:
                first = subprocess.run(command, capture_output=True, timeout=45)
                self.assertEqual(first.returncode, 0, first.stderr)
                pid = int((root/'server.pid').read_text(encoding='utf-8'))
                self.assertTrue(health(f'http://127.0.0.1:{port}', root))
                second = subprocess.run(command, capture_output=True, timeout=15)
                self.assertEqual(second.returncode, 0, second.stderr)
                self.assertEqual(int((root/'server.pid').read_text(encoding='utf-8')), pid)
            finally:
                if pid is not None:
                    try:os.kill(pid, signal.SIGTERM)
                    except ProcessLookupError:pass
                    with platform.instance_lock(root/'server.lock', timeout=10):pass

    def test_server_lock_launcher_health_and_proxy_bypass(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)/TEXT
            root.mkdir()
            with socket.socket() as sock:
                sock.bind(('127.0.0.1',0))
                port = sock.getsockname()[1]
            command = [sys.executable, str(ROOT/'app.py'), '--port', str(port), '--data', str(root)]
            with (root/'test.log').open('wb') as log:
                proc = subprocess.Popen(command, stdout=log, stderr=log, **platform.child_options())
                try:
                    url = f'http://127.0.0.1:{port}'
                    deadline = time.monotonic()+30
                    while time.monotonic()<deadline:
                        if health(url, root):break
                        if proc.poll() is not None:self.fail((root/'test.log').read_text(encoding='utf-8'))
                        time.sleep(.1)
                    self.assertTrue(health(url, root))
                    second = subprocess.run(command, capture_output=True, timeout=15)
                    self.assertNotEqual(second.returncode, 0)
                    self.assertIn(b'already starting or running', second.stderr)
                    with self.assertRaisesRegex(RuntimeError, 'another app'):
                        health(url, root/'other')
                    env = os.environ.copy()
                    env.update(HTTP_PROXY='http://127.0.0.1:9', HTTPS_PROXY='http://127.0.0.1:9', NO_PROXY='')
                    launch = subprocess.run([sys.executable, str(ROOT/'launcher.py'), '--no-open', '--port', str(port), '--data', str(root)], env=env, capture_output=True, timeout=15)
                    self.assertEqual(launch.returncode, 0, launch.stderr)
                    self.assertIsNone(proc.poll())
                finally:
                    platform.stop_process_tree(proc)

class InstallerTests(unittest.TestCase):
    def test_repair_venv_created_without_pip(self):
        from install import ensure_runtime
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)/'runtime'
            subprocess.run([sys._base_executable, '-m', 'venv', '--without-pip', str(root)], check=True)
            python = root/('Scripts/python.exe' if sys.platform=='win32' else 'bin/python')
            self.assertNotEqual(subprocess.run([str(python), '-m', 'pip', '--version'], capture_output=True).returncode, 0)
            ensure_runtime(python)
            self.assertEqual(subprocess.run([str(python), '-m', 'pip', '--version'], capture_output=True).returncode, 0)

    def test_folder_open_is_detached(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(platform.sys, 'platform', 'linux'), patch('shutil.which', return_value='/usr/bin/xdg-open'), patch('subprocess.Popen') as start:
            platform.open_folder(temporary)
            self.assertEqual(start.call_args.args[0], ['xdg-open', str(Path(temporary).resolve())])
            self.assertTrue(start.call_args.kwargs['start_new_session'])

    def test_cancel_while_child_does_not_read_large_prompt(self):
        from concurrent.futures import CancelledError
        from threading import Timer
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = root/'blocked.py'
            script.write_text('import time; time.sleep(60)', encoding='utf-8')
            skill = root/'skill.md'
            skill.write_text('test', encoding='utf-8')
            event = Event()
            timer = Timer(.2, event.set)
            timer.start()
            start = time.monotonic()
            try:
                with patch('engine.codex_command', return_value=[sys.executable, str(script)]):
                    with self.assertRaises(CancelledError):
                        Astra(root, skill).call('x'*1000000, [], {}, None, event)
                self.assertLess(time.monotonic()-start, 10)
            finally:
                timer.cancel()


if __name__ == '__main__':
    unittest.main()
