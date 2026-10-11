"""Fixed-enum configure observations. Never emit input text, paths or exceptions."""
import importlib.util
import json
from pathlib import Path
import re

_spec = importlib.util.spec_from_file_location('iconv_safe_reads', Path(__file__).with_name('safe_reads.py'))
_reads = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_reads)

MAX_LOG = 2 * 1024**2
MAX_GENERATED = 1024**2
MAX_LINES = 65536
MAX_LINE = 16384
MAX_RECORD = 4096
PROBE_LINE = 26816
CACHE_VALUES = {
    'am_cv_func_iconv': {'yes', 'no, consider installing GNU libiconv'},
    'am_cv_func_iconv_works': {'yes', 'no', 'guessing yes', 'guessing no'},
    'am_cv_lib_iconv': {'yes', 'no'},
}


def unknown(reason='missing'):
    return {'status': reason, 'value': None}


def known(value):
    return {'status': 'known', 'value': value}


def lines(data, limit):
    if not isinstance(data, bytes) or len(data) > limit:
        return None
    result = data.splitlines()
    if len(result) > MAX_LINES or any(len(line) > MAX_LINE for line in result):
        return None
    return result


def one(values):
    if not values:
        return unknown()
    if len(values) != 1:
        return unknown('ambiguous')
    return values[0]


def cache_fact(content, key):
    candidates = []
    prefix = key.encode() + b'='
    for line in content:
        if line.startswith(prefix):
            value = line[len(prefix):]
            if value.startswith(b"'") and value.endswith(b"'") and len(value) >= 2:
                value = value[1:-1]
            allowed = {x.encode(): x for x in CACHE_VALUES[key]}
            candidates.append(known(allowed[value]) if value in allowed else unknown('rejected'))
    return one(candidates)


def header_fact(content):
    candidates = []
    for line in content:
        if re.match(rb'^\s*#\s*define\s+HAVE_ICONV(?:\s|$)', line):
            match = re.fullmatch(rb'\s*#\s*define\s+HAVE_ICONV\s+([01])\s*', line)
            candidates.append(known(bool(int(match[1]))) if match else unknown('rejected'))
        elif re.fullmatch(rb'\s*/\*\s*#undef HAVE_ICONV\s*\*/\s*', line):
            candidates.append(known(False))
    return one(candidates)


def make_fact(content, key):
    candidates = []
    prefix = key.encode() + b' = '
    for line in content:
        if line.startswith(prefix):
            value = line[len(prefix):].strip()
            if key == 'HAVE_ICONV':
                candidates.append(known(bool(int(value))) if value in (b'0', b'1') else unknown('rejected'))
            else:
                candidates.append(known({b'': 'empty', b'-liconv': 'sdk_link_flag'}.get(value, 'other_link_expression')))
    return one(candidates)


def probe_exits(content):
    start = f'configure:{PROBE_LINE}: ./conftest'.encode()
    status = re.compile(rb'^configure:' + str(PROBE_LINE).encode() + rb': \$\? = ([0-9]{1,3})$')
    pending, results, invalid = None, [], False
    for index, line in enumerate(content):
        if line == start:
            if pending is not None:
                invalid = True
            pending = index
            continue
        if pending is not None:
            match = status.fullmatch(line)
            if match:
                value = int(match[1])
                invalid = invalid or value > 255
                results.append(value)
                pending = None
            elif line.startswith(b'configure:') or index - pending > 32:
                invalid, pending = True, None
    if invalid or pending is not None or len(results) > 2:
        return unknown('rejected')
    return known(results) if results else unknown()


def parse(config_log, config_header, makefile):
    log = lines(config_log, MAX_LOG)
    header = lines(config_header, MAX_GENERATED)
    make = lines(makefile, MAX_GENERATED)
    facts = {key: cache_fact(log, key) if log is not None else unknown('unavailable_or_rejected') for key in CACHE_VALUES}
    facts['config_header_have_iconv'] = header_fact(header) if header is not None else unknown('unavailable_or_rejected')
    for key in ('HAVE_ICONV', 'LIBICONV', 'LTLIBICONV'):
        facts['make_' + key.lower()] = make_fact(make, key) if make is not None else unknown('unavailable_or_rejected')
    facts['working_iconv_run_exit_codes'] = probe_exits(log) if log is not None else unknown('unavailable_or_rejected')
    required = ('am_cv_func_iconv', 'am_cv_lib_iconv', 'config_header_have_iconv', 'make_have_iconv', 'make_libiconv', 'make_ltlibiconv')
    complete = all(facts[key]['status'] == 'known' for key in required)
    if facts['am_cv_func_iconv']['value'] == 'yes':
        complete = complete and facts['am_cv_func_iconv_works']['status'] == 'known' and facts['working_iconv_run_exit_codes']['status'] == 'known'
    result = {'schema': 1, 'facts_complete': complete, 'facts': facts,
              'raw_config_log_disclosed': False, 'causal_claim': 'none', 'working_iconv_source_line': PROBE_LINE}
    if len(json.dumps(result, sort_keys=True).encode()) > MAX_RECORD:
        raise ValueError('fixed_record_limit')
    return result


def collect(phase):
    phase = Path(phase)
    payloads = []
    for path, maximum in ((phase / 'config.log', MAX_LOG), (phase / 'config.h', MAX_GENERATED), (phase / 'lib/Makefile', MAX_GENERATED)):
        try:
            payloads.append(_reads.read(path, (phase,), maximum))
        except (OSError, _reads.ReadContractError):
            payloads.append(None)
    return parse(*payloads)
