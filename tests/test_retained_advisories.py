"""An advisory tracker must fail closed on drift and incomplete evidence."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('retained', Path(__file__).resolve().parents[1] / 'scripts/check_retained_advisories.py')
retained = importlib.util.module_from_spec(spec)
spec.loader.exec_module(retained)


class RetainedAdvisoryTests(unittest.TestCase):
    identifier = 'CVE-2010-4756'

    def fixture(self):
        page = ('<h1>' + self.identifier + '</h1><p>Name ' + self.identifier
            + '</p><h2>Vulnerable and fixed packages</h2><p>Fixed Version (unfixed)</p>'
            + '<h2>Notes</h2><p>' + 'Standard library behavior requiring caller limits. ' * 12 + '</p>').encode()
        policy = {self.identifier: dict(status='reviewed-service-boundary', source='glibc', source_version='fixed-build')}
        baseline = dict(records={self.identifier: dict(source='glibc', source_version='fixed-build',
            semantic_sha256=retained.page_digest(self.identifier, page))})
        return policy, baseline, {self.identifier: page}

    def test_unchanged_is_reviewed_not_fixed(self):
        result = retained.assess(*self.fixture())
        self.assertTrue(result['passed'])
        self.assertEqual(result['records'][0]['disposition'], 'reviewed-service-boundary')

    def test_upstream_repair_or_note_change_requires_review(self):
        policy, baseline, pages = self.fixture()
        pages[self.identifier] = pages[self.identifier].replace(b'(unfixed)', b'2.99-1')
        self.assertFalse(retained.assess(policy, baseline, pages)['passed'])

    def test_missing_evidence_or_policy_entry_cannot_pass(self):
        policy, baseline, pages = self.fixture()
        with self.assertRaisesRegex(ValueError, 'coverage_mismatch'): retained.assess(policy, baseline, {})
        with self.assertRaisesRegex(ValueError, 'coverage_mismatch'): retained.assess({}, baseline, pages)

    def test_truncated_or_error_page_cannot_pass(self):
        with self.assertRaisesRegex(ValueError, 'incomplete_advisory'): retained.page_digest(self.identifier, b'<h1>Access denied</h1>')

    def test_source_version_change_requires_new_review(self):
        policy, baseline, pages = self.fixture()
        policy[self.identifier]['source_version'] = 'new-build'
        with self.assertRaisesRegex(ValueError, 'source_drift'): retained.assess(policy, baseline, pages)


if __name__ == '__main__': unittest.main()
