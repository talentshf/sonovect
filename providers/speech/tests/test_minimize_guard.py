import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('image_minimize',Path(__file__).parents[1]/'shared/os-security/minimize.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class ImageMinimizeGuardTests(unittest.TestCase):
    def test_checkout_invocation_refuses_before_filesystem_mutation(self):
        with patch.dict(module.os.environ,{},clear=True), patch.object(module.Path,'unlink',side_effect=AssertionError('must not unlink')) as unlink:
            with self.assertRaisesRegex(RuntimeError,'image_installation_only'):
                module.minimize()
            unlink.assert_not_called()
