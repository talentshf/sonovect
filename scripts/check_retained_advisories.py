"""Require renewed review when an accepted upstream advisory changes.

This is an explicit release/maintenance check, not a scheduled monitor or a
replacement for actual-image package scans. It never rewrites the baseline.
"""
import argparse
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / 'providers/speech/shared/os-security/advisory-policy.json'
BASELINE = ROOT / 'docs/security/retained-advisories.json'


class AdvisoryText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.ignored = 0

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style'}: self.ignored += 1

    def handle_endtag(self, tag):
        if tag in {'script', 'style'}: self.ignored = max(0, self.ignored - 1)

    def handle_data(self, value):
        if not self.ignored: self.parts.append(value)


def page_digest(identifier, content):
    parser = AdvisoryText()
    parser.feed(content.decode('utf-8', errors='strict'))
    text = re.sub(r'\s+', ' ', ' '.join(parser.parts)).strip()
    # Drop the site's search/navigation footer but preserve all advisory text,
    # distribution tables and upstream notes. Refuse error/login/truncated pages.
    text = text.split('Search for package or bug name:', 1)[0].strip()
    if not (text.count(identifier) >= 2 and 'Vulnerable and fixed packages' in text
            and 'Fixed Version' in text and 'Notes' in text and len(text) >= 350):
        raise ValueError('incomplete_advisory_page:' + identifier)
    return hashlib.sha256(text.encode()).hexdigest()


def assess(policy, baseline, pages):
    expected = {key for key, row in policy.items() if row['status'] == 'reviewed-service-boundary'}
    if not expected or set(baseline['records']) != expected or set(pages) != expected:
        raise ValueError('retained_advisory_coverage_mismatch')
    results = []
    for identifier in sorted(expected):
        row = baseline['records'][identifier]
        if row['source'] != policy[identifier]['source'] or row['source_version'] != policy[identifier]['source_version']:
            raise ValueError('retained_advisory_source_drift:' + identifier)
        observed = page_digest(identifier, pages[identifier])
        results.append(dict(id=identifier, url='https://security-tracker.debian.org/tracker/' + identifier,
            semantic_sha256=observed, unchanged=observed == row['semantic_sha256'],
            disposition='reviewed-service-boundary'))
    return dict(checked_utc=datetime.now(timezone.utc).isoformat(), records=results,
        passed=all(row['unchanged'] for row in results),
        scope='Advisory drift only. Unchanged does not mean library-fixed, image-scanned or zero-vulnerability.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, default=BASELINE)
    parser.add_argument('--pages', type=Path, help='Previously fetched CVE-ID.html files; offline review')
    parser.add_argument('--output', type=Path, required=True, help='New receipt; existing files are never overwritten')
    args = parser.parse_args()
    if args.output.exists(): raise FileExistsError(args.output)
    policy = json.loads(POLICY.read_text())['records']
    baseline = json.loads(args.baseline.read_text())
    identifiers = sorted(key for key, row in policy.items() if row['status'] == 'reviewed-service-boundary')
    pages = {}
    for identifier in identifiers:
        if args.pages:
            pages[identifier] = (args.pages / (identifier + '.html')).read_bytes()
        else:
            request = urllib.request.Request('https://security-tracker.debian.org/tracker/' + identifier,
                headers={'User-Agent': 'Sonovect-advisory-review/0.1.0'})
            with urllib.request.urlopen(request, timeout=30) as response:
                content = response.read(2**20 + 1)
            if len(content) > 2**20: raise ValueError('advisory_page_too_large')
            pages[identifier] = content
    result = assess(policy, baseline, pages)
    with args.output.open('x') as out:
        out.write(json.dumps(result, indent=2) + '\n')
    print(json.dumps(dict(passed=result['passed'], checked=len(result['records']), output=str(args.output))))
    return 0 if result['passed'] else 1


if __name__ == '__main__': raise SystemExit(main())
