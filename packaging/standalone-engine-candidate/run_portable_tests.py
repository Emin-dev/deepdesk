"""Run the published first-party stdlib/mock contract suite, never payload code."""
import os
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[2]
paths = sorted((root/'packaging/engine-ci').glob('test_*.py'))
paths += sorted((root/'packaging/standalone-engine-candidate').glob('test_*.py'))
paths += [root/'packaging/standalone-engine-candidate/libmagic-pilot/test_helpers.py']
for path in paths:
    subprocess.run([sys.executable, '-I', '-B', str(path)], check=True, cwd=root,
                   env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'}, timeout=120)
print('Portable first-party stdlib/mock contracts passed:', len(paths), 'files')
