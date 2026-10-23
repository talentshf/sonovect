#!/bin/sh
set -eu
cd /tmp/sonovect-os-security
python - <<'CHECK'
import hashlib, json
from pathlib import Path
for item in json.load(open('packages.json')):
    path = Path('runtime') / item['file']
    if path.name != item['file'] or hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
        raise RuntimeError('Backport integrity mismatch')
CHECK
apt-get update
apt-get install -y --no-install-recommends ./runtime/*.deb
apt-get check
# Preserve exact corresponding source and build inventory with the binaries.
mkdir -p /usr/local/share/sonovect-os-security
cp -a source packages.json build-packages.txt /usr/local/share/sonovect-os-security/
find /usr/local/share/sonovect-os-security -type d -exec chmod 755 '{}' +
find /usr/local/share/sonovect-os-security -type f -exec chmod 644 '{}' +
# A model-serving image has no need to acquire another user's privileges.
find /usr/bin /usr/sbin /usr/lib -xdev -type f -perm /6000 -exec chmod a-s '{}' +
python source/recipe/minimize.py
python source/recipe/facts.py --verify
rm -rf /var/lib/apt/lists/* /tmp/sonovect-os-security
