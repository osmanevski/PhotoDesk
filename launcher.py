"""One-click local launcher. No model call happens until the user starts a job."""
from pathlib import Path
import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from platform_support import (alert, child_options, data_dir, data_id,
                              instance_lock, launcher_environment, open_browser,
                              stop_process_tree)

HERE = Path(__file__).resolve().parent
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class HealthPending(RuntimeError):
    pass


def health(url, data):
    try:
        with OPENER.open(url + '/api/health', timeout=5) as response:
            value = json.load(response)
    except urllib.error.HTTPError:
        raise RuntimeError('Another application is using this PhotoDesk port.') from None
    except urllib.error.URLError as error:
        # A timeout must not be interpreted as an absent server.
        if isinstance(error.reason, ConnectionRefusedError):
            return False
        if isinstance(error.reason, TimeoutError):
            raise HealthPending('PhotoDesk is not responding yet; try again shortly.') from None
        raise RuntimeError('PhotoDesk health check failed; see server.log.') from None
    except TimeoutError:
        raise HealthPending('PhotoDesk is not responding yet; try again shortly.') from None
    if value.get('app') != 'fotograf-masasi' or value.get('data_id') != data_id(data):
        raise RuntimeError('This port is used by another app or PhotoDesk data folder. Choose another --port.')
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-open', action='store_true')
    parser.add_argument('--data', type=Path, default=data_dir())
    parser.add_argument('--port', type=int, default=8874)
    args = parser.parse_args()
    data = args.data.expanduser().resolve()
    data.mkdir(parents=True, exist_ok=True)
    url = f'http://127.0.0.1:{args.port}'
    with instance_lock(data / 'launcher.lock'):
        if not health(url, data):
            with (data / 'server.log').open('a', encoding='utf-8') as log:
                proc = subprocess.Popen([sys.executable, str(HERE / 'app.py'), '--data', str(data), '--port', str(args.port)],
                                        cwd=HERE, env=launcher_environment(), stdin=subprocess.DEVNULL,
                                        stdout=log, stderr=log, **child_options(detach=True))
            (data / 'server.pid').write_text(str(proc.pid), encoding='utf-8')
            try:
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    try:
                        if health(url, data):
                            break
                    except HealthPending:
                        pass
                    if proc.poll() is not None:
                        raise RuntimeError('Could not start PhotoDesk. Log: ' + str(data / 'server.log'))
                    time.sleep(.25)
                else:
                    raise RuntimeError('PhotoDesk startup timed out. Log: ' + str(data / 'server.log'))
            except Exception:
                if proc.poll() is None:
                    stop_process_tree(proc)
                raise
        if not args.no_open:
            open_browser(url)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        alert(str(error))
        sys.exit(1)
