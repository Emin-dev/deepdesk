"""Fixed source-libiconv export contract; no raw nm data is disclosed."""
import re

MAX_OUTPUT = 32 * 1024**2  # Existing aggregate captured-output ceiling.
REQUIRED = ('libiconv_open', 'libiconv', 'libiconv_close', 'libiconvctl',
            'libiconvlist', '_libiconv_version')
_LINE = re.compile(rb'^[0-9A-Fa-f]+[ \t]+[A-Za-z][ \t]+(_[A-Za-z_][A-Za-z0-9_]*)$')


def source_libiconv(output, required):
    """Match complete default nm -gU records and retain every required export."""
    if type(required) not in (tuple, list) or tuple(required) != REQUIRED:
        raise ValueError('fixed_export_requirement_mismatch')
    if type(output) is not bytes or len(output) > MAX_OUTPUT:
        raise ValueError('bounded_export_output_required')
    expected = {('_' + name).encode('ascii'): name for name in REQUIRED}
    found = set()
    for line in output.splitlines():
        match = _LINE.fullmatch(line)
        if match and match[1] in expected:
            found.add(match[1])
    missing = [name for name in REQUIRED if ('_' + name).encode('ascii') not in found]
    return {'status': 'failed' if missing else 'passed',
            'required_export_count': len(REQUIRED), 'missing_required_names': missing}
