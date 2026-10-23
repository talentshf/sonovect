import importlib.util,logging,unittest
from pathlib import Path
from unittest.mock import Mock,patch
spec=importlib.util.spec_from_file_location('snapshot_cache',Path(__file__).parents[1]/'shared/snapshot_cache.py')
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
class SnapshotTests(unittest.TestCase):
    def test_offline_missing_snapshot_does_not_fall_back_to_network(self):
        download=Mock(side_effect=FileNotFoundError('cache missing'))
        with patch.dict('os.environ',{'SONOVECT_MODELS_OFFLINE':'1'}):
            with self.assertRaises(FileNotFoundError):
                mod.resolve_pinned_snapshot(download,repo_id='Qwen/Qwen3-ASR-1.7B-hf',revision='bcd2b5b7f32b480ab5790554cfa8347f246a14f3',logger=logging.getLogger('test'))
        download.assert_called_once();self.assertTrue(download.call_args.kwargs['local_files_only'])
    def test_unlisted_model_is_rejected_before_download(self):
        download=Mock()
        with self.assertRaisesRegex(RuntimeError,'not_in_catalog'):
            mod.resolve_pinned_snapshot(download,repo_id='owner/arbitrary',revision='main',logger=logging.getLogger('test'))
        download.assert_not_called()
