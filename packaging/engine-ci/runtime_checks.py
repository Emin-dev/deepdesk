"""Proposed installed-runtime checks. No model is instantiated or requested."""
from __future__ import annotations
import argparse
from contextlib import redirect_stdout
import importlib
import importlib.metadata
import json
from pathlib import Path
import re
import runpy
import sys


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--identity-contract', type=Path, required=True)
    parser.add_argument('--wrapper', type=Path, required=True)
    args = parser.parse_args()
    expected = json.loads(args.identity_contract.read_text())
    actual = {}
    for distribution in importlib.metadata.distributions():
        name = re.sub(r'[-_.]+','-',distribution.metadata['Name']).lower()
        require(name not in actual, 'Duplicate installed distribution')
        actual[name] = distribution.version
    # pip is the pinned interpreter's venv bootstrap tool, not a runtime input.
    require({key:value for key,value in actual.items() if key != 'pip'} == expected,
            'Installed dependency identity/version set differs from reviewed lock')
    modules = ('fastapi','starlette','uvicorn','pydantic','sqlalchemy','sqlcipher3',
               'lxml.etree','cryptography','numpy','pandas','pyarrow','torch','faiss','sentence_transformers')
    with redirect_stdout(sys.stderr):
        for name in modules:
            importlib.import_module(name)
        wrapper = runpy.run_path(str(args.wrapper),run_name='deepdesk_reviewed_resource_check')
        root = wrapper['runtime_resources']()
    import torch
    require(torch.__version__ == '2.14.0', 'Selected PyPI Torch version differs')
    require(Path(torch.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()), 'Torch came from outside runtime')
    print(json.dumps({'status':'passed','kind':'installed-runtime-imports','torch_version':torch.__version__,
        'imported':list(modules),'provider_source_count':len(list((root / 'llm/providers/implementations').glob('*.py'))),
        'model_loaded':False,'provider_queried':False,'pdf_tested':False,'libmagic_tested':False}))


if __name__ == '__main__':
    main()
