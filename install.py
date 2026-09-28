"""Install one shared codebase into an isolated, per-user Python runtime."""
from pathlib import Path
import argparse
import subprocess
import sys
from platform_support import runtime_python


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--wheels', help='Install offline from this wheel directory')
    parser.add_argument('--skip-deps', action='store_true', help='Reuse an existing runtime')
    args = parser.parse_args()
    code = Path(__file__).resolve().parent
    if sys.version_info < (3, 11):
        raise SystemExit('PhotoDesk requires Python 3.11 or newer (3.12 recommended).')
    if sys.platform == 'darwin':
        subprocess.run([sys.executable, str(code / 'install_macos.py'), *sys.argv[1:]], check=True)
        return
    if sys.platform == 'win32' and 'windowsapps' in str(Path(sys._base_executable)).lower():
        raise SystemExit('Use Python from python.org. Microsoft Store Python path virtualization is not supported.')
    python = runtime_python()
    if args.skip_deps and not python.is_file():
        raise SystemExit('No existing runtime. Run without --skip-deps first.')
    if not python.is_file():
        subprocess.run([sys._base_executable, '-m', 'venv', str(python.parent.parent)], check=True)
    if not args.skip_deps:
        command = [str(python), '-m', 'pip', 'install', '--disable-pip-version-check', '-r', str(code / 'requirements.txt')]
        if args.wheels:
            command += ['--no-index', '--find-links', str(Path(args.wheels).resolve())]
        subprocess.run(command, check=True)
    print('PhotoDesk installed. Start from this folder: ' + ('py start.py' if sys.platform == 'win32' else 'python3 start.py'))


if __name__ == '__main__':
    main()
