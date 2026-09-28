"""Start using the installed runtime; no activation or shell wrapper required."""
from pathlib import Path
import subprocess
import sys
from platform_support import runtime_python

if __name__ == '__main__':
    python = runtime_python()
    if not python.is_file():
        raise SystemExit('Run install.py first to create the PhotoDesk runtime.')
    raise SystemExit(subprocess.call([str(python), str(Path(__file__).resolve().with_name('launcher.py')), *sys.argv[1:]]))
