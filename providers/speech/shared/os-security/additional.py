"""Build exact-source library fixes without replacing the Debian distribution."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import urllib.request

HERE = Path(__file__).resolve().parent
LOCK = json.loads((HERE / 'additional-source-lock.json').read_text())
ROOT = Path('/tmp/sonovect-library-build')
OUT = Path('/os-security')
PACKAGES = {'libc6', 'libc-bin', 'libc-gconv-modules-extra', 'libsqlite3-0', 'zlib1g'}


def prepare():
    ROOT.mkdir()
    for name, spec in LOCK['components'].items():
        for item in spec['files']:
            path = ROOT / item['name']
            with urllib.request.urlopen(item['url'], timeout=300) as response, path.open('xb') as target:
                shutil.copyfileobj(response, target)
            if path.stat().st_size != item['size'] or hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
                raise RuntimeError('Source integrity mismatch: ' + path.name)
        descriptor = next(x['name'] for x in spec['files'] if x['name'].endswith('.dsc'))
        subprocess.run(['dpkg-source', '-x', descriptor], cwd=ROOT, check=True)
        directory = ROOT / spec['directory']
        if name == 'glibc':
            # The upstream library supports this compiler; use the stable
            # distribution's GCC14 instead of unstable packaging's GCC15.
            changed = []
            for candidate in (directory / 'debian').rglob('*'):
                if not candidate.is_file():
                    continue
                try:
                    original = candidate.read_text()
                except UnicodeDecodeError:
                    continue
                updated = original.replace('gcc-15', 'gcc-14').replace('g++-15', 'g++-14')
                if updated != original:
                    candidate.write_text(updated)
                    changed.append(str(candidate.relative_to(directory)))
            if not changed:
                raise RuntimeError('Unexpected glibc compiler packaging; review source lock')
            (directory / 'debian/sonovect-build.json').write_text(json.dumps({
                'compiler': 'Debian13 GCC14', 'packaging_files_adjusted': changed,
                'upstream_code_changed': False}, indent=2) + '\n')
        if name == 'zlib':
            patch = HERE / 'zlib-crc.patch'
            if hashlib.sha256(patch.read_bytes()).hexdigest() != LOCK['patches']['zlib']['sha256']:
                raise RuntimeError('Upstream patch integrity mismatch')
            target = directory / 'debian/patches/sonovect-crc-negative-length.patch'
            shutil.copy2(patch, target)
            series = directory / 'debian/patches/series'
            with series.open('a') as stream:
                stream.write('\nsonovect-crc-negative-length.patch\n')
            subprocess.run(['dpkg-source', '--before-build', '.'], cwd=directory, check=True)
        path = directory / 'debian/changelog'
        path.write_text(f"{name} ({spec['version']}) trixie; urgency=high\n\n"
                        '  * Rebuild fixed library sources for the Sonovect Debian13 container.\n\n'
                        ' -- Sonovect contributors <noreply@example.invalid>  Tue, 20 Oct 2026 15:00:00 +0000\n\n'
                        + path.read_text())
        subprocess.run(['dpkg-source', '-b', spec['directory']], cwd=ROOT, check=True)


def build(name):
    env = dict(os.environ, DEB_BUILD_OPTIONS='parallel=6 nocheck nodoc',
               DEB_BUILD_PROFILES='nocheck nodoc noudeb nobiarch')
    subprocess.run(['dpkg-buildpackage', '-B', '-uc', '-us', '-d', '-j6'],
                   cwd=ROOT / LOCK['components'][name]['directory'], env=env, check=True)


def finalize():
    selected = set()
    records = json.loads((OUT / 'packages.json').read_text())
    for path in sorted(ROOT.glob('*.deb')):
        name = subprocess.check_output(['dpkg-deb', '-f', str(path), 'Package'], text=True).strip()
        if name in PACKAGES:
            shutil.copy2(path, OUT / 'runtime' / path.name)
            selected.add(name)
            records.append({'package': name, 'file': path.name,
                            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    if not {'libc6', 'libc-bin', 'libsqlite3-0', 'zlib1g'} <= selected:
        raise RuntimeError('Missing rebuilt runtime library')
    for path in ROOT.iterdir():
        if path.is_file() and ('.orig.' in path.name or ('sonovect13.' in path.name and
                               (path.name.endswith('.dsc') or '.debian.tar.' in path.name))):
            shutil.copy2(path, OUT / 'source' / path.name)
    for name in ['additional.py', 'additional-source-lock.json', 'zlib-crc.patch']:
        shutil.copy2(HERE / name, OUT / 'source/recipe' / name)
    (OUT / 'packages.json').write_text(json.dumps(records, indent=2) + '\n')
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
        if not args.component:
            parser.error('build requires component')
        build(args.component)
    else:
        finalize()
