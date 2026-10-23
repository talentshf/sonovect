"""Remove unused administration/interpreter code from immutable service images."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sysconfig

PROGRAMS = ('bash', 'bashbug', 'dash', 'sh', 'perl', 'tar', 'rmt', 'rmt-tar',
            'ldd', 'grep', 'egrep', 'fgrep',
            'diff', 'diff3', 'sdiff', 'cmp', 'chown', 'chgrp', 'sort', 'uniq',
            'unexpand', 'login', 'su', 'sulogin', 'runuser', 'chfn', 'chsh', 'gpasswd',
            'newgrp', 'passwd', 'chage', 'chpasswd', 'usermod', 'userdel',
            'groupadd', 'groupdel', 'groupmod', 'useradd', 'newusers', 'chroot')


def minimize():
    # Refuse an accidental checkout/host invocation before any filesystem change.
    expected = Path('/tmp/sonovect-os-security/source/recipe/minimize.py')
    if (os.getenv('SONOVECT_IMAGE_BUILD') != '1' or os.getuid() != 0
            or Path(__file__).resolve() != expected
            or not Path('/tmp/sonovect-os-security/packages.json').is_file()):
        raise RuntimeError('image_installation_only: use the project Dockerfile')
    removed = []
    def remove(path):
        if path.is_symlink():
            removed.append({'path': str(path), 'kind': 'symbolic-link'})
            path.unlink()
        elif path.is_file():
            removed.append({'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
            path.unlink()
    for directory in ('/usr/bin', '/usr/sbin', '/usr/libexec'):
        root = Path(directory)
        for name in PROGRAMS:
            remove(root / name)
        for path in root.glob('perl5.*'):
            remove(path)
    modules = Path('/usr/lib') / sysconfig.get_config_var('MULTIARCH') / 'perl-base'
    if modules.is_dir():
        for path in sorted(modules.rglob('*')):
            if path.is_file() or path.is_symlink():
                remove(path)
        shutil.rmtree(modules)
    for path in Path('/usr/lib').rglob('pam_userdb.so'):
        remove(path)
    for name in ('/etc/subuid', '/etc/subgid'):
        remove(Path(name))
    btmp = Path('/var/log/btmp')
    if btmp.is_file():
        btmp.chmod(0o600)
    receipt = {'schema_version': 1, 'profile': 'immutable-shell-free-service',
               'removed': removed, 'package_metadata_retained': True,
               'scope': 'Rebuild images to change software; Python model preparation remains supported. No login, shell, Perl, archive utility or system-administration contract.'}
    target = Path('/usr/local/share/sonovect-os-security/minimization.json')
    target.write_text(json.dumps(receipt, indent=2) + '\n')
    target.chmod(0o644)


if __name__ == '__main__':
    minimize()
