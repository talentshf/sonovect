"""Optional assembly stays explicit, independent and byte-verified."""
import importlib.util
import io
import json
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from sonovect.assets import catalog, main as assets_main
from sonovect.setup import main as setup_main

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('component_preparer', ROOT/'scripts/prepare_deployment.py')
preparer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preparer)


class ComponentSelectionTests(unittest.TestCase):
    def configuration(self, route, voice, explicit=False):
        models = catalog()
        core = {'SONOVECT_SOUND_ENABLED': 'true', 'SONOVECT_VOICE_ENABLED': 'true',
                'SONOVECT_VOICE_BACKEND': 'emotion2vec' if voice == 'emotion2vec' else 'moss'}
        services = {'api': {'environment': core}, 'speech-events': {'environment': {}}}
        if route == 'cpu':
            services['worker'] = {'environment': {'SONOVECT_BACKEND': 'funasr'}}
        else:
            e = {}
            for prefix, alias in [('QWEN_ASR', 'qwen-1.7b'), ('QWEN_ALIGNER', 'aligner')]:
                e[prefix+'_MODEL'] = models[alias]['repo_id']
                e[prefix+'_REVISION'] = models[alias]['revision']
            services['speech-asr'] = {'environment': e}
            services['speech-segmentation'] = {'environment': {'VAD_BACKEND': 'firered'}}
        alias = 'emotion2vec-base' if voice == 'emotion2vec' else 'moss-'+voice
        name = 'speech-vocal' if voice == 'emotion2vec' else 'speech-sound'
        e = {} if voice == 'emotion2vec' else {'MOSS_AUDIO_MODEL': models[alias]['repo_id'],
                                               'MOSS_AUDIO_REVISION': models[alias]['revision']}
        if explicit:
            e['VOCAL_MODEL_ROOT' if voice == 'emotion2vec' else 'MOSS_MODEL_ROOT'] = '/models/selected'
        services[name] = {'environment': e}
        return {'services': services}

    def invoke_preparer(self, config, flags=()):
        out, err = io.StringIO(), io.StringIO()
        with patch.object(preparer.subprocess, 'check_output', return_value=json.dumps(config)), \
             patch.object(preparer.subprocess, 'run') as run, \
             patch.object(preparer, 'check_capacity', return_value=[]) as capacity, \
             patch('sys.argv', ['prepare_deployment.py', *flags]), redirect_stdout(out), redirect_stderr(err):
            status = preparer.main()
        return status, json.loads(out.getvalue().split("MODEL_STORAGE_PLAN=")[0]), run.call_args_list, err.getvalue()

    def test_compact_preparation_matches_distributed_selected_assets(self):
        from sonovect.setup import selection
        for route in ['cpu','qwen']:
            for voice in ['emotion2vec','4b','8b']:
                compact=self.configuration(route,voice)
                services=compact['services'];core=services['api']['environment']
                core['SONOVECT_LAYOUT']='compact';core['SONOVECT_MEASUREMENTS_ENABLED']='true'
                worker=services.setdefault('worker',{'environment':{}})['environment']
                if route=='qwen':
                    worker.update(services.pop('speech-asr')['environment'])
                    worker.update(services.pop('speech-segmentation')['environment'])
                    worker['SONOVECT_BACKEND']='speech'
                analysis=services.pop('speech-events');analysis['environment'].update(core)
                if voice=='emotion2vec':analysis['environment'].update(services.pop('speech-vocal')['environment'])
                services['analysis']=analysis
                for flags in [[],['--plan'],['--verify-only']]:
                    status,plan,calls,error=self.invoke_preparer(compact,flags)
                    self.assertEqual((status,error),(0,''))
                    self.assertEqual(set(plan['selected_models']),set(selection(route=route,voice=voice,measurements=True)['models']))
                    commands=[c.args[0] for c in calls]
                    self.assertFalse(any('speech-asr' in c or 'speech-segmentation' in c or 'speech-events' in c or 'speech-vocal' in c for c in commands))
                    self.assertEqual(plan['measurement_model_download_bytes'],0)

    def test_both_backends_write_private_configuration_without_extra_permission_flag(self):
        for route in ['cpu', 'qwen']:
            for voice in ['emotion2vec', '4b', '8b']:
                with self.subTest(route=route, voice=voice), TemporaryDirectory() as tmp:
                    out = io.StringIO(); path = Path(tmp)/'.env'
                    with redirect_stdout(out):
                        self.assertEqual(setup_main(['--route', route, '--voice', voice, '--write', str(path)]), 0)
                    plan = json.loads(out.getvalue().split("MODEL_STORAGE_PLAN=")[0])
                    self.assertEqual(plan['component_license_policy'], 'informational')
                    self.assertTrue(plan['experimental'])
                    self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                    self.assertEqual({k for k in plan['models'] if k.startswith(('moss-', 'emotion2vec-'))},
                                     {'emotion2vec-base' if voice == 'emotion2vec' else 'moss-'+voice})
                    self.assertEqual(plan['unconfirmed_model_licenses'], ['emotion2vec-base'] if voice == 'emotion2vec' else [])
                    self.assertEqual(plan['unconfirmed_runtime_licenses'], [] if voice == 'emotion2vec' else ['moss-audio-license-text'])

    def test_selected_model_downloads_and_offline_verification_stay_separate(self):
        for alias in ['emotion2vec-base', 'moss-4b', 'moss-8b']:
            for action in ['prepare', 'verify']:
                with self.subTest(alias=alias, action=action), \
                     patch('sonovect.assets.resolve', return_value='selected-cache') as resolve, redirect_stdout(io.StringIO()):
                    self.assertEqual(assets_main([action, alias]), 0)
                    resolve.assert_called_once_with(alias, None, offline=action == 'verify')

    def test_preparer_only_operates_selected_backend_on_both_routes(self):
        for route in ['cpu', 'qwen']:
            for voice in ['emotion2vec', '4b', '8b']:
                for mode in [[], ['--plan'], ['--verify-only']]:
                    with self.subTest(route=route, voice=voice, mode=mode):
                        status, plan, calls, error = self.invoke_preparer(self.configuration(route, voice), mode)
                        self.assertEqual((status, error), (0, ''))
                        alias = 'emotion2vec-base' if voice == 'emotion2vec' else 'moss-'+voice
                        self.assertIn(alias, plan['selected_models'])
                        self.assertEqual(plan['component_license_policy'], 'informational')
                        if mode == ['--plan']:
                            self.assertEqual(calls, [])
                        else:
                            commands = [call.args[0] for call in calls]
                            self.assertEqual(sum(alias in command for command in commands), 1)
                            action = 'verify' if mode else 'prepare'
                            self.assertTrue(all(action in command for command in commands))
                            other = 'speech-sound' if voice == 'emotion2vec' else 'speech-vocal'
                            self.assertFalse(any(other in command for command in commands))
                            self.assertFalse(any('--allow-unconfirmed-license' in command for command in commands))

    def test_explicit_directories_are_verified_without_duplicate_model_download(self):
        for voice in ['emotion2vec', '4b', '8b']:
            with self.subTest(voice=voice):
                status, plan, calls, error = self.invoke_preparer(self.configuration('cpu', voice, explicit=True))
                self.assertEqual((status, error), (0, ''))
                alias = 'emotion2vec-base' if voice == 'emotion2vec' else 'moss-'+voice
                self.assertEqual(plan['explicit_model_aliases'], [alias])
                commands = [call.args[0] for call in calls]
                self.assertFalse(any(alias in command for command in commands))
                checks = [command[-1] for command in commands if '-c' in command]
                self.assertEqual(len(checks), 1)
                self.assertIn('verify_identity', checks[0])
                self.assertIn(catalog()[alias]['revision'], checks[0])

    def test_removed_permission_flag_is_not_a_current_option(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            setup_main(['--allow-unconfirmed-license'])
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            assets_main(['prepare','emotion2vec-base','--allow-unconfirmed-license'])

    def test_missing_selected_service_still_fails_before_model_preparation(self):
        config = self.configuration('qwen', 'emotion2vec')
        del config['services']['speech-vocal']
        with patch.object(preparer.subprocess, 'check_output', return_value=json.dumps(config)), \
             patch.object(preparer.subprocess, 'run') as run, \
             patch.object(preparer, 'check_capacity', return_value=[]) as capacity, \
             patch('sys.argv', ['prepare_deployment.py']), redirect_stderr(io.StringIO()):
            self.assertEqual(preparer.main(), 1)
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
