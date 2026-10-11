"""Run the reviewed shared build/bounds regression suite against the ASGI lane."""
import importlib.util
from pathlib import Path
import sys
import unittest
sys.dont_write_bytecode=True
root=Path(__file__).parent

def load(filename,name):
    spec=importlib.util.spec_from_file_location(name,root/filename)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

if __name__=='__main__':
    suite=load('test_runtime_api_helpers.py','shared_synthetic_runtime_tests')
    suite.stage=load('runtime_asgi_stage.py','asgi_stage_under_test')
    unittest.main(module=suite)
