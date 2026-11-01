"""Exercise real coordinator aggregation without importing model frameworks."""
import ast
import asyncio
from pathlib import Path
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]


def coordinator(probe):
    tree=ast.parse((ROOT/'api/app.py').read_text())
    names={'_discover','_discovery'}
    nodes=[n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name in names]
    env={'asyncio':asyncio,'_probe':probe,'_health_task':None,
         'SEGMENTATION_URL':'seg','QWEN_URL':'asr','MOSS_URL':'vocal','EVENTS_URL':'events','MEASUREMENTS_URL':'measure',
         'VOICE_ENABLED':True,'SOUND_ENABLED':True,'MEASUREMENTS_ENABLED':True}
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),'coordinator-health','exec'),env)
    return env


class CoordinatorDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_components_parallel_and_concurrent_callers_share_one_collection(self):
        calls=[]
        async def probe(url):
            calls.append(url);await asyncio.sleep(.1)
            return {'reachable':True,'payload':{'status':'ok'}}
        env=coordinator(probe);started=time.monotonic()
        values=await asyncio.gather(*(env['_discovery']() for _ in range(10)))
        self.assertEqual(len(calls),5);self.assertLess(time.monotonic()-started,.5)
        self.assertTrue(all(len(v)==5 for v in values))
        await env['_discovery']();self.assertEqual(len(calls),10)

    async def test_total_timeout_cancels_and_preserves_completed_components(self):
        cancelled=[]
        async def probe(url):
            if url=='asr':return {'reachable':True,'payload':{'status':'ok'}}
            try:await asyncio.sleep(30)
            finally:cancelled.append(url)
        env=coordinator(probe);started=time.monotonic();rows=await env['_discovery']()
        self.assertLess(time.monotonic()-started,5.5);self.assertEqual(len(cancelled),4)
        self.assertTrue(rows['qwen3_asr']['reachable'])
        self.assertEqual(rows['events']['error'],'provider_timeout')
