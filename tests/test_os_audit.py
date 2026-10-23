import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('os_audit', Path(__file__).parents[1] / 'scripts/check_os_audit.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class OSAuditTests(unittest.TestCase):
    def fixture(self, advisory='CVE-2026-78408', name='util-linux', version='2.42.4-1~sonovect13.1'):
        packages = [{'package': name, 'version': version, 'source': name, 'source_version': version}]
        packages += [{'package': 'fixture'+str(i), 'version': '1', 'source': 'fixture', 'source_version': '1'} for i in range(50)]
        facts = dict(packages=packages, systemd_homed_paths=[], archive_tar_paths=[], setid_paths=[])
        audit = {'Metadata': {'OS': {'Family': 'debian', 'Name': '13.7'}}, 'Results': [{'Type': 'debian',
                 'Packages': [{'Name': p['package'], 'Version': p['version']} for p in packages],
                 'Vulnerabilities': [{'VulnerabilityID': advisory, 'PkgName': name, 'InstalledVersion': version, 'Severity': 'HIGH'}]}]}
        return audit, facts

    def test_exact_backport_is_reviewed_but_raw_match_is_retained(self):
        audit, facts = self.fixture()
        value = module.classify(audit, facts)
        self.assertEqual(value['raw_matches'], 1)
        self.assertEqual(value['reviewed_high_critical'][0]['status'], 'fixed-by-source-backport')
        self.assertEqual(value['unresolved_high_critical'], [])

    def test_unknown_or_drifted_high_fails(self):
        for kwargs in ({'advisory': 'CVE-2099-unknown'}, {'version': '2.41.5-0+deb13u1'}):
            audit, facts = self.fixture(**kwargs)
            self.assertEqual(len(module.classify(audit, facts)['unresolved_high_critical']), 1)

    def test_scanner_epoch_and_debian_revision_are_not_lost(self):
        audit, facts = self.fixture()
        facts['packages'][0]['version'] = '1:2.42.4-1~sonovect13.1'
        audit['Results'][0]['Packages'][0].update(Version='2.42.4', Epoch=1, Release='1~sonovect13.1')
        self.assertFalse(module.classify(audit, facts)['unresolved_high_critical'])
        audit['Results'][0]['Packages'][0]['Epoch'] = 2
        with self.assertRaises(ValueError):
            module.classify(audit, facts)

    def test_missing_component_exception_requires_exact_package_and_absence(self):
        audit, facts = self.fixture('CVE-2026-16742', 'systemd', '257.13-1~deb13u1')
        self.assertEqual(module.classify(audit, facts)['reviewed_high_critical'][0]['justification'], 'vulnerable_code_not_present')
        for key in ('systemd_homed_paths', 'setid_paths'):
            changed = copy.deepcopy(facts)
            changed[key] = ['/unexpected/file']
            self.assertTrue(module.classify(audit, changed)['unresolved_high_critical'])

    def test_incomplete_scan_and_inventory_mismatch_fail_closed(self):
        audit, facts = self.fixture()
        for changed in ({}, {**audit, 'Results': []}):
            with self.assertRaises(ValueError):
                module.classify(changed, facts)
        facts['packages'][0]['version'] = 'another'
        with self.assertRaises(ValueError):
            module.classify(audit, facts)

    def test_medium_findings_are_preserved_not_silently_marked_fixed(self):
        audit, facts = self.fixture()
        audit['Results'][0]['Vulnerabilities'][0]['Severity'] = 'MEDIUM'
        value = module.classify(audit, facts)
        self.assertEqual(value['residual_lower_severity'][0]['severity'], 'MEDIUM')
        self.assertEqual(value['reviewed_high_critical'], [])
        self.assertEqual(len(value['unresolved_lower_severity']), 1)

    def test_low_absence_is_not_accepted_without_observed_file_evidence(self):
        audit, facts = self.fixture('CVE-2026-82560', 'perl', '5.40.1-6+deb13u1')
        audit['Results'][0]['Vulnerabilities'][0]['Severity'] = 'UNKNOWN'
        self.assertTrue(module.classify(audit, facts)['unresolved_lower_severity'])
        facts['residual'] = {'modules': {'pod_text': []}}
        self.assertFalse(module.classify(audit, facts)['unresolved_lower_severity'])
        facts['residual']['modules']['pod_text'] = ['/usr/lib/perl/Pod/Text.pm']
        self.assertTrue(module.classify(audit, facts)['unresolved_lower_severity'])

    def test_library_patch_version_must_match_current_policy(self):
        audit, facts = self.fixture('CVE-2026-27171', 'zlib', '1:1.3.dfsg+really1.3.1-1+sonovect13.1')
        audit['Results'][0]['Vulnerabilities'][0]['Severity'] = 'MEDIUM'
        self.assertFalse(module.classify(audit, facts)['unresolved_lower_severity'])
        facts['packages'][0]['source_version'] = '1:1.3.dfsg+really1.3.1-1'
        self.assertTrue(module.classify(audit, facts)['unresolved_lower_severity'])

    def test_reviewed_boundary_remains_explicit_and_requires_supported_profile(self):
        audit, facts = self.fixture('CVE-2019-1010022', 'glibc', '2.43-7~sonovect13.1')
        audit['Results'][0]['Vulnerabilities'][0]['Severity'] = 'LOW'
        facts['residual'] = {'uid': 10001, 'effective_capabilities': '0000000000000000',
                             'no_new_privileges': '1', 'commands': {x: [] for x in ['sh', 'bash', 'dash', 'perl']}}
        value = module.classify(audit, facts)
        self.assertEqual(value['reviewed_lower_severity'][0]['status'], 'reviewed-service-boundary')
        facts['residual']['uid'] = 0
        self.assertTrue(module.classify(audit, facts)['unresolved_lower_severity'])

    def test_specific_loader_entry_requires_actual_ldd_absence(self):
        audit, facts = self.fixture('CVE-2019-1010023', 'glibc', '2.43-7~sonovect13.1')
        audit['Results'][0]['Vulnerabilities'][0]['Severity'] = 'LOW'
        facts['residual'] = {'uid':10001,'effective_capabilities':'0000000000000000',
                             'no_new_privileges':'1','commands':{x:[] for x in ['sh','bash','dash','perl']}}
        self.assertTrue(module.classify(audit,facts)['unresolved_lower_severity'])
        facts['residual']['commands']['ldd'] = []
        self.assertFalse(module.classify(audit,facts)['unresolved_lower_severity'])
        facts['residual']['commands']['ldd'] = ['/usr/bin/ldd']
        self.assertTrue(module.classify(audit,facts)['unresolved_lower_severity'])
