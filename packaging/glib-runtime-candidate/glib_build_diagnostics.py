"""Bounded, first-party interpretation of already-private build output.

No execution, network, environment reads, source reads, or raw stream forwarding.
Public names come only from a receipt-bound catalog of the pinned pkgconf input.
Diagnostic text is emitted only through reviewed grammars with public operands;
unknown structured operands are replaced individually. Failed-build stderr also
has a bounded excerpt that preserves unfamiliar prose after explicit redaction.
Observed errors and per-stream order are evidence, not a root-cause assertion.
"""
from __future__ import annotations
import json
from collections import deque
from pathlib import Path
import re
import shlex

BUILD_PHASES = ('pkgconf-build', 'pcre2-build', 'gettext-headers',
                'gettext-gnulib-build', 'gettext-libintl-build',
                'libffi-configure', 'libffi-build', 'libtextstyle-configure', 'libtextstyle-build',
                'gettext-tools-configure', 'gettext-tools-gnulib', 'gettext-tools-headers',
                'gettext-tools-build', 'glib-configure', 'glib-build',
                'glib-probe-compile', 'glib-module-compile', 'glib-probe-run',
                'ncurses-probe-compile', 'ncurses-probe-run')
MAX_STREAM_BYTES = 8 * 1024**2  # Existing aggregate capture limit; never recapture.
MAX_LINES = 32768
MAX_LINE_BYTES = 8192
MAX_EVENTS = 6
MAX_MESSAGE = 240
MAX_REPORT_BYTES = 16384
PIN = '943f0bc88bcaeceb630b00262e2a8ad5ea4fac3fba72a4267d8b9ec6b35d1194'
SEVERITIES = ('fatal error', 'error', 'warning', 'note')
SOURCE_DIAGNOSTIC = re.compile(r'^(.+?):([1-9][0-9]{0,5})(?::([1-9][0-9]{0,3}))?: (fatal error|error|warning|note): (.+)$')
DRIVER_DIAGNOSTIC = re.compile(r'^(?:[^ \t:]+/)?(clang(?:-[0-9]{1,2})?|cc|ld|as): (fatal error|error|warning|note): (.+)$')
MAKE_DIAGNOSTIC = re.compile(r'^make(?:\[[0-9]{1,3}\])?: \*\*\* (.+)$')
DENIALS = {'Operation not permitted': 'operation_not_permitted', 'Permission denied': 'permission_denied',
           'No such file or directory': 'file_not_found', 'Read-only file system': 'read_only_filesystem',
           'No space left on device': 'no_space_left', 'Too many open files': 'file_descriptor_limit'}
COMMANDS = {'clang': 'compiler_driver', 'cc': 'compiler_driver', 'ld': 'linker', 'as': 'assembler',
            'ar': 'archiver', 'ranlib': 'archive_indexer', 'libtool': 'libtool',
            'automake': 'automake_regeneration', 'autoconf': 'autoconf_regeneration',
            'autoheader': 'autoheader_regeneration', 'aclocal': 'aclocal_regeneration',
            'make': 'make', 'sh': 'shell'}


def _load_catalog(path):
    p = Path(path)
    if p.is_symlink() or p.stat().st_size > 256 * 1024:
        raise ValueError()
    catalog = json.loads(p.read_text())
    if catalog['schema'] != 1 or catalog['archive_sha256'] != PIN or catalog['input'] != 'pkgconf':
        raise ValueError()
    return catalog


class Context:
    def __init__(self, phase, catalog, immutable, directory, control):
        self.catalog = catalog
        self.pkgconf = phase == 'pkgconf-build'
        self.source_root = str(Path(immutable) / catalog['source_root'])
        self.roots = ((self.source_root, 'immutable_pkgconf_source'),
                      (str(immutable), 'immutable_input_or_provider'),
                      (str(directory), 'mutable_build_phase'), (str(control), 'reviewed_control'))
        self.directory = str(directory)
        self.identifiers = set(catalog['public_identifiers']) if self.pkgconf else set()
        self.headers = set(catalog['public_headers']) if self.pkgconf else set()

    def relative(self, value, root):
        # Lexical matching only: never follow a child-supplied filesystem path.
        if '..' in value.split('/') or '\\' in value or any(ord(c) < 32 for c in value):
            return None
        if value.startswith(root + '/'):
            return value[len(root)+1:]
        if value.startswith('./'):
            value = value[2:]
        return value if not value.startswith('/') else None

    def location(self, value, line, column):
        if not self.pkgconf:
            return None
        name = self.relative(value, self.source_root)
        item = self.catalog['files'].get(name)
        if item is None or not 1 <= line <= item['line_count']:
            return None
        result = {'file': name.rsplit('/', 1)[-1], 'role': item['role'],
                  'source_sha256': item['sha256'], 'line': line}
        if column is not None and 1 <= column <= 4096:
            result['column'] = column
        return result

    def target(self, value):
        if not self.pkgconf:
            return {'target_status': 'unreviewed_target'}
        name = self.relative(value, self.directory)
        if name not in self.catalog['targets']:
            name = self.relative(value, self.source_root)
        item = self.catalog['targets'].get(name)
        if item is None:
            return {'target_status': 'unreviewed_target'}
        return {'target_status': 'allowlisted', 'target': name, 'target_role': item['role'],
                'rule_file': 'Makefile.in', 'rule_line': item['rule_line']}

    def path_operand(self, value):
        """Retain only an allowlisted target/name or a fixed path role."""
        target = self.target(value)
        if target['target_status'] == 'allowlisted':
            return target['target']
        if self.pkgconf:
            output = self.relative(value, self.directory)
            if output in self.catalog['outputs']:
                return output
            name = self.relative(value, self.source_root)
            if name in self.catalog['files']:
                return '[source:' + name.rsplit('/', 1)[-1] + ']'
        if '..' not in value.split('/') and '\\' not in value:
            for root, role in self.roots:
                if value == root or value.startswith(root + '/'):
                    return '[' + role + ']'
        return '[unreviewed-path]'

    def identifier(self, value):
        return value if value in self.identifiers else '[unreviewed-identifier]'


def _command_role(token):
    base = token.rsplit('/', 1)[-1]
    if base in COMMANDS:
        return COMMANDS[base]
    for name in ('clang', 'automake', 'aclocal', 'autoconf', 'autoheader'):
        if re.fullmatch(re.escape(name) + r'-[0-9]{1,2}(?:\.[0-9]{1,2})?', base):
            return COMMANDS[name]
    return 'unreviewed_command'


def _message(message, context):
    """Return only fixed grammar text with individually reviewed/redacted operands."""
    operand_patterns = (
        (r"use of undeclared identifier '([^']+)'", 'undeclared_identifier', "use of undeclared identifier '{}'"),
        (r"unknown type name '([^']+)'", 'unknown_type', "unknown type name '{}'"),
        (r"no member named '([^']+)' in '([^']+)'", 'unknown_member', "no member named '{}' in '{}'"),
        (r"call to undeclared function '([^']+)'; ISO C99 and later do not support implicit function declarations(?: \[-Wimplicit-function-declaration\])?", 'implicit_function_declaration', "call to undeclared function '{}'; ISO C99 and later do not support implicit function declarations"),
        (r"conflicting types for '([^']+)'", 'conflicting_types', "conflicting types for '{}'"),
        (r"redefinition of '([^']+)'", 'redefinition', "redefinition of '{}'"),
    )
    for pattern, category, template in operand_patterns:
        match = re.fullmatch(pattern, message)
        if match:
            return category, template.format(*(context.identifier(x) for x in match.groups()))
    match = re.fullmatch(r"'([^']+)' file not found", message)
    if match:
        operand = match[1] if match[1] in context.headers else '[unreviewed-header]'
        return 'missing_header', "'{}' file not found".format(operand)
    match = re.fullmatch(r"(unable to open output file|cannot open file|unable to open file) '([^']+)': '?([^']+)'?", message)
    if match and match[3] in DENIALS:
        return 'file_access_' + DENIALS[match[3]], "{} '{}': {}".format(match[1], context.path_operand(match[2]), match[3])
    match = re.fullmatch(r"unable to rename temporary '([^']+)' to output file '([^']+)': '?([^']+)'?", message)
    if match and match[3] in DENIALS:
        return 'file_access_' + DENIALS[match[3]], "unable to rename temporary '{}' to output file '{}': {}".format(context.path_operand(match[1]), context.path_operand(match[2]), match[3])
    match = re.fullmatch(r'(unable to execute command: posix_spawn failed|unable to make temporary file): (.+)', message)
    if match and match[2] in DENIALS:
        category = 'compiler_spawn_' if match[1].startswith('unable to execute') else 'compiler_temporary_file_'
        return category + DENIALS[match[2]], match[1] + ': ' + match[2]
    match = re.fullmatch(r"(unknown argument|unsupported option): '([^']+)'", message)
    if match:
        return 'unsupported_compiler_option', match[1] + ': [unreviewed-option]'
    match = re.fullmatch(r'(linker|assembler) command failed with exit code ([0-9]{1,3})(?: \(use -v to see invocation\))?', message)
    if match:
        return match[1] + '_command_failed', match[1] + ' command failed with exit code ' + match[2]
    match = re.fullmatch(r"library not found for -l[^ ]+", message)
    if match:
        return 'link_library_not_found', 'library not found: [unreviewed-library]'
    if message in ('expected expression', "expected ';' after expression", 'too many errors emitted, stopping now [-ferror-limit=]', 'no input files'):
        return 'compiler_syntax_or_input_error', message
    return 'unrecognized_diagnostic', '[message withheld: no reviewed grammar]'


def _event(line, context):
    match = SOURCE_DIAGNOSTIC.fullmatch(line)
    if match:
        location, number, column, severity, message = match.groups()
        category, safe = _message(message, context)
        result = {'severity': severity, 'category': category, 'command_role': 'compiler', 'message': safe[:MAX_MESSAGE]}
        source = context.location(location, int(number), int(column) if column else None)
        if source is not None:
            result['source'] = source
        else:
            result['source_status'] = 'unreviewed_or_out_of_range'
        return result
    match = DRIVER_DIAGNOSTIC.fullmatch(line)
    if match:
        tool, severity, message = match.groups(); category, safe = _message(message, context)
        return {'severity': severity, 'category': category, 'command_role': _command_role(tool), 'message': safe[:MAX_MESSAGE]}
    match = re.fullmatch(r'(fatal error|error|warning|note): (.+)', line)
    if match:
        category, safe = _message(match[2], context)
        return {'severity': match[1], 'category': category, 'command_role': 'unattributed_diagnostic', 'message': safe[:MAX_MESSAGE]}
    match = re.fullmatch(r'libtool:\s+(?:(?:link|compile):\s*)?(fatal error|error|warning|note):\s*(.+)', line)
    if match:
        category, safe = _message(match[2], context)
        return {'severity': match[1], 'category': category, 'command_role': 'libtool', 'message': safe[:MAX_MESSAGE]}
    match = MAKE_DIAGNOSTIC.fullmatch(line)
    if match:
        body = match[1]
        if body in ('Waiting for unfinished jobs....', 'Waiting for unfinished jobs...'):
            return {'severity': 'note', 'category': 'make_waiting_for_jobs', 'command_role': 'make'}
        failed = re.fullmatch(r'\[([^\]]+)\] (Error ([0-9]{1,3})|Killed|Segmentation fault)( \(ignored\))?', body)
        if failed:
            target = re.sub(r'^Makefile:[0-9]{1,6}: ', '', failed[1])
            result = {'severity': 'warning' if failed[4] else 'error', 'category': 'make_recipe_ignored' if failed[4] else 'make_recipe_failed',
                      **context.target(target), 'make_failure': not bool(failed[4])}
            if failed[3]:
                result['recipe_exit'] = int(failed[3])
            else:
                result['termination'] = 'killed' if failed[2] == 'Killed' else 'segmentation_fault'
            return result
        missing = re.fullmatch(r"No rule to make target [`']([^`']+)'(?:, needed by [`']([^`']+)')?\.\s+Stop\.", body)
        if missing:
            result = {'severity': 'error', 'category': 'make_no_rule', 'make_failure': True, **context.target(missing[1])}
            if missing[2]:
                result['needed_by'] = context.target(missing[2])
            return result
        return {'severity': 'error', 'category': 'make_unrecognized_failure', 'make_failure': True,
                'target_status': 'unreviewed_target', 'message': '[message withheld: no reviewed grammar]'}
    # Context-bound shell/make command errors; a standalone permission marker is ignored.
    match = re.fullmatch(r'(?:make(?:\[[0-9]{1,3}\])?|(?:/bin/)?sh): (?:(?:line )?[0-9]{1,6}: )?(.+?): (Operation not permitted|Permission denied|No such file or directory|command not found)', line)
    if match:
        command, reason = match.groups()
        return {'severity': 'error', 'category': 'command_' + DENIALS.get(reason, 'not_found'),
                'command_role': _command_role(command), 'message': 'command failed: ' + reason}
    match = re.fullmatch(r'Undefined symbols for architecture (arm64|x86_64):', line)
    if match:
        return {'severity': 'error', 'category': 'linker_undefined_symbols', 'command_role': 'linker',
                'message': 'Undefined symbols for architecture ' + match[1]}
    return None


def _observed_command(line, context):
    """Fixed role and exact public target only. No command text or argv is retained."""
    if line.startswith('libtool: compile: '):
        line = line[len('libtool: compile: '):]
    elif line.startswith('libtool: link: '):
        line = line[len('libtool: link: '):]
    try:
        words = shlex.split(line)
    except ValueError:
        return None
    if not words or len(words) > 512:
        return None
    role = _command_role(words[0])
    if role not in ('compiler_driver', 'linker', 'assembler', 'archiver', 'archive_indexer'):
        return None
    result = {'command_role': role, 'relationship': 'observed_command_only_not_proven_failed'}
    if '-o' in words:
        index = words.index('-o')
        if index + 1 < len(words):
            result.update(context.target(words[index+1]))
            # A target role describes the Makefile rule, not a proven failing executable.
    return result


def _stream(data, context):
    result = {'severity_counts': dict.fromkeys(SEVERITIES, 0), 'events': [], 'first_error': None,
              'first_failing_make_target': None, 'last_observed_command': None,
              'omitted_events': 0, 'rejected_lines': 0, 'scan_truncated': False}
    if not isinstance(data, bytes):
        result['input_status'] = 'invalid_stream_type'
        return result
    if len(data) > MAX_STREAM_BYTES:
        result['scan_truncated'] = True
    stop = min(len(data), MAX_STREAM_BYTES); start = 0; count = 0
    while start < stop and count < MAX_LINES:
        end = data.find(b'\n', start, stop)
        if end < 0:
            end = stop
            # Never parse a partial final line from a truncated stream.
            if stop < len(data):
                break
        count += 1
        if end-start > MAX_LINE_BYTES:
            result['rejected_lines'] += 1; start = end+1; continue
        raw = data[start:end]; start = end+1
        if raw.endswith(b'\r'):
            raw = raw[:-1]
        if re.search(rb'[^\x20-\x7e\t]', raw) or b'::' in raw:
            result['rejected_lines'] += 1; continue
        line = raw.decode('ascii').strip()
        event = _event(line, context)
        if event is None:
            observed = _observed_command(line, context)
            if observed:
                result['last_observed_command'] = {'stream_line': count, **observed}
            continue
        event['stream_line'] = count
        result['severity_counts'][event['severity']] += 1
        if event['severity'] in ('fatal error', 'error') and result['first_error'] is None:
            result['first_error'] = event
        if event.get('make_failure') and result['first_failing_make_target'] is None:
            result['first_failing_make_target'] = event
        if len(result['events']) < MAX_EVENTS:
            result['events'].append(event)
        else:
            result['omitted_events'] += 1
    if start < stop:
        result['scan_truncated'] = True
    result['scanned_lines'] = count
    return result


# Bounded stderr-only review surface. Full stdout/stderr remain private and unchanged.
MAX_EXCERPT_LINES = 64
MAX_EXCERPT_LINE_CHARS = 512
MAX_EXCERPT_BYTES = 6144  # Encoded JSON, including excerpt metadata.
EXCERPT_HEAD_LINES = 16
SAFE_TOOL_BASENAMES = frozenset(('clang','clang++','cc','gcc','ld','as','ar','ranlib','nm',
    'sed','grep','egrep','fgrep','sort','uniq','cut','tr','mkdir','mv','cp','rm','touch',
    'xcrun','xcodebuild','make','libtool','sh','bash','config.status','configure','missing','depcomp','ltmain.sh'))
CREDENTIAL_KEY = r'(?:authorization|proxy-authorization|cookie|set-cookie|password|passwd|credentials?|client[_-]?secret|api[_-]?key|access[_-]?key|access[_-]?token|refresh[_-]?token|id[_-]?token|secret|token|(?:aws|github|gh|openai|slack)[_-][a-z0-9_-]*(?:key|token|secret))'
# Optional plain or backslash-escaped quotes cover JSON and quoted field labels.
CREDENTIAL_LABEL = re.compile(r'(?i)(?<![A-Za-z0-9_])(?:\\?["\'])?' + CREDENTIAL_KEY + r'(?:\\?["\'])?(?![A-Za-z0-9_])(?:[ \t]*[:=][ \t]*|[ \t]+(?=(?:\\?["\']|bearer\b|basic\b))|[ \t]+(?=[^ \t]+$))')
TOKEN_PATTERN = re.compile(r'(?i)\b(?:gh[pousr]_[A-Za-z0-9_]{8,}|github_pat_[A-Za-z0-9_]{8,}|glpat-[A-Za-z0-9_-]{8,}|xox[baprs]-[A-Za-z0-9-]{8,}|sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{8,}|AIza[A-Za-z0-9_-]{20,}|(?:AKIA|ASIA)[A-Z0-9]{16}|eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,})\b')
URL_PATTERN = re.compile(r'(?i)\b[a-z][a-z0-9+.-]{1,20}://[^\s<>\'"`]+')
ANSI_PATTERN = re.compile(r'\x1b(?:\][^\x07\x1b]*(?:\x07|\x1b\\)|\[[0-9;:]*m)')
OPAQUE_PATTERN = re.compile(r'(?<![A-Za-z0-9_])[A-Za-z0-9_+/=-]{32,}(?![A-Za-z0-9_])')
PATH_PATTERN = re.compile(r"(?<![A-Za-z0-9_\]])(?:[A-Za-z]:[\\/][^\s\'\"<>`|;,()]+|(?:~[A-Za-z0-9_.-]*|\.\.?|)/[^\s\'\"<>`|;,()]+|[A-Za-z0-9_.-]+(?:/[^\s\'\"<>`|;,():]+)+)")


def _excerpt_path(value, context):
    """Never return a private prefix; preserve exact public suffixes when useful."""
    suffix = ''
    # Diagnostic line/column trailers do not belong to the filesystem path.
    match = re.search(r'(:[0-9]{1,6}(?::[0-9]{1,4})?)$', value)
    if match:
        suffix = match[1]; value = value[:match.start()]
    value = value.rstrip(':')
    if value.startswith(('/usr/bin/', '/bin/')) and value.rsplit('/',1)[-1] in SAFE_TOOL_BASENAMES:
        return value + suffix
    if value in context.catalog['files'] or value in context.catalog['targets'] or value in context.catalog['outputs']:
        return value + suffix if context.pkgconf else '[relative-path]' + suffix
    roots = ((context.source_root, 'pkgconf-source'), (context.directory+'/tmp','phase-tmp'),
             (context.directory+'/home','phase-home'), *context.roots[1:])
    for root, role in roots:
        if value == root or value.startswith(root+'/'):
            relative = value[len(root):].lstrip('/')
            public = relative in context.catalog['files'] or relative in context.catalog['targets'] or relative in context.catalog['outputs']
            # A known source/output suffix is useful; private directories are never retained.
            return '['+role+']' + ('/'+relative if context.pkgconf and public else '') + suffix
    role = 'path'
    if value.startswith(('/Users/runner/', '/home/runner/')): role = 'runner-path'
    elif value.startswith(('/private/var/folders/','/var/folders/','/private/tmp/','/tmp/')): role = 'runner-tmp'
    elif value.startswith(('/Applications/','/Library/Developer/')): role = 'toolchain-path'
    elif value.startswith(('/Users/','/home/','~')): role = 'home-path'
    elif re.match(r'^[A-Za-z]:[\\/]',value): role = 'windows-path'
    elif not value.startswith('/'): role = 'relative-path'
    base = re.split(r'[\\/]',value)[-1]
    if base in SAFE_TOOL_BASENAMES:
        return '['+role+']/'+base+suffix
    return '['+role+']'+suffix


def _normalize_excerpt_line(raw):
    """Remove terminal controls before inspecting the visible structural syntax."""
    # Normalize eight-bit CSI/OSC/ST spellings too; unrecognized escape forms
    # are omitted as a whole line, not converted into a misleading visible prefix.
    raw = raw.replace(b'\x9b', b'\x1b[').replace(b'\x9d', b'\x1b]').replace(b'\x9c', b'\x1b\\')
    value = raw.decode('utf-8', 'replace')
    value = ANSI_PATTERN.sub('', value)
    if '\x1b' in value:
        return None  # An incomplete/unknown escape cannot hide a command prefix.
    return ''.join(c if 32 <= ord(c) <= 126 else (' ' if c == '\t' else '') for c in value)


def _suppressed_structure(value):
    """Whole-line suppression for command/env contexts; never expose their argv."""
    command = value.strip()
    wrapped = re.match(r'^libtool:\s+(?:link|compile|execute):\s*(.*)$', command)
    if wrapped:
        command = wrapped[1]
        # libtool's explicit command-echo context is not a free-form diagnostic.
        # Real severity messages are retained, including unfamiliar error prose.
        if re.match(r'^(?:fatal error|error|warning|note):', command):
            return None
        return '[command-line redacted]'
    if re.match(r'^\++(?:\s|(?=[A-Za-z_/\'"(]))', command):
        return '[shell-trace redacted]'
    command = command.lstrip('(').lstrip()
    if re.match(r'^[A-Za-z_][A-Za-z0-9_]*\s*=', command):
        return '[environment-assignment redacted]'
    try:
        words = shlex.split(command)
    except ValueError:
        # Malformed quoted commands still cannot expose their remaining operands.
        leading = re.match(r'''["']?([^ \t"']+)''', command)
        words = [leading[1]] if leading else []
        if command.startswith(('"', "'")) and '/' in command:
            return '[malformed-command redacted]'
    if not words:
        return None
    first = words[0]
    if re.match(r'^[A-Za-z_][A-Za-z0-9_]*\s*=', first):
        return '[environment-assignment redacted]'
    base = first.rsplit('/', 1)[-1]
    wrappers = {'env', 'command', 'exec', 'builtin', 'export', 'declare', 'readonly',
                'typeset', 'time', 'nice', 'nohup', 'stdbuf', 'xargs', 'sudo', 'doas',
                'python', 'python3', 'perl', 'ruby', 'awk', 'gawk', 'dash', 'zsh',
                'echo', 'printf', 'cat', 'head', 'tail', 'wc', 'install', 'ln', 'chmod',
                'basename', 'dirname', 'readlink', 'realpath', 'test', 'true', 'false',
                'printenv', 'set', 'unset', 'local', 'read', 'eval', 'source', '.',
                'ksh', 'fish', 'ccache', 'sccache', 'timeout', 'cmake', 'ninja'}
    if base in SAFE_TOOL_BASENAMES or base in wrappers or re.fullmatch(r'(?:clang|gcc|cc|python|python3)(?:-[0-9.]+|[0-9.]+)', base):
        return '[command-line redacted]'
    return None


def _redact_compiler_defines(value):
    """No operand parsing: a recognized -D makes the entire suffix private."""
    match = re.search(r'(?<![A-Za-z0-9_])-D', value)
    return value[:match.start()] + '[compiler-define redacted]' if match else value


def _sanitize_excerpt_line(raw, context):
    """Redact values, not unknown error prose. This is not a raw-output fallback."""
    value = _normalize_excerpt_line(raw)
    if value is None:
        return '[malformed terminal control redacted]'
    suppressed = _suppressed_structure(value)
    if suppressed is not None:
        return suppressed
    value = value.replace('::','[workflow-marker]')
    # URLs can contain userinfo/query credentials and are always replaced as a unit.
    value = URL_PATTERN.sub('[url-redacted]',value)
    value = re.sub(r'\b[^\s:@]+:[^\s@]+@[^\s]+','[userinfo-redacted]',value)
    value = TOKEN_PATTERN.sub('[credential-redacted]',value)
    value = re.sub(r'(?i)\b(?:bearer|basic)\s+[^\s,;]+','[authorization-redacted]',value)
    value = re.sub(r'(?i)\bssh-(?:rsa|ed25519|dss)\s+.*','[ssh-key-redacted]',value)
    # A labeled credential may contain spaces or punctuation; redact through EOL.
    label = CREDENTIAL_LABEL.search(value)
    if label:
        value = value[:label.start()] + '[credential-field redacted]'
    value = re.sub(r'(?i)--(?:password|passwd|token|secret|api[-_]key|access[-_]token)(?:=|\s+).*','[credential-option redacted]',value)
    value = _redact_compiler_defines(value)
    # Quoted paths may contain spaces; handle them before unquoted path tokens.
    value = re.sub(r"(['\"])((?:/|~|\.{1,2}/|[A-Za-z]:[\\/])[^'\"\n]+)\1",
                   lambda m:m[1]+_excerpt_path(m[2],context)+m[1],value)
    value = PATH_PATTERN.sub(lambda m:_excerpt_path(m[0],context),value)
    # Unlabelled token-shaped strings are withheld unless exact public code operands.
    value = OPAQUE_PATTERN.sub(lambda m:m[0] if m[0] in context.identifiers else '[opaque-value redacted]',value)
    return value


def _stderr_excerpt(data, context):
    result = {'policy':'bounded_sanitized_stderr_v3','lines':[], 'scanned_lines':0,
              'omitted_lines':0,'oversized_lines':0,'truncated_lines':0,'scan_truncated':False,
              'raw_stdout_included':False,'raw_full_output_included':False}
    if not isinstance(data,bytes):
        result['status']='invalid_stream_type'; return result
    head=[];tail=deque(maxlen=MAX_EXCERPT_LINES-EXCERPT_HEAD_LINES)
    stop=min(len(data),MAX_STREAM_BYTES);start=0;count=0;private_key=False;pending_credential=0
    result['scan_truncated']=len(data)>stop
    while start<stop and count<MAX_LINES:
        end=data.find(b'\n',start,stop)
        if end<0:
            end=stop
            if stop<len(data):break
        count+=1;size=end-start
        raw=data[start:end] if size<=MAX_LINE_BYTES else b'';start=end+1
        # State uses the same control-normalized syntax as redaction, and is
        # maintained across blank and omitted lines before head/tail selection.
        visible = _normalize_excerpt_line(raw)
        visible = visible if visible is not None else ''
        if '-----BEGIN ' in visible and 'PRIVATE KEY-----' in visible:private_key=True
        blank = not visible.strip()
        indented = bool(visible[:1] in (' ', '\t'))
        blocked = private_key
        if pending_credential:
            if blank:
                blocked = True  # A blank line does not consume the pending value.
            elif pending_credential == 1 or indented:
                blocked = True; pending_credential = 2
            else:
                pending_credential = 0
        if '-----END ' in visible and 'PRIVATE KEY-----' in visible:private_key=False
        label = CREDENTIAL_LABEL.search(visible)
        if label and not visible[label.end():].strip():pending_credential=1
        if blocked: raw=b'[credential-block redacted]'
        elif size>MAX_LINE_BYTES:
            raw=b'[oversized stderr line omitted]';result['oversized_lines']+=1
        item=(count,raw)
        if len(head)<EXCERPT_HEAD_LINES:head.append(item)
        else:tail.append(item)
    result['scanned_lines']=count
    result['scan_truncated'] = result['scan_truncated'] or start<stop
    for number,raw in head+list(tail):
        value=_sanitize_excerpt_line(raw,context)
        if len(value)>MAX_EXCERPT_LINE_CHARS:
            value=value[:MAX_EXCERPT_LINE_CHARS-len(' [line truncated]')]+' [line truncated]';result['truncated_lines']+=1
        result['lines'].append({'stream_line':number,'text':value})
    result['omitted_lines']=count-len(result['lines'])
    # Keep the head and final error context. Short stderr (including the prior 23
    # lines / 2,119 bytes) is complete; long streams disclose all omission counts.
    while len(json.dumps(result,sort_keys=True).encode('ascii'))>MAX_EXCERPT_BYTES and result['lines']:
        index=min(EXCERPT_HEAD_LINES,len(result['lines'])//2)
        result['lines'].pop(index);result['omitted_lines']+=1
    return result


def summarize(phase, stdout, stderr, catalog_path, immutable, directory, control):
    """Diagnostic failure never replaces the original failed subprocess record."""
    fixed = {'schema': 1, 'status': 'bounded_observations', 'causal_claim': 'none',
             'stream_order': 'per_stream_only_cross_stream_order_unavailable',
             'legacy_classifications_are_mentions_only': True}
    if phase not in BUILD_PHASES:
        return {**fixed, 'status': 'phase_not_supported'}
    try:
        context = Context(phase, _load_catalog(catalog_path), immutable, directory, control)
        result = {**fixed, 'source_catalog_scope': 'pkgconf_3_0_8' if context.pkgconf else 'generic_grammar_only',
                  'stdout': _stream(stdout, context), 'stderr': _stream(stderr, context)}
        result['stderr_excerpt'] = _stderr_excerpt(stderr, context)
        result['event_records_omitted_for_excerpt'] = 0
        # Excerpt evidence has priority over duplicate structured event records.
        # First errors/targets, exit status and private byte/hash metadata remain.
        for label in ('stdout', 'stderr'):
            while len(json.dumps(result, sort_keys=True).encode('ascii')) > MAX_REPORT_BYTES and result[label]['events']:
                result[label]['events'].pop()
                result[label]['omitted_events'] += 1
                result['event_records_omitted_for_excerpt'] += 1
        if len(json.dumps(result, sort_keys=True).encode('ascii')) > MAX_REPORT_BYTES:
            return {**fixed, 'status': 'diagnostic_output_cap'}
        return result
    except Exception:
        return {**fixed, 'status': 'diagnostic_unavailable'}
