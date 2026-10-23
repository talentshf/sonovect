import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('vocal_output', Path(__file__).parents[1]/'moss-worker/vocal_output.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class VocalOutputTests(unittest.TestCase):
    def test_demographic_relative_claim_is_omitted_without_rewriting(self):
        for value in ('Mid-to-high for a male','Young female voice','女性，音调偏高','听起来约30岁'):
            self.assertEqual(module.audible_description(value),'')

    def test_audible_properties_survive_and_nontext_is_not_invented(self):
        for value in ('Average volume','Clear human voice','High-pitched','Low and breathy','清晰且偏慢'):
            self.assertEqual(module.audible_description(value),value)
        for value in ({'pitch':'high'},['slow'],None,42,'x'*513):
            self.assertEqual(module.audible_description(value),'')
