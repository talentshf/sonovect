"""Safety gates must reject plausible deployment drift before publication."""
import copy
import importlib.util
import sys
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from check_release import validate_configuration


class ReleaseConfigurationTests(unittest.TestCase):
    def config(self):
        s={'user':'10001:10001','cap_drop':['ALL'],'security_opt':['no-new-privileges:true']}
        return {'services':{'api':copy.deepcopy(s),'worker':copy.deepcopy(s),'speech-measurements':copy.deepcopy(s)}}

    def test_reject_privilege_escalation_and_private_port_exposure(self):
        for patch in [{'privileged':True},{'cap_drop':[]},{'security_opt':[]},{'user':'0'},{'ports':['8086:8086']}]:
            config=self.config();config['services']['speech-measurements'].update(patch)
            with self.assertRaises(ValueError):validate_configuration(config)
        self.assertTrue(validate_configuration(self.config()))

    def test_queue_and_weights_cannot_share_one_storage_source(self):
        for volumes in [['shared:/data','shared:/models'],[{'source':'shared','target':'/data'},{'source':'shared','target':'/models/cache'}]]:
            config=self.config();config['services']['worker']['volumes']=volumes
            with self.assertRaisesRegex(ValueError,'storage_overlap'):validate_configuration(config)

    def test_cross_service_queue_model_storage_overlap_rejected(self):
        config=self.config()
        config['services']['api']['volumes']=['shared:/data']
        config['services']['speech-measurements']['volumes']=['shared:/models']
        with self.assertRaisesRegex(ValueError,'across_services'):validate_configuration(config)


if __name__=='__main__':unittest.main()
