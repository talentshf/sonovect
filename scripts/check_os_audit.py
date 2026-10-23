"""Retain raw OS findings and fail on unreviewed matches at any severity or drift."""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXED = {
    'CVE-2026-76642': ('util-linux', '2.42.4-1~sonovect13.1'),
    'CVE-2026-78408': ('util-linux', '2.42.4-1~sonovect13.1'),
    'CVE-2026-78409': ('util-linux', '2.42.4-1~sonovect13.1'),
    'CVE-2026-78410': ('util-linux', '2.42.4-1~sonovect13.1'),
    'CVE-2026-54369': ('acl', '2.4.0-1~sonovect13.1'),
    'CVE-2025-69720': ('ncurses', '6.6+20260608-2~sonovect13.1'),
}
ABSENT = {'CVE-2026-16742': ('systemd', 'systemd_homed_paths'),
          'CVE-2026-9538': ('perl', 'archive_tar_paths')}
ROLES = ('core', 'media-worker', 'provider', 'segmentation', 'asr', 'sound', 'events', 'native', 'vocal', 'measurements')
POLICY = json.loads((ROOT / 'providers/speech/shared/os-security/advisory-policy.json').read_text())['records']


def lower_disposition(item, package, facts):
    rule = POLICY.get(item['id'])
    if (not rule or rule['severity'] != item['severity'] or rule['source'] != package.get('source')
            or rule['source_version'] != package.get('source_version')):
        return None
    evidence, proof = facts.get('residual', {}), rule['proof']
    kind = proof['type']
    valid = False
    if kind == 'fixed-source':
        valid = True
    elif kind == 'absence':
        valid = (all(key in evidence.get('commands', {}) and not evidence['commands'][key] for key in proof.get('commands', []))
                 and all(key in evidence.get('modules', {}) and not evidence['modules'][key] for key in proof.get('modules', [])))
        if 'sqlite_zipfile' in proof.get('modules', []):
            valid = valid and evidence.get('sqlite_zipfile_export') is False
    elif kind == 'compiler-header':
        valid = evidence.get('compiler_headers_present') is False
    elif kind == 'aligned-new':
        probe = evidence.get('aligned_new', {})
        valid = (evidence.get('architecture') == 'x86_64' and probe.get('oversized_cases') == 9
                 and probe.get('all_rejected') is True and probe.get('ordinary_allocation_valid') is True
                 and evidence.get('libraries', {}).get('libstdc++.so.6', {}).get('sha256') == proof['library_sha256'])
    elif kind == 'service-boundary':
        commands = evidence.get('commands', {})
        valid = (evidence.get('uid') == 10001 and evidence.get('effective_capabilities') == '0000000000000000'
                 and evidence.get('no_new_privileges') == '1' and facts.get('setid_paths') == []
                 and all(key in commands and not commands[key]
                         for key in ('sh', 'bash', 'dash', 'perl', *proof.get('commands', []))))
    return {**item, 'status': rule['status'], 'reason': rule['reason'], 'references': rule['references']} if valid else None


def package_version(package):
    # Trivy separates the Debian epoch and revision from the upstream version.
    version = package['Version']
    if package.get('Release'):
        version += '-' + package['Release']
    if package.get('Epoch'):
        version = str(package['Epoch']) + ':' + version
    return version


def classify(audit, facts):
    os_info = audit.get('Metadata', {}).get('OS', {})
    results = [r for r in audit.get('Results', []) if r.get('Type') == 'debian']
    if os_info.get('Family') != 'debian' or not str(os_info.get('Name', '')).startswith('13.') or not results:
        raise ValueError('Expected an actual Debian13 OS-package scan')
    inventory = {p['package'].split(':')[0]: p for p in facts['packages']}
    scanned = {p['Name']: p for r in results for p in r.get('Packages', [])}
    # Bind the scan to the observed inventory, including epochs and architecture.
    if len(scanned) < 50 or set(scanned) != set(inventory):
        raise ValueError('OS scan/inventory coverage mismatch')
    if any(package_version(scanned[name]) != p['version'] for name, p in inventory.items()):
        raise ValueError('OS scan/inventory version mismatch')
    reviewed, unresolved, residual, reviewed_lower, unresolved_lower = [], [], [], [], []
    for r in results:
        for v in r.get('Vulnerabilities', []):
            item = {'id': v['VulnerabilityID'], 'package': v['PkgName'],
                    'version': v['InstalledVersion'], 'severity': v['Severity']}
            if v['Severity'] not in ('HIGH', 'CRITICAL'):
                assessed = lower_disposition(item, inventory.get(v['PkgName'], {}), facts)
                residual.append(assessed or item)
                (reviewed_lower if assessed else unresolved_lower).append(assessed or item)
                continue
            package = inventory.get(v['PkgName'], {})
            fixed = FIXED.get(v['VulnerabilityID'])
            absent = ABSENT.get(v['VulnerabilityID'])
            if fixed and package.get('source') == fixed[0] and package.get('source_version') == fixed[1]:
                item.update(status='fixed-by-source-backport', source=fixed[0], source_version=fixed[1])
                reviewed.append(item)
            elif (absent and package.get('source') == absent[0]
                  and facts.get(absent[1]) == [] and facts.get('setid_paths') == []
                  and package.get('source_version') == {'systemd': '257.13-1~deb13u1', 'perl': '5.40.1-6+deb13u1'}[absent[0]]):
                item.update(status='not_affected', justification='vulnerable_code_not_present',
                            evidence_field=absent[1])
                reviewed.append(item)
            else:
                unresolved.append(item)
    return {'raw_matches': len(reviewed) + len(unresolved) + len(residual),
            'reviewed_high_critical': reviewed, 'unresolved_high_critical': unresolved,
            'reviewed_lower_severity': reviewed_lower, 'unresolved_lower_severity': unresolved_lower,
            'residual_lower_severity': residual,
            'scope': 'OS package scope only; raw matches remain visible. Native wheel libraries and Python audit are separate.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('receipt', type=Path)
    parser.add_argument('facts', type=Path)
    parser.add_argument('--role', required=True, choices=ROLES)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = classify(json.loads(args.receipt.read_text()), json.loads(args.facts.read_text()))
    result['role'] = args.role
    content = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        args.output.write_text(content)
    else:
        print(content, end='')
    return bool(result['unresolved_high_critical'] or result['unresolved_lower_severity'])


if __name__ == '__main__':
    raise SystemExit(main())
