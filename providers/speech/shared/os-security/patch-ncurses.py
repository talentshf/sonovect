"""Use an explicit staging output for Debian's extra terminfo definitions."""
from pathlib import Path
import subprocess

root = Path('/tmp/sonovect-os-build')
path = root / 'ncurses-6.6+20260608/debian/rules'
original = path.read_text()
text = original.replace('tic -x debian/$$ti.ti', 'tic -o $(fulltempdir)/usr/share/terminfo -x debian/$$ti.ti')
if text == original:
    raise RuntimeError('Unexpected ncurses packaging; review staging rule')
path.write_text(text)
# Keep the complete corresponding source for this packaging adjustment.
subprocess.run(['dpkg-source', '-b', 'ncurses-6.6+20260608'], cwd=root, check=True)
