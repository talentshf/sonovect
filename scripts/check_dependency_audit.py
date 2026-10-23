"""Classify an unmodified pip-audit JSON receipt against exact reviewed scopes.

Unknown findings, skipped packages and version/platform/role drift fail closed.
The raw scanner result stays visible; this is not a claim of zero findings.
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def classify(audit, statements, *, role, platform):
    reviewed, unresolved, skipped = [], [], []
    seen = set()
    for package in audit['dependencies']:
        if package.get('skip_reason'):
            skipped.append({'package': package['name'], 'reason': package['skip_reason']})
        for vulnerability in package.get('vulns', []):
            ids = {vulnerability['id'], *vulnerability.get('aliases', [])}
            key = (package['name'], tuple(sorted(i for i in ids if i.startswith('CVE-'))) or vulnerability['id'])
            if key in seen:
                continue
            seen.add(key)
            match = next((s for s in statements if s['id'] in ids
                          and s['package'] == package['name']
                          and s['version'] == package['version'].split('+')[0]
                          and s['platform'] == platform and role in s['roles']
                          and s['status'] == 'not_affected'), None)
            item = {'package': package['name'], 'version': package['version'], 'ids': sorted(ids)}
            if match:
                item.update({'status': match['status'], 'justification': match['justification'],
                             'impact_statement': match['impact_statement'], 'references': match['references']})
                reviewed.append(item)
            else:
                unresolved.append(item)
    return {'role': role, 'platform': platform, 'raw_package_advisory_pairs': len(seen),
            'reviewed_not_affected': reviewed, 'unresolved': unresolved, 'skipped': skipped}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('receipt', type=Path)
    parser.add_argument('--role', required=True)
    parser.add_argument('--platform', required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    dispositions = json.loads((ROOT/'docs/security/dependency-dispositions.json').read_text())
    result = classify(json.loads(args.receipt.read_text()), dispositions['statements'],
                      role=args.role, platform=args.platform)
    content = json.dumps(result, ensure_ascii=False, indent=2)+'\n'
    if args.output:
        args.output.write_text(content)
    else:
        print(content, end='')
    return bool(result['unresolved'] or result['skipped'])


if __name__ == '__main__':
    raise SystemExit(main())
