"""Translate application-owned messages only; never rewrite user data."""
from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parent
MESSAGES = json.loads((ROOT / 'locales/server.en.json').read_text(encoding='utf-8'))
PATTERN = re.compile('|'.join(re.escape(k) for k in sorted(MESSAGES, key=len, reverse=True)))

def translate(message, language='en'):
    if language == 'tr' or not isinstance(message, str):
        return message
    return PATTERN.sub(lambda m: MESSAGES[m.group()], message)

def localize_response(data, language):
    """Only transient status/error fields, never stored names, notes or paths."""
    if isinstance(data, dict):
        data = dict(data)
        for key in ('error', 'message'):
            if key in data: data[key] = translate(data[key], language)
        if 'errors' in data: data['errors'] = [translate(e, language) for e in data['errors']]
        if 'job' in data: data['job'] = localize_response(data['job'], language)
        if 'layouts' in data: data['layouts'] = {k: translate(v, language) for k,v in data['layouts'].items()}
    return data
