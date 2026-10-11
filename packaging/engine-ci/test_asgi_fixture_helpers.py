"""First-party ASGI fixture adapter tests; all third-party modules are mocked."""
import asyncio
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.dont_write_bytecode=True
ROOT=Path(__file__).parent
spec=importlib.util.spec_from_file_location('synthetic_asgi_fixture',ROOT/'smoke_asgi_authenticated.py')
api=importlib.util.module_from_spec(spec);spec.loader.exec_module(api)


class Cookies:
    def __init__(self): self.cleared=False
    def clear(self): self.cleared=True


class Transport:
    def __init__(self):
        self.cookies=Cookies();self.requests=[];self.reply=SimpleNamespace(
            headers={'x-deepdesk-instance':'n'},status_code=200,content=b'{}',json=lambda:{})
        self.inject_cookie=False
    def build_request(self,method,path,content,headers):
        headers={k.lower():v for k,v in headers.items()}
        if self.inject_cookie: headers['cookie']='synthetic'
        request=SimpleNamespace(url='http://127.0.0.1:54321'+path,headers=headers)
        self.requests.append(request);return request
    def send(self,request,follow_redirects):
        assert follow_redirects is False
        return self.reply


class AdapterTests(unittest.TestCase):
    def test_token_free_metadata_handshake(self):
        transport=Transport();client=api.Client(transport,'n')
        client.request('GET','/api/v1/health',bootstrap=True)
        self.assertTrue(client.verified)
        self.assertNotIn('x-deepdesk-request',transport.requests[-1].headers)
        self.assertNotIn('cookie',transport.requests[-1].headers)

    def test_bootstrap_cookie_refused(self):
        transport=Transport();transport.inject_cookie=True
        with self.assertRaisesRegex(RuntimeError,'secret'):
            api.Client(transport,'n').request('GET','/api/v1/health',bootstrap=True)

    def test_identity_mismatch_refused(self):
        client=api.Client(Transport(),'wrong')
        with self.assertRaisesRegex(RuntimeError,'metadata differs'):
            client.request('GET','/api/v1/health',bootstrap=True)
        self.assertFalse(client.verified)

    def test_authenticated_request_requires_initial_check(self):
        with self.assertRaisesRegex(RuntimeError,'metadata must'):
            api.Client(Transport(),'n').request('GET','/auth/check')

    def test_cross_origin_path_refused(self):
        client=api.Client(Transport(),'n');client.verified=True
        for path in ('//other.invalid/','http://other.invalid/'):
            with self.assertRaisesRegex(RuntimeError,'route'): client.request('GET',path)

    def test_mutation_headers_and_context(self):
        transport=Transport();client=api.Client(transport,'n');client.verified=True
        client.csrf='csrf';client.context='ctx'
        client.form('/auth/login',{'password':'synthetic-&+=%'})
        self.assertEqual(transport.requests[-1].headers['x-ldr-auth-context'],'ctx')
        self.assertEqual(transport.requests[-1].headers['x-csrf-token'],'csrf')
        self.assertEqual(transport.requests[-1].headers['x-deepdesk-request'],'n')

    def test_missing_csrf_refused(self):
        client=api.Client(Transport(),'n');client.verified=True
        with self.assertRaisesRegex(RuntimeError,'CSRF'): client.request('POST','/auth/logout')

    def test_response_limit_checked(self):
        transport=Transport();transport.reply.content=b'x'*(2*1024**2+1)
        client=api.Client(transport,'n')
        with self.assertRaisesRegex(RuntimeError,'limit'): client.request('GET','/api/v1/health',bootstrap=True)

    def test_streaming_response_cap_stops_before_buffering(self):
        sent=[]
        async def application(scope,receive,send):
            await send({'type':'http.response.body','body':b'x'*(2*1024**2)})
            await send({'type':'http.response.body','body':b'x'})
        async def record(message): sent.append(len(message['body']))
        with self.assertRaisesRegex(RuntimeError,'limit'):
            asyncio.run(api.ResponseCap(application)({'type':'http'},None,record))
        self.assertEqual(sent,[2*1024**2])


class WorkerSeamTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);(self.root/'deepdesk-ci-fixture-only').write_text('a'*64)
        self.config={'fixture_marker':'a'*64,'username':'deepdesk_fixture_'+'b'*12,
            'password':'fixture1-&+=%'+'c'*64,'research_id':'12345678-1234-4234-8234-123456789abc'}

    def invoke(self,*,change=None,repeated=False):
        events=[];fakeuvicorn=SimpleNamespace(run=lambda:None);original=fakeuvicorn.run
        fakeapp=object()
        class TestClient:
            def __init__(self,app,**kwargs):
                assert isinstance(app,api.ResponseCap) and app.app is fakeapp
                assert kwargs=={'base_url':'http://127.0.0.1:54321','follow_redirects':False,'client':('127.0.0.1',54322)}
            def __enter__(self): events.append('enter');return self
            def __exit__(self,*args): events.append('exit')
        def serve():
            sys.modules['local_deep_research.web.fastapi_app']=SimpleNamespace(app=fakeapp)
            kwargs={'host':'127.0.0.1','port':54321,'workers':1,'log_level':'warning',
                'access_log':False,'server_header':False,'timeout_keep_alive':5,'timeout_graceful_shutdown':10,
                'proxy_headers':False,'forwarded_allow_ips':None}
            kwargs.update(change or {})
            fakeuvicorn.run('local_deep_research.web.fastapi_app:app',**kwargs)
            if repeated: fakeuvicorn.run('local_deep_research.web.fastapi_app:app',**kwargs)
        testmodule=SimpleNamespace(TestClient=TestClient,httpx=SimpleNamespace(__name__='httpx2',__version__='2.13.1'))
        mocks={'uvicorn':fakeuvicorn,'starlette':SimpleNamespace(testclient=testmodule),'starlette.testclient':testmodule}
        with patch.dict(sys.modules,mocks),patch.dict(os.environ,{'LDR_DATA_DIR':str(self.root/'data')}), \
             patch.object(sys,'stdin',SimpleNamespace(buffer=io.BytesIO(json.dumps(self.config).encode()))), \
             patch.object(api.runpy,'run_path',return_value={'serve':serve}), \
             patch.object(api,'exercise',side_effect=lambda *args:events.append('routes')):
            try: result=api.run_worker(self.root/'unchanged-wrapper.py','register')
            finally: sys.modules.pop('local_deep_research.web.fastapi_app',None)
        self.assertIs(fakeuvicorn.run,original)
        return result,events

    def test_exact_seam_lifespan_and_restore(self):
        result,events=self.invoke();self.assertEqual(events,['enter','routes','exit'])
        self.assertTrue(result['lifespan_completed']);self.assertFalse(result['real_http_tested'])

    def test_nonloopback_launch_refused(self):
        with self.assertRaisesRegex(RuntimeError,'arguments'): self.invoke(change={'host':'0.0.0.0'})

    def test_extra_server_config_refused(self):
        with self.assertRaisesRegex(RuntimeError,'arguments'): self.invoke(change={'reload':True})

    def test_duplicate_server_invocation_refused(self):
        with self.assertRaisesRegex(RuntimeError,'repeated'): self.invoke(repeated=True)

    def test_offline_profile_is_unchanged(self):
        self.assertEqual(hashlib.sha256((ROOT/'runtime-offline.sb').read_bytes()).hexdigest(),
            '9d4f464140e5bb35efb2f937e820349b6f7a47482d4fcb2a618cc489b9bf4710')
        source=(ROOT/'runtime_asgi_stage.py').read_text()
        self.assertNotIn('SERVER_ADDRESS',source)
        self.assertNotIn('runtime-loopback.sb',source)
        self.assertNotIn('reservation.bind',source)


if __name__=='__main__': unittest.main()
