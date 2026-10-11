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
        old=ast.parse(ORIGINAL.read_text());new=ast.parse((HERE/'engine_entry.py').read_text())
        old_defs={n.name:ast.dump(n) for n in old.body if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
        new_defs={n.name:ast.dump(n) for n in new.body if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
        self.assertEqual(set(old_defs),set(new_defs))
        self.assertEqual(hashlib.sha256(new_defs['install_managed_inference_provider'].encode()).hexdigest(),
                         '82275ccb3095d70ce7208b90cc7835501cf7c2ef82ec8d3662485779431593a6')
        for name in old_defs:
            if name not in {'self_test', 'install_managed_inference_provider'}:
                self.assertEqual(old_defs[name],new_defs[name],name)
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
