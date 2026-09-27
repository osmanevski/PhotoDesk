"""Use the installed Codex model catalogue; never invent effort support."""
from pathlib import Path
import json

DEFAULTS={'backend':'local','model':'gpt-6-astra','effort':'medium','layout':'auto','api_model':'','api_effort':'default'}
def catalog(path=None):
    path=Path(path) if path else Path.home()/'.codex/models_cache.json'
    try:
        models=json.loads(path.read_text()).get('models',[])
        result=[]
        for model in models:
            slug=model.get('slug','')
            if not slug.startswith('gpt-') or 'image' not in model.get('input_modalities',[]) or slug=='gpt-reserve':continue
            efforts=[x['effort'] for x in model.get('supported_reasoning_levels',[]) if isinstance(x,dict) and x.get('effort')]
            if not efforts:continue
            result.append({'id':slug,'name':model.get('display_name',slug),'efforts':efforts})
        if result:return result
    except (OSError,ValueError,TypeError):pass
    # This combination has been exercised successfully on this installation.
    return [{'id':'gpt-6-astra','name':'GPT-6-Astra','efforts':['medium']}]

def validate_settings(value,api_models=None):
    from local_engine import LAYOUTS
    value={k:value.get(k,v) for k,v in DEFAULTS.items()}
    if value['backend'] not in ['local','ai','openrouter']:raise ValueError('Geçersiz işleme yöntemi.')
    if value['layout'] not in LAYOUTS:raise ValueError('Geçersiz yerleşim.')
    models={m['id']:m for m in catalog()}
    if value['backend']=='ai' and value['model'] not in models:raise ValueError('Model yerel Codex listesinde yok. Codex model listesini yenile.')
    if value['backend']=='ai' and value['effort'] not in models[value['model']]['efforts']:raise ValueError('Seçilen model bu effort düzeyini desteklemiyor.')
    if value['backend']=='openrouter':
        api={m['id']:m for m in (api_models or [])}
        if value['api_model'] and value['api_model'] not in api:raise ValueError('OpenRouter model listesini yenile ve model seç.')
        if value['api_model'] and value['api_effort'] not in api[value['api_model']]['efforts']:raise ValueError('Bu API modeli seçilen effort düzeyini desteklemiyor.')
    return value
