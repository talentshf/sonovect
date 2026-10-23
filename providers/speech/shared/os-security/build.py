"""Build narrowly scoped Debian13 security backports, retaining their source."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import urllib.request

HERE = Path(__file__).resolve().parent
LOCK = json.loads((HERE / 'source-lock.json').read_text())
ROOT = Path('/tmp/sonovect-os-build')
OUT = Path('/os-security')
RUNTIME = {'libacl1', 'libncursesw6', 'libtinfo6', 'ncurses-base', 'ncurses-bin',
           'bsdutils', 'util-linux', 'mount', 'login', 'libblkid1', 'libmount1',
           'libuuid1', 'libsmartcols1', 'liblastlog2-2', 'libfdisk1'}


def run(*command, cwd=ROOT):
    subprocess.run(command, cwd=cwd, check=True)


def adjust_util_linux(directory):
    # Debian unstable moved packaging to debhelper14/debputy. Retain the exact
    # upstream code, adapting packaging to Debian13's supported debhelper13.
    debian = directory / 'debian'
    path = debian / 'control'
    original = path.read_text()
    text = original.replace(' debhelper (>= 14.1~),', ' debhelper (>= 13),')
    text = text.replace(' debhelper-compat (= 14),', ' debhelper-compat (= 13),')
    text = text.replace(' dh-package-notes,\n', '')
    text = text.replace(' dh-sequence-zz-debputy-rrr (>= 0.1.23~),\n', '')
    if text == original:
        raise RuntimeError('Unexpected util-linux packaging; review source lock')
    path.write_text(text)
    path = debian / 'rules'
    text = path.read_text().replace('include /usr/share/debhelper/dh_package_notes/package-notes.mk\n', '')
    text += ('\noverride_dh_gencontrol:\n'
             '\tdh_gencontrol -pbsdutils -- -v1:2.42.4-1~sonovect13.1\n'
             '\tdh_gencontrol -plogin -- -v1:4.16.0-2+really2.42.4-1~sonovect13.1\n'
             '\tdh_gencontrol --remaining-packages\n')
    path.write_text(text)
    # debputy had specified these privilege bits. Service images deliberately
    # omit all setuid/setgid bits; they are never a system-login environment.
    (debian / 'debputy.manifest').unlink()


def prepare():
    ROOT.mkdir()
    (OUT / 'runtime').mkdir(parents=True)
    (OUT / 'source').mkdir()
    for name, spec in LOCK['components'].items():
        for item in spec['files']:
            target = ROOT / item['name']
            with urllib.request.urlopen(item['url'], timeout=300) as response, target.open('xb') as output:
                shutil.copyfileobj(response, output)
            if target.stat().st_size != item['size'] or hashlib.sha256(target.read_bytes()).hexdigest() != item['sha256']:
                raise RuntimeError('Source integrity mismatch: ' + item['name'])
        descriptor = next(x['name'] for x in spec['files'] if x['name'].endswith('.dsc'))
        run('dpkg-source', '-x', descriptor)
        directory = ROOT / spec['directory']
        if name == 'util-linux':
            adjust_util_linux(directory)
        path = directory / 'debian/changelog'
        path.write_text(f"{name} ({spec['version']}) trixie; urgency=high\n\n"
                        '  * Rebuild fixed upstream code for the Sonovect Debian13 image.\n\n'
                        ' -- Sonovect contributors <noreply@example.invalid>  Tue, 20 Oct 2026 13:00:00 +0000\n\n'
                        + path.read_text())
        # Corresponding source is generated before compilation changes files.
        run('dpkg-source', '-b', spec['directory'])


def build(name):
    env = dict(os.environ, DEB_BUILD_OPTIONS='parallel=4 nocheck nodoc',
               DEB_BUILD_PROFILES='nocheck nodoc pkg.util-linux.noverity nobiarch')
    subprocess.run(['dpkg-buildpackage', '-b', '-uc', '-us', '-d', '-j4'],
                   cwd=ROOT / LOCK['components'][name]['directory'], env=env, check=True)


def finalize():
    selected = set()
    packages = []
    for path in sorted(ROOT.glob('*.deb')):
        name = subprocess.check_output(['dpkg-deb', '-f', str(path), 'Package'], text=True).strip()
        if name in RUNTIME:
            shutil.copy2(path, OUT / 'runtime' / path.name)
            selected.add(name)
            packages.append({'package': name, 'file': path.name,
                             'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    if selected != RUNTIME:
        raise RuntimeError('Incomplete runtime backports: ' + str(RUNTIME - selected))
    for path in ROOT.iterdir():
        if path.is_file() and ('.orig.' in path.name or '~sonovect13.1.dsc' in path.name
                               or '~sonovect13.1.debian.tar.' in path.name):
            shutil.copy2(path, OUT / 'source' / path.name)
    shutil.copytree(HERE, OUT / 'source' / 'recipe')
    (OUT / 'packages.json').write_text(json.dumps(packages, indent=2) + '\n')
    (OUT / 'build-packages.txt').write_text(subprocess.check_output(
        ['dpkg-query', '-W', '-f=${binary:Package} ${Version}\n'], text=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'build', 'finalize'))
    parser.add_argument('component', nargs='?', choices=tuple(LOCK['components']))
    args = parser.parse_args()
    if args.action == 'prepare':
        prepare()
    elif args.action == 'build':
        if args.component is None:
            parser.error('build requires a component')
        build(args.component)
    else:
        finalize()
