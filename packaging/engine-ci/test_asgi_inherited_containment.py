"""Mocked inheritance-canary checks, without opening a network socket."""
import errno
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.dont_write_bytecode=True
ROOT=Path(__file__).parent
spec=importlib.util.spec_from_file_location('inheritance_fixture',ROOT/'smoke_asgi_authenticated.py')
api=importlib.util.module_from_spec(spec);spec.loader.exec_module(api)


class InheritedTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.scope=self.root/'scope';self.home=self.scope/'fixture'
        self.home.mkdir(parents=True);(self.home/'deepdesk-ci-fixture-only').write_text('marker')
        self.immutable=self.root/'immutable';self.immutable.mkdir();self.runtime=self.root/'runtime';self.runtime.mkdir()

    def canary(self,*,connect=errno.EPERM,bind=errno.EPERM,write=errno.EPERM,allow_write_index=None):
        events=[]
        class Socket:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def settimeout(self,value):events.append(('timeout',value))
            def connect_ex(self,address):events.append(('connect',address));return connect
            def bind(self,address):
                events.append(('bind',address))
                if bind:raise OSError(bind,'synthetic')
        real_open=Path.open
        def opening(path,*args,**kwargs):
            if path.name.startswith('deepdesk-inherited-denial-'):
                events.append(('write',path.parent))
                count=len([e for e in events if e[0]=='write'])
                if count==allow_write_index:return real_open(path,*args,**kwargs)
                raise OSError(write,'synthetic')
            return real_open(path,*args,**kwargs)
        env={'HOME':str(self.home),'DEEPDESK_CI_FIXTURE_SCOPE':str(self.scope),'DEEPDESK_CI_IMMUTABLE_ROOT':str(self.immutable)}
        with patch.dict(os.environ,env),patch.object(sys,'prefix',str(self.runtime)), \
             patch.object(api.socket,'socket',return_value=Socket()),patch.object(Path,'open',opening):
            api.verify_inherited_denial()
        return events

    def test_expected_denials_and_all_targets(self):
        events=self.canary()
        self.assertEqual([e[1] for e in events if e[0]=='connect'],[('192.0.2.1',9),('127.0.0.1',54321)])
        self.assertEqual([e[1] for e in events if e[0]=='bind'],[('127.0.0.1',54321)])
        self.assertEqual([e[1] for e in events if e[0]=='write'],[self.root,self.immutable,self.runtime,ROOT.resolve()])

    def test_access_denied_also_accepted(self):self.canary(connect=errno.EACCES,bind=errno.EACCES,write=errno.EACCES)

    def test_connection_refused_is_not_containment(self):
        with self.assertRaisesRegex(RuntimeError,'connect denial'):self.canary(connect=errno.ECONNREFUSED)

    def test_connect_timeout_is_not_containment(self):
        with self.assertRaisesRegex(RuntimeError,'connect denial'):self.canary(connect=errno.ETIMEDOUT)

    def test_successful_connect_refused(self):
        with self.assertRaisesRegex(RuntimeError,'connect denial'):self.canary(connect=0)

    def test_successful_bind_refused(self):
        with self.assertRaisesRegex(RuntimeError,'bind denial'):self.canary(bind=0)

    def test_address_in_use_is_not_containment(self):
        with self.assertRaisesRegex(RuntimeError,'bind denial'):self.canary(bind=errno.EADDRINUSE)

    def test_missing_path_is_not_write_denial(self):
        with self.assertRaisesRegex(RuntimeError,'write denial'):self.canary(write=errno.ENOENT)

    def test_any_allowed_protected_write_fails(self):
        # Use only temporary roots; never simulate a successful repository write.
        for index in (1,2,3):
            with self.subTest(index=index),self.assertRaisesRegex(RuntimeError,'write denial'):
                self.canary(allow_write_index=index)

    def test_wrong_fixture_parent_refused(self):
        with patch.dict(os.environ,{'HOME':str(self.home),'DEEPDESK_CI_FIXTURE_SCOPE':str(self.root),
                                   'DEEPDESK_CI_IMMUTABLE_ROOT':str(self.immutable)}), \
             self.assertRaisesRegex(RuntimeError,'boundary'):
            api.verify_inherited_denial()

    def test_single_profile_and_narrowed_outer_scope_contract(self):
        fixture=(ROOT/'smoke_asgi_authenticated.py').read_text()
        self.assertNotIn("prefix=['/usr/bin/sandbox-exec'",fixture)
        self.assertIn("prefix=[str(runtime_python),'-I']",fixture)
        self.assertIn('env=env,cwd=root,work=root.parent,disk_limit=128*1024**2',fixture)
        stage=(ROOT/'runtime_asgi_stage.py').read_text()
        self.assertIn("fixture_scope = work / 'asgi-fixture-scope'",stage)
        self.assertIn('cwd=fixture_scope,writable=fixture_scope,timeout=360',stage)
        self.assertIn("'WORK_DIR=' + str(writable)",stage)
        self.assertIn("verify_inherited_denial()\n                if args.phase=='seed':",fixture)


if __name__=='__main__':unittest.main()
