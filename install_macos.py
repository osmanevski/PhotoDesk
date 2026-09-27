"""Install this project's launcher and isolated dependencies without changing originals."""
from pathlib import Path
import argparse,hashlib,json,os,plistlib,shlex,shutil,subprocess,sys

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--wheels');parser.add_argument('--skip-deps',action='store_true',help='Reuse an existing runtime');args=parser.parse_args()
    code=Path(__file__).resolve().parent
    runtime=Path.home()/'Library'/'Application Support'/'FotografMasasi'/'runtime'
    python=runtime/'bin/python'
    if args.skip_deps and not python.exists():raise SystemExit('No existing runtime. Run without --skip-deps first.')
    if not python.exists():subprocess.run([sys._base_executable,'-m','venv',str(runtime)],check=True)
    command=[str(python),'-m','pip','install','--disable-pip-version-check','-r',str(code/'requirements.txt')]
    if args.wheels:command += ['--no-index','--find-links',str(Path(args.wheels).resolve())]
    if not args.skip_deps:subprocess.run(command,check=True)
    app=Path.home()/'Applications'/'PhotoDesk.app'
    old=app.with_name('Fotoğraf Masası.app')
    if old.exists() and not app.exists():
        info_path=old/'Contents/Info.plist'
        if info_path.exists() and plistlib.loads(info_path.read_bytes()).get('CFBundleIdentifier')=='com.osmanevski.fotografmasasi':old.rename(app)
    contents=app/'Contents'
    (contents/'MacOS').mkdir(parents=True,exist_ok=True);(contents/'Resources').mkdir(exist_ok=True)
    icon_source=code/'static/AppIcon.icns'
    icon_name='AppIcon-'+hashlib.sha256(icon_source.read_bytes()).hexdigest()[:12]+'.icns'
    info={'CFBundleName':'PhotoDesk','CFBundleDisplayName':'PhotoDesk','CFBundleIdentifier':'com.osmanevski.fotografmasasi',
          'CFBundleVersion':'4','CFBundleShortVersionString':'1.3.0','CFBundleDevelopmentRegion':'en','CFBundleLocalizations':['en','tr'],'CFBundleExecutable':'FotografMasasi',
          'CFBundlePackageType':'APPL','CFBundleIconFile':icon_name,'LSUIElement':True,'NSHighResolutionCapable':True}
    with open(contents/'Info.plist','wb') as f:plistlib.dump(info,f)
    launch=contents/'MacOS'/'FotografMasasi'
    launch.write_text('#!/bin/zsh\nexec '+shlex.quote(str(python))+' '+shlex.quote(str(code/'launcher.py'))+'\n');launch.chmod(0o755)
    shutil.copy2(icon_source,contents/'Resources'/icon_name)
    app.touch()
    register=Path('/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister')
    if register.exists():subprocess.run([str(register),'-f',str(app)],check=True)
    desktop=Path.home()/'Desktop'/'PhotoDesk.app'
    if not desktop.exists() and not desktop.is_symlink():desktop.symlink_to(app,target_is_directory=True)
    if desktop.is_symlink() and desktop.resolve()==app:os.utime(desktop,follow_symlinks=False)
    legacy=desktop.with_name('Fotoğraf Masası.app')
    if legacy.is_symlink() and legacy.readlink() in (old,app):legacy.unlink()
    print(json.dumps({'app':str(app),'code':str(code),'runtime':str(runtime),'desktop':str(desktop)},ensure_ascii=False))

if __name__=='__main__':main()
