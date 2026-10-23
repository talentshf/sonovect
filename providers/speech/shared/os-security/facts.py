"""Inspect exact runtime package/file evidence, without media or credentials."""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from residual_facts import collect as residual_evidence


def facts():
    raw = subprocess.check_output(['dpkg-query', '-W', '-f=${binary:Package}\t${Version}\t${source:Package}\t${source:Version}\n'], text=True)
    packages = [dict(zip(('package', 'version', 'source', 'source_version'), line.split('\t'))) for line in raw.splitlines()]
    modules, homed, setid = [], [], []
    for directory, _, names in os.walk('/usr'):
        for name in names:
            path = Path(directory) / name
            if name == 'Tar.pm' and path.parent.name == 'Archive':
                modules.append(str(path))
            if name == 'systemd-homed':
                homed.append(str(path))
            if not path.is_symlink() and path.stat().st_mode & 0o6000:
                setid.append(str(path))
    files = {}
    for name in ('mount', 'nsenter', 'infocmp'):
        path = shutil.which(name)
        files[name] = {'path': path, 'sha256': hashlib.sha256(Path(path).read_bytes()).hexdigest() if path else None}
    return {'schema_version': 1, 'packages': packages, 'residual': residual_evidence(), 'archive_tar_paths': sorted(set(modules)),
            'systemd_homed_paths': sorted(set(homed)), 'files': files, 'setid_paths': sorted(setid)}


def verify(value):
    expected = {'util-linux': '2.42.4-1~sonovect13.1', 'acl': '2.4.0-1~sonovect13.1',
                'ncurses': '6.6+20260608-2~sonovect13.1', 'glibc': '2.43-7~sonovect13.1',
                'sqlite3': '3.53.4-2~sonovect13.1', 'zlib': '1:1.3.dfsg+really1.3.1-1+sonovect13.1'}
    for source, version in expected.items():
        matching = [p for p in value['packages'] if p['source'] == source]
        if not matching or any(p['source_version'] != version for p in matching):
            raise RuntimeError('Runtime security source version mismatch: ' + source)
    if value['archive_tar_paths'] or value['systemd_homed_paths'] or value['setid_paths']:
        raise RuntimeError('Previously absent vulnerable component is present; review applicability')
    for library in ('libacl.so.1', 'libmount.so.1', 'libtinfo.so.6', 'libncursesw.so.6'):
        ctypes.CDLL(library)
    audit = subprocess.check_output(['dpkg', '--audit'], text=True)
    if audit.strip():
        raise RuntimeError('Incomplete OS package installation')
    for command in (['mount', '--version'], ['nsenter', '--version'], ['infocmp', '-V']):
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL)
    for command in ('sh', 'bash', 'dash', 'perl', 'ldd', 'grep', 'egrep', 'fgrep', 'tar', 'diff', 'login', 'su'):
        if value['residual']['commands'].get(command):
            raise RuntimeError('Unexpected mutable administration runtime: ' + command)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    value = facts()
    if args.verify:
        verify(value)
    print(json.dumps(value, indent=2))
