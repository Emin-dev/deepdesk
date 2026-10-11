"""Synthetic secret-leak/schema/worker failures; no downloaded code execution."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.dont_write_bytecode=True
ROOT=Path(__file__).parent
spec=importlib.util.spec_from_file_location('diagnostic_fixture',ROOT/'smoke_asgi_authenticated.py')
api=importlib.util.module_from_spec(spec);spec.loader.exec_module(api);diag=api.diag


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.engine=self.root/'engine_entry.py';self.engine.write_text('# synthetic')
        (self.root/'deepdesk-ci-fixture-only').write_text('a'*64)

    def report(self,exc=ValueError('synthetic-secret'),phase='register',checkpoint='routes'):
        try: raise exc
        except BaseException as caught: return diag.failure(caught,phase,checkpoint,self.engine)

    def test_message_and_unlisted_type_never_published(self):
        SecretType=type('SyntheticSecretType',(Exception,),{})
        for exc in (ValueError('synthetic-secret'),SecretType('synthetic-secret')):
            value=self.report(exc);serialized=json.dumps(value)
            self.assertNotIn('secret',serialized.lower());self.assertNotIn('SyntheticSecretType',serialized)
            self.assertEqual(value['assertion_id'],'none')

    def test_known_assertion_becomes_fixed_id(self):
        value=self.report(RuntimeError('Registration session failed'))
        self.assertEqual(value['assertion_id'],diag.ASSERTIONS['Registration session failed'])
        self.assertNotIn('Registration session failed',json.dumps(value))

    def test_secret_filename_is_not_published(self):
        path=self.root/'synthetic-secret-file.py';path.write_text('raise RuntimeError("synthetic-secret")')
        try: exec(compile(path.read_text(),str(path),'exec'),{})
        except BaseException as exc: result=diag.failure(exc,'persisted','routes',self.engine)
        self.assertNotIn('synthetic-secret',json.dumps(result));self.assertEqual(result['source_category'],'unknown')

    def test_causal_error_is_fixed_category(self):
        try:
            try: raise ModuleNotFoundError('synthetic-secret')
            except Exception as exc: raise RuntimeError('wrapper-secret') from exc
        except BaseException as exc: value=diag.failure(exc,'register','wrapper-serve',self.engine)
        self.assertEqual(value['exception_type'],'RuntimeError');self.assertEqual(value['cause_type'],'ModuleNotFoundError')
        self.assertNotIn('secret',json.dumps(value))

    def test_exception_group_leaf_category(self):
        value=self.report(ExceptionGroup('synthetic-secret',[KeyError('synthetic-secret')]))
        self.assertEqual(value['exception_type'],'ExceptionGroup');self.assertEqual(value['cause_type'],'KeyError')

    def test_malformed_untrusted_reports_refused(self):
        base=self.report()
        cases=[{**base,'extra':'synthetic-secret'},{**base,'phase':'synthetic-secret'},
               {**base,'checkpoint':'synthetic-secret'},{**base,'exception_type':'synthetic-secret'},
               {**base,'cause_type':'synthetic-secret'},{**base,'assertion_id':'synthetic-secret'},
               {**base,'source_file':'/secret/file.py'},{**base,'source_file':'../secret.py'},
               {**base,'source_line':True},{**base,'source_line':100001},
               {**base,'source_file':'x'*10000},{**base,'source_category':'synthetic-secret'},
               {**base,'source_category':'installed-package','source_file':'local_deep_research/synthetic-secret.py'},
               {**base,'source_category':'stdlib','source_file':'synthetic-secret.py'}]
        for case in cases:
            with self.subTest(keys=tuple(case)),self.assertRaises(RuntimeError): diag.validate(case)

    def test_exact_source_catalog_allows_reviewed_file_only(self):
        value={**self.report(),'source_category':'installed-package',
               'source_file':'local_deep_research/web/fastapi_app.py','source_line':272}
        self.assertEqual(diag.validate(value),value)
        self.assertEqual(len(diag.SOURCE_FILES['installed-package']),1099)
        self.assertEqual(len(diag.SOURCE_FILES['stdlib']),1090)

    def test_private_context_stays_local(self):
        try: raise ValueError('synthetic-secret-private')
        except Exception as exc:
            console=io.StringIO()
            with patch.dict(os.environ,{'HOME':str(self.root)}),contextlib.redirect_stdout(console):
                diag.private_context(exc,'register')
        self.assertEqual(console.getvalue(),'')
        data=(self.root/'private-asgi-register.log').read_bytes()
        self.assertIn(b'synthetic-secret-private',data);self.assertLessEqual(len(data),1024**2)

    def test_worker_phase_failures_are_explicit_redacted_json(self):
        for phase,checkpoint in (('register','lifespan-enter'),('register','routes'),
                                 ('persisted','lifespan-exit')):
            def fail(*args): api.mark(checkpoint);raise ValueError('synthetic-secret')
            output=io.StringIO()
            with patch.object(sys,'argv',['fixture','--engine',str(self.engine),'--phase',phase]), \
                 patch.object(api.platform,'system',return_value='Darwin'),patch.object(api.platform,'machine',return_value='arm64'), \
                 patch.object(api,'run_worker',side_effect=fail),patch.dict(os.environ,{'HOME':str(self.root)}), \
                 contextlib.redirect_stdout(output):
                api.main()
            value=json.loads(output.getvalue());diag.validate(value)
            self.assertEqual((value['status'],value['phase'],value['checkpoint']),('failed',phase,checkpoint))
            self.assertNotIn('synthetic-secret',output.getvalue())

    def test_seed_failure_is_classified_without_changing_seed(self):
        def fail(): raise RuntimeError('Fixture account is not empty')
        output=io.StringIO()
        with patch.object(sys,'argv',['fixture','--engine',str(self.engine),'--phase','seed']), \
             patch.object(api.platform,'system',return_value='Darwin'),patch.object(api.platform,'machine',return_value='arm64'), \
             patch.object(api.runpy,'run_path',return_value={'main':fail}),patch.dict(os.environ,{'HOME':str(self.root)}), \
             contextlib.redirect_stdout(output):
            api.main()
        value=json.loads(output.getvalue());diag.validate(value)
        self.assertEqual(value['phase'],'seed');self.assertEqual(value['checkpoint'],'seed-main')
        self.assertEqual(value['assertion_id'],diag.ASSERTIONS['Fixture account is not empty'])

    def test_success_payload_unchanged(self):
        expected={'status':'passed','phase':'register'};output=io.StringIO()
        with patch.object(sys,'argv',['fixture','--engine',str(self.engine),'--phase','register']), \
             patch.object(api.platform,'system',return_value='Darwin'),patch.object(api.platform,'machine',return_value='arm64'), \
             patch.object(api,'run_worker',return_value=expected),contextlib.redirect_stdout(output): api.main()
        self.assertEqual(json.loads(output.getvalue()),expected)


if __name__=='__main__': unittest.main()
