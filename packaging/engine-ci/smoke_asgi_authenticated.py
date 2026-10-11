"""CI-only real ASGI/lifespan/auth fixture using in-process TestClient transport.

The production wrapper remains unchanged. Only uvicorn.run is intercepted in
fresh worker processes; no TCP listener or real HTTP/native lifecycle is tested.
All workers and the offline seed remain under the unchanged deny-network profile.
"""
from __future__ import annotations
import argparse
from contextlib import redirect_stdout
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import runpy
import secrets
import sys
import tempfile
import urllib.parse
import uuid

_diag_spec=importlib.util.spec_from_file_location('deepdesk_asgi_diagnostics',Path(__file__).with_name('asgi_diagnostics.py'))
diag=importlib.util.module_from_spec(_diag_spec);_diag_spec.loader.exec_module(diag)
checkpoint='controller-setup'
active_phase='controller'


def mark(value):
    global checkpoint
    if value not in diag.CHECKPOINTS: raise RuntimeError('Unknown diagnostic checkpoint')
    checkpoint=value


PORT = 54321  # ASGI scope metadata only; this is never bound to a TCP socket.
CHECKS = {
    'register': ['asgi-health-without-token','managed-host-origin-token-rejection','registration',
        'cookie-session','csrf','auth-context','invalid-start','rejected-start-no-history','logout'],
    'persisted': ['asgi-health-without-token','unauthenticated-report-rejected','wrong-password',
        'correct-password','reopened-account-identity','fixture-status','fixture-report-citation',
        'fixture-history','settings','already-terminal-stop','logout'],
}


def require(value,message):
    if not value:
        raise RuntimeError(message)


def validate_fixture(config):
    require(set(config)=={'fixture_marker','username','password','research_id'},'Unexpected fixture input fields')
    for key,pattern in {'fixture_marker':r'[a-f0-9]{64}','username':r'deepdesk_fixture_[a-f0-9]{12}',
                        'password':r'fixture1-&\+=%[a-f0-9]{64}'}.items():
        require(isinstance(config[key],str) and re.fullmatch(pattern,config[key]),'Invalid synthetic fixture shape')
    require(str(uuid.UUID(config['research_id'],version=4))==config['research_id'],'Invalid fixture research identity')
    root=Path(os.environ['LDR_DATA_DIR'])
    marker=root.parent/'deepdesk-ci-fixture-only'
    require(root.is_absolute() and marker.is_file() and marker.read_text()==config['fixture_marker'],
            'Refusing non-fixture data')


class ResponseCap:
    """Bound real ASGI response bytes before TestClient buffers them."""
    def __init__(self,app): self.app=app
    async def __call__(self,scope,receive,send):
        total=0
        async def bounded_send(message):
            nonlocal total
            if message['type']=='http.response.body':
                total+=len(message.get('body',b''))
                require(total<=2*1024*1024,'ASGI response limit exceeded')
            await send(message)
        await self.app(scope,receive,bounded_send)


class Client:
    def __init__(self,transport,nonce):
        self.transport,self.nonce=transport,nonce
        self.verified=False
        self.csrf,self.context=None,None

    def request(self,method,path,body=None,content_type=None,extra_headers=None,bootstrap=False):
        require(self.verified or (bootstrap and method=='GET' and path=='/api/v1/health'),
                'ASGI identity metadata must be checked before authenticated requests')
        require(path.startswith('/') and not path.startswith('//'),'Unexpected fixture route')
        require(not bootstrap or (body is None and extra_headers is None),'Unsafe bootstrap request')
        headers={'Accept':'application/json'}
        if not bootstrap: headers['X-Deepdesk-Request']=self.nonce
        if content_type: headers['Content-Type']=content_type
        if method!='GET':
            require(self.csrf,'Missing CSRF token')
            headers['X-CSRF-Token']=self.csrf
            if self.context: headers['X-LDR-Auth-Context']=self.context
        headers.update(extra_headers or {})
        request=self.transport.build_request(method,path,content=body,headers=headers)
        require(str(request.url)==f'http://127.0.0.1:{PORT}'+path,'Unexpected ASGI request destination')
        if bootstrap:
            require('cookie' not in request.headers and 'x-deepdesk-request' not in request.headers,
                    'Bootstrap included synthetic secret')
        route=path.split('?',1)[0]
        mark({'/api/v1/health':'health','/auth/csrf-token':'csrf-refresh','/auth/register':'registration',
            '/auth/check':'identity','/history/api':'history','/api/start_research':'invalid-start',
            '/settings/api':'settings','/auth/login':'login','/auth/logout':'logout'}.get(route,
            'report' if route.startswith('/api/report/') else 'status' if route.endswith('/status')
            else 'terminal-stop' if route.startswith('/api/terminate/') else 'unknown'))
        response=self.transport.send(request,follow_redirects=False)
        require(response.headers.get('x-deepdesk-instance')==self.nonce,'ASGI instance metadata differs')
        require(len(response.content)<=2*1024*1024,'ASGI response limit exceeded')
        if bootstrap:
            require(response.status_code==200,'Initial ASGI health failed')
            self.verified=True
        try: data=response.json()
        except (ValueError,UnicodeDecodeError): data=None
        return response.status_code,dict(response.headers),data

    def refresh_csrf(self,authenticated):
        status,_,data=self.request('GET','/auth/csrf-token')
        require(status==200 and isinstance(data,dict) and data.get('csrf_token'),'CSRF refresh failed')
        self.csrf,self.context=data['csrf_token'],data.get('auth_context')
        require(bool(self.context)==authenticated,'Unexpected account context')

    def form(self,path,values):
        return self.request('POST',path,urllib.parse.urlencode(values).encode(),'application/x-www-form-urlencoded')

    def logout(self):
        status,_,_=self.request('POST','/auth/logout')
        require(status in (200,302,303),'Logout failed')
        status,_,data=self.request('GET','/auth/check')
        require(status==401 and data.get('authenticated') is False,'Logout retained authentication')
        self.transport.cookies.clear()
        self.refresh_csrf(False)


def exercise(client,config,phase):
    username,password,research_id=config['username'],config['password'],config['research_id']
    client.request('GET','/api/v1/health',bootstrap=True)
    if phase=='register':
        # Real production middleware, not a mocked route or authorization result.
        mark('managed-boundary')
        for headers in ({'Host':'other.invalid'}, {'Origin':'http://other.invalid'},
                        {'Sec-Fetch-Site':'cross-site'}, {'X-Deepdesk-Request':'incorrect'}, {}):
            invalid_headers={'X-Deepdesk-Request':client.nonce,**headers} if headers else {}
            response=client.transport.get('/auth/check',headers=invalid_headers,follow_redirects=False)
            require(response.status_code==403,'Managed ASGI boundary accepted invalid request')
        status,_,_=client.request('GET','/history/api?limit=5&offset=0')
        require(status==401,'History accepted unauthenticated caller')
        client.refresh_csrf(False)
        status,headers,_=client.form('/auth/register',{'username':username,'password':password,
            'confirm_password':password,'acknowledge':'true'})
        require(status==302 and headers.get('location')=='/','Synthetic registration failed; do not retry')
        status,_,data=client.request('GET','/auth/check')
        require(status==200 and data.get('authenticated') is True and data.get('username')==username,'Registration session failed')
        client.refresh_csrf(True)
        status,_,data=client.request('GET','/history/api?limit=5&offset=0')
        require(status==200 and data.get('items')==[],'Synthetic account not empty')
        invalid=json.dumps({'query':'','mode':'quick'}).encode()
        status,headers,_=client.request('POST','/api/start_research',invalid,'application/json',
            extra_headers={'X-CSRF-Token':'incorrect'})
        require(status==403 and headers.get('x-ldr-csrf-rejected')=='1','CSRF rejection failed')
        status,_,_=client.request('POST','/api/start_research',invalid,'application/json',
            extra_headers={'X-LDR-Auth-Context':'incorrect'})
        require(status==409,'Account-context rejection failed')
        status,_,_=client.request('POST','/api/start_research',invalid,'application/json')
        require(status==400,'Invalid start did not fail before research')
        status,_,data=client.request('GET','/history/api?limit=5&offset=0')
        require(status==200 and data.get('items')==[],'Rejected start created research state')
    else:
        require(phase=='persisted','Unexpected ASGI phase')
        status,_,_=client.request('GET','/api/report/'+research_id)
        require(status==401,'Persisted report accepted unauthenticated caller')
        client.refresh_csrf(False)
        status,_,_=client.form('/auth/login',{'username':username,'password':password+'wrong','remember':'false'})
        require(status==401,'Wrong password accepted')
        client.refresh_csrf(False)
        status,headers,_=client.form('/auth/login',{'username':username,'password':password,'remember':'false'})
        require(status==302 and headers.get('location')=='/','Correct-key login after process reopen failed')
        status,_,data=client.request('GET','/auth/check')
        require(status==200 and data.get('authenticated') is True and data.get('username')==username,'Reopened account identity differs')
        client.refresh_csrf(True)
        status,_,data=client.request('GET','/api/research/'+research_id+'/status')
        require(status==200 and data.get('status')=='completed' and data.get('progress')==100,'Fixture status mismatch')
        status,_,data=client.request('GET','/api/report/'+research_id)
        require(status==200 and data.get('summary')==data.get('content') and 'Synthetic CI evidence' in data['content'],'Fixture report mismatch')
        require(any(x.get('url')=='https://fixture.invalid/evidence' for x in data.get('sources',[])),'Fixture citation missing')
        status,_,data=client.request('GET','/history/api?limit=5&offset=0')
        require(status==200 and any(x.get('id')==research_id for x in data.get('items',[])),'Fixture history missing')
        status,_,data=client.request('GET','/settings/api')
        require(status==200 and data.get('status')=='success' and isinstance(data.get('settings'),dict),'Authenticated settings failed')
        status,_,data=client.request('POST','/api/terminate/'+research_id)
        require(status==200 and data.get('status')=='success','Already-terminal stop failed')
    client.logout()


def run_worker(engine,phase):
    mark('fixture-input')
    raw=sys.stdin.buffer.read(16385)
    require(len(raw)<=16384,'Oversized synthetic stdin')
    config=json.loads(raw);validate_fixture(config)
    require(not any(x=='local_deep_research' or x.startswith('local_deep_research.') for x in sys.modules),
            'Upstream imported before managed wrapper setup')
    nonce=secrets.token_hex(32)
    os.environ.update(LDR_WEB_HOST='127.0.0.1',LDR_WEB_PORT=str(PORT),DEEPDESK_INSTANCE_NONCE=nonce)
    mark('transport-import')
    import uvicorn
    import starlette.testclient as testclient_module
    require(testclient_module.httpx.__name__=='httpx2' and testclient_module.httpx.__version__=='2.13.1',
            'Unreviewed ASGI client backend')
    TestClient=testclient_module.TestClient
    calls=[]
    def in_process(app_name,**kwargs):
        mark('uvicorn-contract')
        require(not calls,'Unexpected repeated server startup')
        require(app_name=='local_deep_research.web.fastapi_app:app','Unexpected uvicorn app target')
        require(kwargs=={'host':'127.0.0.1','port':PORT,'workers':1,'log_level':'warning',
            'access_log':False,'server_header':False,'timeout_keep_alive':5,'timeout_graceful_shutdown':10,
            'proxy_headers':False,'forwarded_allow_ips':None},'Unreviewed uvicorn launch arguments')
        from local_deep_research.web.fastapi_app import app
        mark('lifespan-enter')
        with TestClient(ResponseCap(app),base_url=f'http://127.0.0.1:{PORT}',follow_redirects=False,
                        client=('127.0.0.1',54322)) as transport:
            mark('routes')
            exercise(Client(transport,nonce),config,phase)
            mark('lifespan-exit')
        calls.append('lifespan-entered-routes-checked-lifespan-exited')
    original=uvicorn.run
    uvicorn.run=in_process
    try:
        mark('wrapper-load')
        wrapper=runpy.run_path(str(engine),run_name='deepdesk_reviewed_asgi_wrapper')
        mark('wrapper-serve')
        wrapper['serve']()
    finally:
        uvicorn.run=original
    require(calls==['lifespan-entered-routes-checked-lifespan-exited'],'ASGI lifecycle did not complete exactly once')
    return {'status':'passed','phase':phase,'transport':'in-process-ASGI','checks':CHECKS[phase],
            'lifespan_completed':True,'real_http_tested':False,'client_backend':'httpx2-2.13.1','pid':os.getpid()}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--engine',type=Path,required=True)
    parser.add_argument('--runtime-python',type=Path)
    parser.add_argument('--offline-profile',type=Path)
    parser.add_argument('--fixture-root',type=Path)
    parser.add_argument('--immutable-root',type=Path)
    parser.add_argument('--phase',choices=(*CHECKS,'seed'))
    args=parser.parse_args()
    require(platform.system()=='Darwin' and platform.machine()=='arm64','macOS arm64 fixture only')
    engine=args.engine.resolve(strict=True)
    if args.phase:
        with redirect_stdout(sys.stderr):
            try:
                if args.phase=='seed':
                    mark('seed-main')
                    seed=runpy.run_path(str(Path(__file__).with_name('seed_fixture.py')),run_name='deepdesk_offline_seed')
                    seed['main']()
                    result={'status':'seeded','synthetic':True,'model_executed':False,'provider_queried':False}
                else:
                    result=run_worker(engine,args.phase)
            except BaseException as exc:
                diag.private_context(exc,args.phase)
                result=diag.failure(exc,args.phase,checkpoint,engine)
        print(json.dumps(result,sort_keys=True));return
    require(all((args.runtime_python,args.offline_profile,args.fixture_root,args.immutable_root)), 'Missing controller arguments')
    require(not args.fixture_root.exists() and args.fixture_root.parent.is_dir(),'Fixture root must be new')
    runtime_env=args.runtime_python.parent.parent.resolve(strict=True)
    runtime_python=runtime_env/'bin/python'
    immutable=args.immutable_root.resolve(strict=True)
    profile=args.offline_profile.resolve(strict=True)
    spec=importlib.util.spec_from_file_location('asgi_fixture_bounds',Path(__file__).with_name('bounded_runtime.py'))
    bounds=importlib.util.module_from_spec(spec);spec.loader.exec_module(bounds)
    with tempfile.TemporaryDirectory(prefix=args.fixture_root.name+'-',dir=args.fixture_root.parent) as temporary:
        root=Path(temporary).resolve();marker=secrets.token_hex(32)
        (root/'deepdesk-ci-fixture-only').write_text(marker)
        env={'PATH':'/usr/bin:/bin:/usr/sbin:/sbin','HOME':str(root),'TMPDIR':str(root),
            'LDR_DATA_DIR':str(root/'engine-data'),'LDR_BOOTSTRAP_ALLOW_UNENCRYPTED':'false',
            'LDR_ENABLE_FILE_LOGGING':'false','LDR_APP_DEBUG':'false','LDR_LOGURU_DIAGNOSE':'false',
            'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1','HF_HUB_DISABLE_TELEMETRY':'1',
            'ANONYMIZED_TELEMETRY':'false','PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD':'1',
            'TOKENIZERS_PARALLELISM':'false','OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1',
            'PYTHONDONTWRITEBYTECODE':'1','PYTHONNOUSERSITE':'1'}
        config={'fixture_marker':marker,'username':'deepdesk_fixture_'+secrets.token_hex(6),
            'password':'fixture1-&+=%'+secrets.token_hex(32),'research_id':str(uuid.uuid4())}
        prefix=['/usr/bin/sandbox-exec','-D','WORK_DIR='+str(root),'-D','IMMUTABLE_DIR='+str(immutable),
            '-D','READONLY_ENV='+str(runtime_env),'-f',str(profile),str(runtime_python),'-I']
        def invoke(command,timeout):
            return json.loads(bounds.run_bounded(prefix+command,input_data=json.dumps(config).encode(),
                env=env,cwd=root,work=root,disk_limit=128*1024**2,timeout=timeout,
                own_session=False,public_summary=False))
        def phase_result(phase,timeout):
            global active_phase
            active_phase=phase
            mark('worker-result')
            result=invoke([str(Path(__file__).resolve()),'--engine',str(engine),'--phase',phase],timeout)
            if result.get('status')=='failed': diag.validate(result)
            return result
        before=phase_result('register',120)
        if before.get('status')=='failed': print(json.dumps(before,sort_keys=True));return
        seeded=phase_result('seed',90)
        if seeded.get('status')=='failed': print(json.dumps(seeded,sort_keys=True));return
        require(seeded=={'status':'seeded','synthetic':True,'model_executed':False,'provider_queried':False},'Fixture seed failed')
        after=phase_result('persisted',120)
        if after.get('status')=='failed': print(json.dumps(after,sort_keys=True));return
        mark('worker-result')
        for result,phase in ((before,'register'),(after,'persisted')):
            require(result=={'status':'passed','phase':phase,'transport':'in-process-ASGI','checks':CHECKS[phase],
                'lifespan_completed':True,'real_http_tested':False,'client_backend':'httpx2-2.13.1','pid':result.get('pid')}
                and isinstance(result.get('pid'),int) and result['pid']>0,'Unexpected ASGI worker result')
        require(before['pid']!=after['pid'],'Expected distinct ASGI worker processes')
    print(json.dumps({'status':'passed','kind':'installed-authenticated-synthetic-ASGI',
        'checks':CHECKS['register']+CHECKS['persisted'],'transport':'in-process-ASGI','client_backend':'httpx2-2.13.1',
        'fresh_process_database_reopen':True,'lifespan_completed_twice':True,'real_http_tested':False,
        'tcp_listener_tested':False,'owned_listener_identity_tested':False,'native_transport_tested':False,
        'research_execution_tested':False,'model_loaded':False,'provider_queried':False},sort_keys=True))


if __name__=='__main__':
    try:
        main()
    except BaseException as exc:
        # Controller/pre-parser errors also receive only the same fixed schema.
        result=diag.failure(exc,active_phase,checkpoint,Path(__file__).with_name('engine_entry.py'))
        print(json.dumps(result,sort_keys=True))
