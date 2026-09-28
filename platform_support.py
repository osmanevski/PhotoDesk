"""Small OS boundary; image processing stays platform-independent."""
from contextlib import contextmanager
from pathlib import Path
import errno
import hashlib
import os
import shutil
import signal
import subprocess
import sys
import time
import webbrowser


def data_dir():
    if sys.platform == 'darwin':
        return Path.home() / 'Library/Application Support/FotografMasasi'
    if sys.platform == 'win32':
        return Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData/Local') / 'PhotoDesk'
    base = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share')
    if not base.is_absolute():
        base = Path.home() / '.local/share'
    return base / 'photodesk'


def data_id(path):
    return hashlib.sha256(os.path.normcase(str(Path(path).resolve())).encode('utf-8')).hexdigest()


def runtime_python():
    return data_dir() / 'runtime' / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')


def child_options(detach=False):
    if sys.platform == 'win32':
        # Server survives closing the terminal. Model processes must remain killable as a tree.
        return {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP |
                (subprocess.DETACHED_PROCESS if detach else subprocess.CREATE_NO_WINDOW)}
    return {'start_new_session': True}


@contextmanager
def instance_lock(path, timeout=30):
    """Kernel-owned lock: released on crash; never unlink a live lock file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as handle:
        if path.stat().st_size == 0:
            handle.write(b'0')
            handle.flush()
        if sys.platform == 'win32':
            import msvcrt
            def acquire():
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            def release():
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            def acquire():
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            def release():
                fcntl.flock(handle, fcntl.LOCK_UN)
        deadline = time.monotonic() + timeout
        while True:
            try:
                acquire()
                break
            except OSError as error:
                if error.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
                if time.monotonic() >= deadline:
                    raise RuntimeError('PhotoDesk is already starting or running for this data folder.') from None
                time.sleep(.1)
        try:
            yield
        finally:
            release()


def open_folder(path):
    path = str(Path(path).resolve())
    if sys.platform == 'win32':
        os.startfile(path)
    else:
        tool = 'open' if sys.platform == 'darwin' else 'xdg-open'
        if not shutil.which(tool):
            raise RuntimeError('Klasör açılamadı. Dosya yöneticisini kur veya çıktı yolunu elle aç.')
        subprocess.Popen([tool, path], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)


def open_browser(url):
    if not webbrowser.open(url):
        raise RuntimeError('Open PhotoDesk in your browser: ' + url)


def alert(message):
    print(message, file=sys.stderr)
    try:
        if sys.platform == 'darwin':
            # Pass data as argv, never insert it into AppleScript source.
            script = 'on run argv\ndisplay alert "PhotoDesk" message (item 1 of argv) as critical\nend run'
            subprocess.run(['osascript', '-e', script, message], timeout=30, check=False)
        elif sys.platform == 'win32':
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, 'PhotoDesk', 0x10)
    except (OSError, subprocess.TimeoutExpired):
        pass


def launcher_environment():
    env = os.environ.copy()
    paths = [str(Path.home() / '.local/bin')]
    if sys.platform == 'darwin':
        paths = ['/opt/homebrew/bin', '/usr/local/bin'] + paths
    env['PATH'] = os.pathsep.join(paths + [env.get('PATH', '')])
    env['PYTHONUNBUFFERED'] = '1'
    env['PYTHONIOENCODING'] = 'utf-8'
    return env


def codex_command():
    override = os.environ.get('PHOTODESK_CODEX')
    if override:
        binary = shutil.which(override) or (override if Path(override).is_file() else None)
    elif sys.platform == 'win32':
        binary = shutil.which('codex.exe') or shutil.which('codex.cmd')
    else:
        binary = shutil.which('codex')
        if not binary and sys.platform == 'darwin' and Path('/opt/homebrew/bin/codex').is_file():
            binary = '/opt/homebrew/bin/codex'
    if not binary:
        raise RuntimeError('Codex bulunamadı. Codex CLI kurulu ve hesabına giriş yapılmış olmalı.')
    path = Path(binary).resolve()
    if sys.platform == 'win32' and path.suffix.lower() in ('.cmd', '.bat'):
        # npm's known JS entry point avoids cmd.exe quoting/injection entirely.
        entry = path.parent / 'node_modules/@openai/codex/bin/codex.js'
        node = path.parent / 'node.exe'
        node_path = str(node) if node.is_file() else shutil.which('node.exe')
        if not entry.is_file() or not node_path:
            raise RuntimeError('Codex npm başlatıcısı çözülemedi. Node.js ve Codex CLI kurulumunu kontrol et veya PHOTODESK_CODEX ile codex.exe yolunu belirt.')
        return [node_path, str(entry)]
    if sys.platform == 'win32' and path.suffix.lower() != '.exe':
        raise RuntimeError('Windows için yerel codex.exe veya npm codex.cmd gerekir; WSL kurulumu kullanılamaz.')
    return [str(path)]


def stop_process_tree(proc, timeout=5):
    if sys.platform == 'win32':
        if proc.poll() is not None:
            return
        tool = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/taskkill.exe'
        try:
            subprocess.run([str(tool), '/PID', str(proc.pid), '/T', '/F'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=15, check=False, creationflags=subprocess.CREATE_NO_WINDOW)
            proc.wait(timeout=timeout)
        except (OSError, subprocess.TimeoutExpired):
            raise RuntimeError('Codex process could not be stopped. End it in Task Manager before retrying.') from None
    else:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            pass
        # Kill stubborn descendants even if the group leader already exited.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait(timeout=timeout)
