"""Build English UI assets from the shared Turkish source and reviewed catalog.

No live DOM translation: user names, notes, image metadata and input values are
inserted only at runtime and are never passed through this build step.
"""
from pathlib import Path
import argparse
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parents[1]

def build(check=False):
    catalog = json.loads((ROOT / 'locales/en.json').read_text())
    pattern = re.compile('|'.join(re.escape(k) for k in sorted(catalog, key=len, reverse=True)))
    for name in ('app.js', 'index.html'):
        source = (ROOT / 'locales/tr' / name).read_text()
        if name == 'index.html':
            for asset in ('icon.svg','favicon.png'):
                digest=hashlib.sha256((ROOT/'static'/asset).read_bytes()).hexdigest()[:12]
                source=source.replace('/static/'+asset,'/static/'+asset+'?v='+digest)
        english = pattern.sub(lambda m: catalog[m.group()], source)
        if name == 'index.html': english = english.replace('lang="tr"', 'lang="en"')
        for target, content in [(ROOT/'static'/name, english), (ROOT/'static'/name.replace('.', '.tr.', 1), source)]:
            if check:
                if not target.exists() or target.read_text() != content: raise SystemExit(f'Stale locale asset: {target.name}')
            else: target.write_text(content)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--check', action='store_true')
    build(parser.parse_args().check)
