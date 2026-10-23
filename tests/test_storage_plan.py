"""Capacity failures precede every download; verified bytes are not charged twice."""
import hashlib
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from sonovect.assets import storage_plan
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('storage_preparer',ROOT/'scripts/prepare_deployment.py')
preparer=importlib.util.module_from_spec(spec);spec.loader.exec_module(preparer)


class StoragePlanTests(unittest.TestCase):
    def test_partial_corrupt_and_complete_sdk_caches_are_hashed_without_writes(self):
        for hub in ['huggingface','modelscope']:
            with TemporaryDirectory() as raw:
                base=Path(raw);model={'hub':hub,'repo_id':'org/a.b','revision':'abcdef',
                    'files':{name:{'size':len(data),'algorithm':'sha256','digest':hashlib.sha256(data).hexdigest()}
                             for name,data in [('a',b'correct'),('b',b'weights')]}}
                root=base/('models--org--a.b' if hub=='huggingface' else 'models/org--a.b')/'snapshots/abcdef'
                root.mkdir(parents=True);(root/'a').write_bytes(b'correct')
                with patch('sonovect.assets.catalog',return_value={'selected':model}):
                    row=storage_plan(['selected'],str(base))[0]
                    self.assertEqual((row['missing_bytes'],row['verified_files']),(7,1))
                    (root/'b').write_bytes(b'corrupt')
                    self.assertEqual(storage_plan(['selected'],str(base))[0]['missing_bytes'],7)
                    (root/'b').write_bytes(b'weights')
                    before={str(p):p.stat().st_mtime_ns for p in base.rglob('*')}
                    self.assertEqual(storage_plan(['selected'],str(base))[0]['missing_bytes'],0)
                    self.assertEqual(before,{str(p):p.stat().st_mtime_ns for p in base.rglob('*')})

    def test_shadowed_complete_modelscope_cache_does_not_hide_active_missing_files(self):
        with TemporaryDirectory() as raw:
            base=Path(raw);data=b'weights';model={'hub':'modelscope','repo_id':'org/model','revision':'fixed',
                'files':{'weight':{'size':len(data),'algorithm':'sha256','digest':hashlib.sha256(data).hexdigest()}}}
            old=base/'org/model';old.mkdir(parents=True);(old/'weight').write_bytes(data)
            active=base/'models/org--model/snapshots/fixed';active.mkdir(parents=True)
            with patch('sonovect.assets.catalog',return_value={'selected':model}):
                self.assertEqual(storage_plan(['selected'],str(base))[0]['missing_bytes'],len(data))
                (active/'weight').write_bytes(data)
                self.assertEqual(storage_plan(['selected'],str(base))[0]['missing_bytes'],0)
                (active/'weight').unlink()
                preferred=base/'models/org/model';preferred.mkdir(parents=True);(preferred/'weight').write_bytes(data)
                self.assertEqual(storage_plan(['selected'],str(base))[0]['missing_bytes'],0)

    def test_failed_capacity_stops_preparation_and_verify_only_never_requires_it(self):
        import io
        from contextlib import redirect_stdout, redirect_stderr
        config={'services':{'api':{'environment':{}},'worker':{'environment':{'SONOVECT_BACKEND':'funasr'}}}}
        for flags in [[],['--verify-only']]:
            with patch.object(preparer.subprocess,'check_output',return_value=json.dumps(config)), \
                 patch.object(preparer.subprocess,'run') as run, \
                 patch.object(preparer,'check_capacity',side_effect=ValueError('insufficient_model_disk_space')) as capacity, \
                 patch('sys.argv',['prepare_deployment.py',*flags]), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                status=preparer.main()
                if flags:
                    self.assertEqual(status,0);capacity.assert_not_called()
                    self.assertTrue(all('verify' in c.args[0] for c in run.call_args_list))
                else:
                    self.assertEqual(status,1);run.assert_not_called()

    def test_capacity_is_aggregated_per_filesystem_and_complete_cache_needs_no_reserve(self):
        def row(fs,missing,free):return {'filesystem':fs,'missing_bytes':missing,'free_bytes':free,
                                        'largest_missing_file':missing,'alias':'selected'}
        tasks=[('worker',['sonovect','models'],['selected'],[]),('analysis',['sonovect','models'],['other'],[])]
        with patch.object(preparer.subprocess,'check_output',side_effect=[json.dumps([row('shared',2**30,4*2**30)]),json.dumps([row('shared',2**30,4*2**30)])]):
            self.assertEqual(preparer.check_capacity([],tasks)[0]['missing_bytes'],2*2**30)
        with patch.object(preparer.subprocess,'check_output',side_effect=[json.dumps([row('shared',2**30,3*2**30)]),json.dumps([row('shared',2**30,3*2**30)])]):
            with self.assertRaisesRegex(ValueError,'insufficient_model_disk_space'):preparer.check_capacity([],tasks)
        with patch.object(preparer.subprocess,'check_output',return_value=json.dumps([row('complete',0,1)])):
            self.assertEqual(preparer.check_capacity([],tasks)[0]['missing_bytes'],0)
        with patch.object(preparer.subprocess,'check_output',side_effect=[json.dumps([row('a',2**30,3*2**30)]),json.dumps([row('b',2**30,3*2**30)])]):
            self.assertEqual(len(preparer.check_capacity([],tasks)),2)
