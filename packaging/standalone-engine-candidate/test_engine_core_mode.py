"""First-party AST and mocked branch tests; no installed engine code runs."""
import ast
import hashlib
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import runpy
import tempfile
import types
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
ORIGINAL=HERE.parent/'engine_entry.py'

class CoreModeTests(unittest.TestCase):
    def test_production_functions_ast_unchanged(self):
        old=ast.parse(ORIGINAL.read_text());source=(HERE/'engine_entry.py').read_text();new=ast.parse(source)
        old_defs={n.name:ast.dump(n) for n in old.body if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
        new_defs={n.name:ast.dump(n) for n in new.body if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
        self.assertEqual(set(old_defs),set(new_defs))
        # Pin reviewed source bytes, not ast.dump's host-version-specific format.
        managed_defs=[n for n in new.body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name=='install_managed_inference_provider']
        self.assertEqual(len(managed_defs), 1, 'Exactly one reviewed managed provider is required')
        managed=managed_defs[0]
        self.assertIsInstance(managed, ast.FunctionDef)
        self.assertEqual(managed.decorator_list, [], 'Reviewed managed provider must have no decorators')
        self.assertEqual(hashlib.sha256(ast.get_source_segment(source,managed).encode()).hexdigest(),
                         '5b004b96378ceb0ebd347d9e7f3055ce11ae8dcbc1003e07cf634b704570423e')
        self.assertEqual(hashlib.sha256(source.encode()).hexdigest(),
                         'ad8fc34f04809ad9b6a43922d47709a112e6aaedf04ddc427cae968edc5264d2')
        for name in old_defs:
            if name not in {'self_test', 'install_managed_inference_provider'}:
                self.assertEqual(old_defs[name],new_defs[name],name)
    def test_function_pin_independent_of_ast_dump_format(self):
        original_dump=ast.dump
        with patch.object(ast,'dump',side_effect=lambda node: 'changed-host-format:'+original_dump(node)):
            self.test_production_functions_ast_unchanged()
    def test_added_decorator_rejected_without_execution(self):
        target=HERE/'engine_entry.py';source=target.read_text()
        decorated=source.replace('def install_managed_inference_provider(',
                                 '@(lambda function: (lambda *args, **kwargs: None))\ndef install_managed_inference_provider(',1)
        self.assertNotEqual(source,decorated)
        original_read=Path.read_text
        def read(path,*args,**kwargs):
            return decorated if path==target else original_read(path,*args,**kwargs)
        with patch.object(Path,'read_text',read),self.assertRaisesRegex(AssertionError,'must have no decorators'):
            self.test_production_functions_ast_unchanged()
    def test_duplicate_definition_rejected_without_execution(self):
        target=HERE/'engine_entry.py';source=target.read_text()
        duplicated=source+'\ndef install_managed_inference_provider():\n    pass\n'
        original_read=Path.read_text
        def read(path,*args,**kwargs):
            return duplicated if path==target else original_read(path,*args,**kwargs)
        with patch.object(Path,'read_text',read),self.assertRaisesRegex(AssertionError,'Exactly one reviewed'):
            self.test_production_functions_ast_unchanged()
    def test_same_name_class_rejected_without_execution(self):
        target=HERE/'engine_entry.py';source=target.read_text()
        duplicated=source+'\nclass install_managed_inference_provider:\n    pass\n'
        original_read=Path.read_text
        def read(path,*args,**kwargs):
            return duplicated if path==target else original_read(path,*args,**kwargs)
        with patch.object(Path,'read_text',read),self.assertRaisesRegex(AssertionError,'Exactly one reviewed'):
            self.test_production_functions_ast_unchanged()
    def run_mode(self,core):
        module=runpy.run_path(str(HERE/'engine_entry.py'),run_name='synthetic_wrapper_contract')
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);providers=root/'llm/providers/implementations';providers.mkdir(parents=True);(providers/'test.py').write_text('# synthetic')
            imported=[]
            class Cursor:
                def __init__(self,value):self.value=value
                def fetchone(self):return self.value
            class Connection:
                def __init__(self,path):Path(path).write_bytes(b'Encrypted synthetic test bytes')
                def execute(self,sql):return Cursor(('4.7.0 community',) if sql=='PRAGMA cipher_version' else ('encrypted',))
                def commit(self):pass
                def close(self):pass
            cipher=types.ModuleType('sqlcipher3');cipher.dbapi2=types.SimpleNamespace(connect=Connection)
            fn=module['self_test'];fn.__globals__['runtime_resources']=lambda:root
            out=io.StringIO()
            with patch.dict('sys.modules',{'sqlcipher3':cipher}),patch('importlib.import_module',side_effect=lambda name:imported.append(name)),redirect_stdout(out):
                fn(core_only=core)
            return imported,json.loads(out.getvalue())
    def test_explicit_core_imports_and_label(self):
        imported,result=self.run_mode(True)
        self.assertEqual(len(imported),14);self.assertNotIn('weasyprint',imported)
        self.assertEqual(result['kind'],'packaging-core-self-test')
        self.assertFalse(result['network_research_tested']);self.assertFalse(result['authenticated_api_tested'])
    def test_original_full_imports_preserved(self):
        imported,result=self.run_mode(False)
        self.assertEqual(len(imported),15);self.assertEqual(imported[-1],'weasyprint')
        self.assertEqual(result['kind'],'packaging-self-test')

if __name__=='__main__':unittest.main()
