import json
import unittest
from scripts.check_dependency_audit import classify, ROOT


class DependencyDispositionTests(unittest.TestCase):
    def setUp(self):
        self.statements=[{'package':'torch','version':'2.11.0','id':'CVE-2025-3000','platform':'linux','roles':['asr'],'status':'not_affected','justification':'synthetic scope fixture','impact_statement':'test fixture only','references':[]}]
        self.package={'name':'torch','version':'2.11.0+cpu','vulns':[{'id':'PYSEC-example','aliases':['CVE-2025-3000']}]}

    def test_review_requires_exact_version_platform_and_role(self):
        for role,platform,version in [('asr','linux','2.12.0'),('api','linux','2.11.0'),('asr','darwin','2.11.0')]:
            value=classify({'dependencies':[{**self.package,'version':version}]},self.statements,role=role,platform=platform)
            self.assertEqual(len(value['unresolved']),1)
        value=classify({'dependencies':[self.package]},self.statements,role='asr',platform='linux')
        self.assertEqual(len(value['reviewed_not_affected']),1)

    def test_unknown_advisory_and_unscannable_package_remain_open(self):
        package={**self.package,'vulns':[{'id':'NEW-ADVISORY','aliases':[]}]}
        value=classify({'dependencies':[package,{'name':'unknown','skip_reason':'not queryable'}]},self.statements,role='asr',platform='linux')
        self.assertEqual(len(value['unresolved']),1)
        self.assertEqual(len(value['skipped']),1)

    def test_duplicate_scanner_aliases_are_counted_once(self):
        package={**self.package,'vulns':self.package['vulns']*2}
        value=classify({'dependencies':[package]},self.statements,role='asr',platform='linux')
        self.assertEqual(value['raw_package_advisory_pairs'],1)


class DependencyHygieneTests(unittest.TestCase):
    def test_four_part_package_versions_do_not_hide_endpoint_addresses(self):
        from scripts.check_public_tree import scan_text
        version = "10." + "4.0.35"
        self.assertNotIn("private-network-address", scan_text("requirements.lock", "nvidia-curand=="+version))
        self.assertIn("private-network-address", scan_text("README.md", version))
        self.assertIn("private-network-address", scan_text("requirements.lock", "# URL http://"+version))
