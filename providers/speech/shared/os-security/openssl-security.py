"""Rebuild Debian OpenSSL with exact official fixes and their regression tests."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import urllib.request

HERE = Path(__file__).resolve().parent
LOCK = json.loads((HERE / 'openssl-source-lock.json').read_text())
ROOT = Path('/tmp/sonovect-openssl-build')
OUT = Path('/os-security')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ROOT.mkdir()
    for item in LOCK['files']:
        path = ROOT / item['name']
        with urllib.request.urlopen(item['url'], timeout=300) as response, path.open('xb') as target:
            shutil.copyfileobj(response, target)
        if path.stat().st_size != item['size'] or digest(path) != item['sha256']:
            raise RuntimeError('OpenSSL source integrity mismatch: ' + path.name)
    descriptor = next(item['name'] for item in LOCK['files'] if item['name'].endswith('.dsc'))
    subprocess.run(['dpkg-source', '-x', descriptor], cwd=ROOT, check=True)
    source = ROOT / LOCK['directory']
    series = source / 'debian/patches/series'
    for item in LOCK['patches']:
        patch = HERE / 'openssl-patches' / item['file']
        if digest(patch) != item['patch_sha256']:
            raise RuntimeError('OpenSSL official patch integrity mismatch')
        if item.get('applied_file'):
            patch = HERE / 'openssl-patches' / item['applied_file']
            if digest(patch) != item['applied_sha256']:
                raise RuntimeError('OpenSSL backport context integrity mismatch')
        shutil.copyfile(patch, source / 'debian/patches' / item['file'])
        with series.open('a') as stream:
            stream.write('\n' + item['file'] + '\n')
    subprocess.run(['dpkg-source', '--before-build', '.'], cwd=source, check=True)
    changelog = source / 'debian/changelog'
    changelog.write_text(f"openssl ({LOCK['version']}) trixie; urgency=high\n\n"
        '  * Apply official November 2026 security fixes and regression tests.\n\n'
        ' -- Sonovect contributors <noreply@example.invalid>  Sun, 15 Nov 2026 12:00:00 +0000\n\n'
        + changelog.read_text())
    # Preserve a normal quilt source package containing all modifications.
    subprocess.run(['dpkg-source', '-b', LOCK['directory']], cwd=ROOT, check=True)
    log = OUT / 'source/openssl-build.log'
    # Do not use nocheck: the patched upstream tests run against these binaries.
    env = dict(os.environ, DEB_BUILD_OPTIONS='parallel=6', DEB_BUILD_PROFILES='noudeb')
    with log.open('w') as stream:
        result = subprocess.run(['dpkg-buildpackage', '-B', '-uc', '-us', '-d', '-j6'],
            cwd=source, env=env, stdout=stream, stderr=subprocess.STDOUT)
    if result.returncode:
        print('\n'.join(log.read_text().splitlines()[-100:]), flush=True)
        raise RuntimeError('OpenSSL build or upstream tests failed')
    records = json.loads((OUT / 'packages.json').read_text())
    selected = set()
    binary_hashes = {}
    for path in sorted(ROOT.glob('*.deb')):
        name = subprocess.check_output(['dpkg-deb', '-f', str(path), 'Package'], text=True).strip()
        if name not in {'openssl', 'libssl3t64', 'openssl-provider-legacy'}:
            continue
        selected.add(name)
        shutil.copyfile(path, OUT / 'runtime' / path.name)
        records.append(dict(package=name, file=path.name, sha256=digest(path)))
        unpacked = ROOT / ('unpacked-' + name)
        subprocess.run(['dpkg-deb', '-x', str(path), str(unpacked)], check=True)
        for library in unpacked.rglob('*.so*'):
            if library.is_file() and not library.is_symlink():
                binary_hashes['/' + str(library.relative_to(unpacked))] = digest(library)
    if selected != {'openssl', 'libssl3t64', 'openssl-provider-legacy'}:
        raise RuntimeError('OpenSSL runtime bundle incomplete')
    libraries = ROOT / 'unpacked-libssl3t64/usr/lib/x86_64-linux-gnu'
    peer = subprocess.check_output(['python', str(HERE / 'openssl-peer-probe.py')],
        env=dict(os.environ, LD_LIBRARY_PATH=str(libraries)), text=True)
    peer_results = json.loads(peer)
    if peer_results != {'127.0.0.1': True, '::1': True}:
        raise RuntimeError('OpenSSL actual-library IPv4/IPv6 peer regression')
    for path in ROOT.iterdir():
        if path.is_file() and ('.orig.' in path.name or ('sonovect13.' in path.name
                and (path.name.endswith('.dsc') or '.debian.tar.' in path.name))):
            shutil.copyfile(path, OUT / 'source' / path.name)
    for name in ('openssl-security.py', 'openssl-source-lock.json', 'openssl-peer-probe.py'):
        shutil.copyfile(HERE / name, OUT / 'source/recipe' / name)
    shutil.copytree(HERE / 'openssl-patches', OUT / 'source/recipe/openssl-patches')
    (OUT / 'source/openssl-verification.json').write_text(json.dumps(dict(
        source_version=LOCK['version'], lock_sha256=digest(HERE / 'openssl-source-lock.json'),
        upstream_tests_passed=True, peer_probe=peer_results,
        patches=LOCK['patches'], libraries=binary_hashes), indent=2) + '\n')
    (OUT / 'packages.json').write_text(json.dumps(records, indent=2) + '\n')
    (OUT / 'build-packages.txt').write_text(subprocess.check_output(
        ['dpkg-query', '-W', '-f=${binary:Package} ${Version}\n'], text=True))


if __name__ == '__main__':
    main()
