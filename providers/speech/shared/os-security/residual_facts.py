"""Bounded applicability evidence for distro source-package advisories."""
import ctypes
import hashlib
from pathlib import Path
import platform
import shutil
import os
import sqlite3
import struct
import subprocess


def undefined_symbols(path):
    """Read ELF64 dynamic symbol names; do not execute inspected programs."""
    data = Path(path).read_bytes()
    if data[:6] != b'\x7fELF\x02\x01':
        raise ValueError('Expected little-endian ELF64')
    offset = struct.unpack_from('<Q', data, 40)[0]
    size, count = struct.unpack_from('<HH', data, 58)
    sections = [struct.unpack_from('<IIQQQQIIQQ', data, offset + i * size) for i in range(count)]
    names = set()
    for section in sections:
        if section[1] != 11:
            continue
        strings = sections[section[6]]
        table = data[strings[4]:strings[4] + strings[5]]
        for pos in range(section[4], section[4] + section[5], section[9]):
            index, _, _, section_index, _, _ = struct.unpack_from('<IBBHQQ', data, pos)
            if section_index == 0 and index:
                names.add(table[index:table.index(b'\0', index)].decode())
    return sorted(names)


def aligned_new_probe():
    library = ctypes.CDLL('libstdc++.so.6')
    function = getattr(library, '_ZnwmSt11align_val_tRKSt9nothrow_t')
    function.argtypes = [ctypes.c_size_t, ctypes.c_size_t, ctypes.c_void_p]
    function.restype = ctypes.c_void_p
    nothrow = ctypes.addressof(ctypes.c_byte.in_dll(library, '_ZSt7nothrow'))
    maximum = ctypes.c_size_t(-1).value
    probes = [(maximum - 8, 32), (maximum, 8), (maximum, 32), (maximum, 1024),
              (maximum, 65536), (maximum - 1, 16), (maximum - 1025, 1024),
              (maximum - 1024, 1024), (maximum - 65536, 65536)]
    results = [function(size, alignment, nothrow) is None for size, alignment in probes]
    libc = ctypes.CDLL(None)
    libc.free.argtypes = [ctypes.c_void_p]
    ordinary = function(64, 64, nothrow)
    valid = ordinary is not None and ordinary % 64 == 0
    if ordinary:
        libc.free(ordinary)
    return {'oversized_cases': len(probes), 'all_rejected': all(results), 'ordinary_allocation_valid': valid}


def collect():
    commands = ('bash', 'sh', 'dash', 'perl', 'ldd', 'grep', 'egrep', 'fgrep', 'diff', 'diff3', 'cmp', 'sdiff',
                'tar', 'rmt', 'chown', 'chgrp', 'sort', 'uniq', 'unexpand',
                'login', 'su', 'chfn', 'chsh', 'sulogin', 'init', 'apt-key', 'getfacl', 'setfacl', 'chacl', 'getfattr', 'setfattr',
                'bzip2recover', 'nscd', 'systemd-oomd', 'systemd-journald',
                'newuidmap', 'newgidmap', 'pod2text', 'gcc', 'g++')
    modules = {'file_temp': [], 'pod_text': [], 'nscd': [], 'systemd_programs': [], 'pam_userdb': [], 'sqlite_zipfile': []}
    for directory in ('/usr', '/sbin', '/bin'):
        for path in Path(directory).rglob('*'):
            if not path.is_file():
                continue
            if path.name == 'Temp.pm' and path.parent.name == 'File':
                modules['file_temp'].append(str(path))
            if path.name == 'Text.pm' and path.parent.name == 'Pod':
                modules['pod_text'].append(str(path))
            if path.name == 'nscd':
                modules['nscd'].append(str(path))
            if path.name == 'pam_userdb.so':
                modules['pam_userdb'].append(str(path))
            if path.name == 'zipfile.so':
                modules['sqlite_zipfile'].append(str(path))
            if path.name in ('systemd', 'systemd-oomd', 'systemd-journald'):
                modules['systemd_programs'].append(str(path))
    dash = shutil.which('dash')
    dash_unicode = subprocess.check_output([dash, '-c', "printf '\\u0041'"]) if dash else None
    libraries = {}
    for name in ('libstdc++.so.6', 'libc.so.6', 'libsqlite3.so.0', 'libz.so.1'):
        path = next(Path('/usr/lib').rglob(name), None)
        if path:
            path = path.resolve()
            libraries[name] = {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    status = Path('/proc/self/status').read_text()
    command_paths = {}
    for name in commands:
        paths = [Path(directory) / name for directory in ('/usr/bin', '/usr/sbin', '/usr/libexec', '/bin', '/sbin')]
        command_paths[name] = sorted({str(path.resolve()) for path in paths if path.is_file() or path.is_symlink()})
    sqlite_library = ctypes.CDLL('libsqlite3.so.0')
    return {'architecture': platform.machine(), 'libc_runtime': platform.libc_ver(),
            'uid': os.getuid(), 'gid': os.getgid(),
            'effective_capabilities': next(line.split()[1] for line in status.splitlines() if line.startswith('CapEff:')),
            'no_new_privileges': next(line.split()[1] for line in status.splitlines() if line.startswith('NoNewPrivs:')),
            'sqlite_runtime': sqlite3.sqlite_version,
            'commands': command_paths,
            'sqlite_zipfile_export': hasattr(sqlite_library, 'sqlite3_zipfile_init'),
            'modules': {k: sorted(set(v)) for k, v in modules.items()},
            'dash_imports_fnmatch': bool(dash and 'fnmatch' in undefined_symbols(dash)),
            'dash_unicode_escape_supported': dash_unicode == b'A',
            'aligned_new': aligned_new_probe(), 'libraries': libraries,
            'compiler_headers_present': Path('/usr/include/c++').exists()}
