import ast,asyncio,unittest
from pathlib import Path
from unittest.mock import AsyncMock


class SoundHandoffTests(unittest.TestCase):
    def helper(self, resident=True, released=None, enabled=True):
        source=Path(__file__).parents[1]/'api/app.py'
        node=next(n for n in ast.parse(source.read_text()).body if isinstance(n,ast.AsyncFunctionDef) and n.name=='_release_sound_before_speech')
        probe=AsyncMock(return_value={'reachable':True,'payload':{'manager':{'resident':resident}}})
        control=AsyncMock(return_value=released or {'status':'unloaded','manager':{'resident':False,'busy':False}})
        ns={'VOICE_ENABLED':enabled,'VOICE_BACKEND':'moss','MOSS_URL':'http://sound','_probe':probe,'_post_control':control}
        exec(compile(ast.Module(body=[node],type_ignores=[]),str(source),'exec'),ns)
        return ns['_release_sound_before_speech'],probe,control

    def test_retained_sound_model_must_release_before_asr(self):
        helper,probe,control=self.helper()
        asyncio.run(helper());control.assert_awaited_once()
        helper,_,_=self.helper(released={'status':'unloaded','manager':{'resident':True,'busy':False}})
        with self.assertRaisesRegex(RuntimeError,'unload_not_confirmed'):asyncio.run(helper())

    def test_omitted_or_already_unloaded_sound_does_not_run_control(self):
        for enabled,resident in [(False,True),(True,False)]:
            helper,probe,control=self.helper(resident=resident,enabled=enabled)
            asyncio.run(helper());control.assert_not_awaited()
            if not enabled:probe.assert_not_awaited()

    def test_cpu_voice_never_probes_or_evicts_gpu_models(self):
        source=Path(__file__).parents[1]/'api/app.py'
        node=next(n for n in ast.parse(source.read_text()).body if isinstance(n,ast.AsyncFunctionDef) and n.name=='_release_sound_before_speech')
        probe,control=AsyncMock(),AsyncMock()
        ns={'VOICE_ENABLED':True,'VOICE_BACKEND':'emotion2vec','_probe':probe,'_post_control':control}
        exec(compile(ast.Module(body=[node],type_ignores=[]),str(source),'exec'),ns)
        asyncio.run(ns['_release_sound_before_speech']());probe.assert_not_awaited();control.assert_not_awaited()
