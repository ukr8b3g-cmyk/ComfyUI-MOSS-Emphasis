import sys
import types
import unittest
from unittest.mock import patch
try:
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer
except ImportError:
    web = None
from moss_emphasis.api import install_routes
from test_core import graph, ON

@unittest.skipIf(web is None, "aiohttp unavailable")
class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.server=types.SimpleNamespace(routes=web.RouteTableDef())
        module=types.ModuleType('server');module.PromptServer=types.SimpleNamespace(instance=self.server)
        with patch.dict(sys.modules,{'server':module}):install_routes();install_routes()
        app=web.Application();app.add_routes(self.server.routes);self.client=TestClient(TestServer(app));await self.client.start_server()
    async def asyncTearDown(self):await self.client.close()
    async def test_prepare_ok(self):
        r=await self.client.post('/moss_emphasis/prepare',json={'schema_version':1,'prompt':graph(),'settings':ON});self.assertEqual(r.status,200);self.assertEqual(len((await r.json())['targets']),1)
    async def test_invalid_request(self):
        r=await self.client.post('/moss_emphasis/prepare',json=[]);self.assertEqual(r.status,400)
    async def test_invalid_strength(self):
        r=await self.client.post('/moss_emphasis/prepare',json={'schema_version':1,'prompt':graph(),'settings':{'enabled':True,'strength':99}});self.assertEqual(r.status,400)
    async def test_unsupported_path(self):
        g=graph();g['3']['class_type']='ConditioningConcat';r=await self.client.post('/moss_emphasis/prepare',json={'schema_version':1,'prompt':g,'settings':ON});self.assertEqual(r.status,400)
    async def test_off_no_injection(self):
        g=graph();r=await self.client.post('/moss_emphasis/prepare',json={'schema_version':1,'prompt':g,'settings':{}});self.assertEqual((await r.json())['prompt'],g)

if __name__=='__main__':unittest.main()
