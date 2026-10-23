"""Generated configuration references must not depend on filesystem order."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('configuration_inventory',ROOT/'scripts/check_configuration.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class ConfigurationInventoryTests(unittest.TestCase):
    def test_reversed_directory_order_preserves_runtime_entrypoint_defaults(self):
        expected=module.inventory();original=Path.glob
        with patch.object(Path,'glob',lambda self,pattern:iter(reversed(list(original(self,pattern))))):
            self.assertEqual(module.inventory(),expected)
        self.assertEqual(expected['segmentation-worker']['VAD_BACKEND'],'fsmn')
