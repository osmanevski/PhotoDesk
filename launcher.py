"""One-click local launcher. No model call happens until the user starts a job."""
from pathlib import Path
import fcntl,json,os,subprocess,sys,time,urllib.request

HERE=Path(__file__).resolve().parent
DATA=Path.home()/'Library'/'Application Support'/'FotografMasasi'
URL='http://127.0.0.1:8874'

def health():
    try:
        with urllib.request.urlopen(URL+'/api/health',timeout=1) as r:
            data=json.load(r)
        if data.get('app')!='fotograf-masasi':raise RuntimeError('Another application is using port 8874.')
        return True
    except OSError:return False

def main():
    DATA.mkdir(parents=True,exist_ok=True)
    with open(DATA/'launcher.lock','w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if not health():
            env=os.environ.copy();env['PATH']='/opt/homebrew/bin:/usr/local/bin:'+str(Path.home()/'.local/bin')+':'+env.get('PATH','/usr/bin:/bin')
            env['PYTHONUNBUFFERED']='1'
            with open(DATA/'server.log','a') as log:
                proc=subprocess.Popen([sys.executable,str(HERE/'app.py'),'--data',str(DATA)],cwd=HERE,env=env,
                                      stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
                (DATA/'server.pid').write_text(str(proc.pid))
            for _ in range(80):
                if health():break
                if proc.poll() is not None:raise RuntimeError('Could not start PhotoDesk. Log: '+str(DATA/'server.log'))
                time.sleep(.25)
            else:raise RuntimeError('PhotoDesk startup timed out. Log: '+str(DATA/'server.log'))
        if '--no-open' not in sys.argv:subprocess.run(['open',URL],check=True)

if __name__=='__main__':
    try:main()
    except Exception as e:
        print(str(e),file=sys.stderr)
        text=str(e).replace('\\','\\\\').replace('"','\\"').replace('\n',' ')
        subprocess.run(['osascript','-e','display alert "PhotoDesk" message "'+text+'" as critical'])
        sys.exit(1)
