"""Reviewed Meson adapter: stable immutable discovery and isolated internal commands.
No downloaded module executes on import of this first-party file.
"""
import hashlib
from importlib import import_module
from pathlib import Path
import sys
sys.dont_write_bytecode=True
PINS={
 'mesonbuild/__init__.py':'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
 'mesonbuild/mesonmain.py':'6f6866cc9760e2ad9516ccdb3f3a42b3733dc3ce718e78e915ed2589b14f95b4',
 'mesonbuild/utils/universal.py':'28587e42fe4db670ee9334acefe65036f7c447d4345b20a38f6628a77dbbbda2',
 'mesonbuild/mesonlib.py':'6e1cfe1d2d5e43c74a65ada0857235d1d2d931ec9d4f3078df58e5784c25ccdb',
}

def wheel_from_interpreter(executable):
    runtime=Path(executable).resolve()
    if runtime.parts[-4:]!=('tree-python','python','bin','python3.12'):
        raise ValueError('fixed-layout-contract')
    return runtime.parents[3]/'tree-meson'

def validate_wheel(wheel):
    if not wheel.is_dir() or wheel.is_symlink():raise ValueError('wheel-layout-contract')
    for relative,sha in PINS.items():
        path=wheel/relative
        if not path.is_file() or path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest()!=sha:
            raise ValueError('wheel-bytes-contract')

def run(argv=None):
    # Fail before any wheel import if a generated helper ever drops isolation.
    if not (sys.flags.isolated and sys.flags.no_site and sys.flags.ignore_environment):
        print('deepdesk_meson_isolation_required',file=sys.stderr);return 81
    wheel=wheel_from_interpreter(sys.executable);validate_wheel(wheel)
    sys.path.insert(0,str(wheel))
    universal=import_module('mesonbuild.utils.universal')
    # In-place mutation retains the shared list object re-exported by mesonlib
    # and imported elsewhere. It changes invocation configuration, not source.
    universal.python_command[:]=[sys.executable,'-I','-S']
    mesonlib=import_module('mesonbuild.mesonlib')
    if mesonlib.python_command is not universal.python_command:
        print('deepdesk_meson_command_contract_failed',file=sys.stderr);return 82
    main=import_module('mesonbuild.mesonmain')
    return main.run(list(sys.argv[1:] if argv is None else argv),str(Path(__file__).resolve()))

if __name__=='__main__':
    try:status=run()
    except Exception:
        print('deepdesk_meson_launcher_contract_failed',file=sys.stderr);status=83
    raise SystemExit(status)
