"""First-party synthetic stderr fixtures; no native tools or downloaded code run."""
from pathlib import Path
import hashlib
import re
import base64
import importlib.util
import json
import sys
sys.dont_write_bytecode=True
import unittest
from unittest.mock import patch
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('excerpt_build_diagnostics',HERE/'build_diagnostics.py')
d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d)
IMMUTABLE='/private/runner-sensitive/work/immutable'
SOURCE=IMMUTABLE+'/tree-pkgconf/pkgconf-3.0.8'
PHASE='/private/runner-sensitive/work/phases/pkgconf-build'
CONTROL='/Users/runner/work/private-repository/private-repository'

def summarize(stderr,stdout=b'',phase='pkgconf-build'):
    if isinstance(stderr,str):stderr=stderr.encode()
    return d.summarize(phase,stdout,stderr,HERE/'build-diagnostic-catalog.json',IMMUTABLE,PHASE,CONTROL)

def text(record):return '\n'.join(row['text'] for row in record['stderr_excerpt']['lines'])

class ExcerptTests(unittest.TestCase):
    def assertSafe(self,record,secrets=()):
        encoded=json.dumps(record)
        self.assertLessEqual(len(encoded.encode()),d.MAX_REPORT_BYTES)
        self.assertLessEqual(len(json.dumps(record['stderr_excerpt']).encode()),d.MAX_EXCERPT_BYTES)
        for secret in ('runner-sensitive','private-repository','::error','::set-output','\u001b','\x00',*secrets):
            self.assertNotIn(secret,encoded)
        for row in record['stderr_excerpt']['lines']:
            self.assertLessEqual(len(row['text']),d.MAX_EXCERPT_LINE_CHARS)
            self.assertTrue(all(32<=ord(c)<=126 for c in row['text']))

    def test_padded_pinned_libtool_error_and_multiline_unknown_prose_survive(self):
        raw='libtool:   error: cannot extract exported symbols from the selected library\nlibtool:          please check whether the symbol extraction command succeeded\nmake: *** [libpkgconf.la] Error 1\n'
        record=summarize(raw)
        self.assertEqual(record['stderr']['first_error']['command_role'],'libtool')
        self.assertEqual(record['stderr']['first_error']['stream_line'],1)
        self.assertIn('cannot extract exported symbols from the selected library',text(record))
        self.assertIn('please check whether the symbol extraction command succeeded',text(record))
        self.assertEqual(record['stderr_excerpt']['omitted_lines'],0)
        self.assertSafe(record)

    def test_underlying_ld_unrecognized_message_preserved(self):
        raw='ld: unsupported tapi file type in the selected SDK stub\nlibtool:   error: unexpected compiler output while linking\nmake: *** [libpkgconf.la] Error 1\n'
        record=summarize(raw)
        self.assertIn('ld: unsupported tapi file type in the selected SDK stub',text(record))
        self.assertIn('unexpected compiler output while linking',text(record))
        self.assertSafe(record)

    def test_current_failure_sized_23_line_fixture_is_complete(self):
        lines=['synthetic tool diagnostic context '+str(i)+' '+('x'*40) for i in range(21)]
        lines+=['libtool:   error: symbol extraction failed for the static library','make: *** [libpkgconf.la] Error 1']
        padding=2119-len(('\n'.join(lines)+'\n').encode()); self.assertGreater(padding,0)
        for i in range(padding): lines[i%21]+='x'
        raw='\n'.join(lines)+'\n';self.assertEqual(len(raw.encode()),2119)
        record=summarize(raw)
        self.assertEqual(len(record['stderr_excerpt']['lines']),23)
        self.assertEqual(record['stderr_excerpt']['omitted_lines'],0)
        self.assertFalse(record['stderr_excerpt']['scan_truncated'])
        self.assertIn(lines[-2],text(record));self.assertSafe(record)

    def test_known_roots_map_to_roles_and_public_source_suffix(self):
        values=[(SOURCE+'/libpkgconf/buffer.c','pkgconf-source'),(PHASE+'/tmp/private-token','phase-tmp'),
                (PHASE+'/home/private-token','phase-home'),(PHASE+'/private-token','mutable_build_phase'),
                (IMMUTABLE+'/private-token','immutable_input_or_provider'),(CONTROL+'/private-token','reviewed_control')]
        for value,role in values:
            with self.subTest(role=role):
                record=summarize("libtool:   error: cannot access '"+value+"': Operation not permitted\n")
                self.assertIn('['+role+']',text(record));self.assertSafe(record,('private-token',))
        record=summarize("ld: error opening '"+SOURCE+"/libpkgconf/buffer.c'\n")
        self.assertIn('libpkgconf/buffer.c',text(record))

    def test_other_runner_tmp_home_and_windows_paths_redact(self):
        values=['/Users/runner/INVALID_TEST_PATH_MARKER/file','/home/runner/INVALID_TEST_PATH_MARKER/file','/private/var/folders/INVALID_TEST_PATH_MARKER/file',
                '/var/folders/INVALID_TEST_PATH_MARKER/file','/tmp/INVALID_TEST_PATH_MARKER/file','/Users/private-account/INVALID_TEST_PATH_MARKER',
                'C:\\Users\\private-account\\INVALID_TEST_PATH_MARKER','~/INVALID_TEST_PATH_MARKER','../../INVALID_TEST_PATH_MARKER/file']
        for value in values:
            with self.subTest(value=value):
                record=summarize("libtool:   error: cannot access '"+value+"': permission was denied\n")
                self.assertIn('permission was denied',text(record));self.assertSafe(record,('INVALID_TEST_PATH_MARKER','private-account'))

    def test_quoted_paths_with_spaces_are_redacted_before_truncation(self):
        record=summarize('libtool:   error: cannot read "/Users/private-account/My Secret Project/file": denied\n')
        self.assertIn('cannot read',text(record));self.assertSafe(record,('private-account','My Secret Project'))

    def test_public_tools_targets_and_source_symbols_stay_useful(self):
        record=summarize("libtool:   error: /usr/bin/nm failed for libpkgconf.la; symbol pkgconf_client_init was unavailable\n")
        self.assertIn('/usr/bin/nm',text(record));self.assertIn('libpkgconf.la',text(record));self.assertIn('pkgconf_client_init',text(record))
        record=summarize("ld: cannot read '/Applications/private-Xcode/Toolchains/clang'\n")
        self.assertIn('[toolchain-path]/clang',text(record));self.assertSafe(record,('private-Xcode',))

    def test_urls_userinfo_and_query_values_removed(self):
        record=summarize('libtool:   error: failed lookup https://alice:INVALID_TEST_PATH_MARKER@example.invalid/a?token=other-secret ftp://private.invalid/INVALID_TEST_PATH_MARKER alice:INVALID_TEST_PATH_MARKER@example.invalid\n')
        self.assertIn('failed lookup',text(record));self.assertSafe(record,('INVALID_TEST_PATH_MARKER','other-secret','example.invalid','private.invalid','alice'))

    def test_labeled_credentials_and_space_containing_values_removed(self):
        for value in ('password="INVALID TEST VALUE WITH SPACES"','PASSWORD: INVALID TEST VALUE WITH SPACES','api_key=INVALID_TEST_VALUE',
                      'GITHUB_TOKEN=INVALID_TEST_VALUE','Authorization: Bearer INVALID_TEST_VALUE','client-secret: INVALID_TEST_VALUE',
                      '--token "INVALID TEST VALUE WITH SPACES"','--api-key INVALID_TEST_VALUE','Cookie: session=INVALID_TEST_VALUE'):
            with self.subTest(value=value):
                record=summarize('libtool:   error: tool failed; '+value+'\n')
                self.assertIn('tool failed',text(record));self.assertSafe(record,('INVALID_TEST_VALUE','INVALID TEST VALUE WITH SPACES'))

    def test_inert_provider_sentinels_exercise_redaction_pipeline(self):
        # Intentionally invalid labels, never provider-shaped values.
        markers=('INVALID_TEST_TOKEN[github-classic]','INVALID_TEST_TOKEN[github-fine-grained]',
                 'INVALID_TEST_TOKEN[gitlab]','INVALID_TEST_TOKEN[slack]',
                 'INVALID_TEST_TOKEN[openai]','INVALID_TEST_TOKEN[google]',
                 'INVALID_TEST_TOKEN[aws]','INVALID_TEST_TOKEN[jwt]')
        for marker in markers:
            self.assertIsNone(d.TOKEN_PATTERN.search(marker))
            # Exercise replacement with an inert matcher, without constructing a realistic token.
            with patch.object(d,'TOKEN_PATTERN',re.compile(re.escape(marker))):
                record=summarize('libtool:   error: unexpected response '+marker+'\n')
            self.assertIn('[credential-redacted]',text(record))
            self.assertIn('unexpected response',text(record));self.assertSafe(record,(marker,))

    def test_production_provider_pattern_contract_is_unchanged(self):
        # Pin every real rule without storing any provider-shaped value.
        self.assertEqual(hashlib.sha256(d.TOKEN_PATTERN.pattern.encode()).hexdigest(),'d4cfef6258fa66f73da89243036c26f01b5f36f7bf55a8737eec201a05999c7d')
        families=('gh[pousr]_','github_pat_','glpat-','xox[baprs]-','sk-(?:proj-|svcacct-)?','AIza','(?:AKIA|ASIA)','eyJ')
        for family in families:self.assertIn(family,d.TOKEN_PATTERN.pattern)
        self.assertTrue(d.TOKEN_PATTERN.flags & re.IGNORECASE)
        self.assertTrue(d.TOKEN_PATTERN.pattern.startswith(r'(?i)\b(?:'))
        self.assertTrue(d.TOKEN_PATTERN.pattern.endswith(r')\b'))

    def test_opaque_unlabeled_tokens_are_redacted_but_public_identifiers_survive(self):
        token='INVALID_TEST_OPAQUE_VALUE_NOT_A_CREDENTIAL';record=summarize('libtool:   error: response '+token+'\n')
        self.assertSafe(record,(token,))
        catalog=json.loads((HERE/'build-diagnostic-catalog.json').read_text())
        identifier=next(x for x in catalog['public_identifiers'] if len(x)>=32)
        self.assertIn(identifier,text(summarize('libtool:   error: unsupported symbol '+identifier+'\n')))

    def test_environment_assignments_command_lines_shell_traces_are_suppressed(self):
        lines=['GITHUB_TOKEN=INVALID_TEST_VALUE','export CUSTOM=INVALID_TEST_VALUE','PATH=/Users/private-account/bin',
               '/usr/bin/clang -DPRIVATE=INVALID_TEST_VALUE -c cli/main.c','libtool: link: /usr/bin/nm INVALID_TEST_VALUE',
               '+ env CUSTOM=INVALID_TEST_VALUE','declare -x PRIVATE=INVALID_TEST_VALUE']
        record=summarize('\n'.join(lines)+'\n')
        self.assertIn('environment-assignment redacted',text(record));self.assertIn('command-line redacted',text(record));self.assertIn('shell-trace redacted',text(record))
        self.assertSafe(record,('INVALID_TEST_VALUE','private-account'))

    def test_compiler_defines_redacted_inside_diagnostic_prose(self):
        record=summarize('libtool:   error: unexpected argument -DPRIVATE=INVALID_TEST_VALUE while linking\n')
        self.assertNotIn('while linking',text(record));self.assertSafe(record,('INVALID_TEST_VALUE',))

    def test_private_key_blocks_are_redacted_across_excerpt_gap(self):
        payload='INVALID_TEST_NONKEY_DATA!'
        with self.assertRaises(ValueError):base64.b64decode(payload,validate=True)
        lines=['-----BEGIN INVALID TEST PRIVATE KEY-----']+[payload]*90+['-----END INVALID TEST PRIVATE KEY-----','libtool:   error: key rejected']
        record=summarize('\n'.join(lines)+'\n')
        self.assertGreater(record['stderr_excerpt']['omitted_lines'],0)
        self.assertIn('key rejected',text(record));self.assertSafe(record,('INVALID_TEST_NONKEY_DATA!',))

    def test_empty_credential_field_redacts_following_line(self):
        record=summarize('libtool:   error: token:\n  INVALID_TEST_VALUE\n  INVALID_TEST_OTHER\nlibtool:   error: rejected\n')
        self.assertIn('rejected',text(record));self.assertSafe(record,('INVALID_TEST_VALUE','INVALID_TEST_OTHER'))

    def test_controls_ansi_osc_workflow_commands_and_invalid_bytes_neutralized(self):
        raw=b'\x1b[31mlibtool:   error: command failed\x1b[0m\n::error::forged\n::set-output name=x::bad\n'+b'libtool: error: bad\x00\r\xff\n'+b'\x1b]0;private-title\x07libtool: error: bad title\n'
        record=summarize(raw)
        self.assertIn('command failed',text(record));self.assertIn('[workflow-marker]',text(record));self.assertSafe(record,('private-title',))

    def test_oversized_line_never_forwards_partial_secret(self):
        record=summarize(b'libtool:   error: '+b'x'*(d.MAX_LINE_BYTES+1)+b' token=INVALID_TEST_VALUE\n')
        self.assertEqual(record['stderr_excerpt']['oversized_lines'],1)
        self.assertEqual(record['stderr_excerpt']['lines'][0]['text'],'[oversized stderr line omitted]');self.assertSafe(record,('INVALID_TEST_VALUE',))

    def test_per_line_total_and_head_tail_limits_are_enforced(self):
        lines=['libtool:   error: '+('human words '*100)+' line '+str(i) for i in range(200)]
        lines[-1]='libtool:   error: final underlying message remains'
        record=summarize('\n'.join(lines)+'\n')
        excerpt=record['stderr_excerpt'];self.assertLessEqual(len(excerpt['lines']),64)
        self.assertGreater(excerpt['omitted_lines'],0);self.assertGreater(excerpt['truncated_lines'],0)
        self.assertEqual(excerpt['lines'][0]['stream_line'],1)
        self.assertIn('final underlying message remains',text(record));self.assertSafe(record)

    def test_scan_line_limit_and_incomplete_byte_tail_disclosed(self):
        with patch.object(d,'MAX_LINES',3):record=summarize(b'one\ntwo\nthree\nfour\n')
        self.assertTrue(record['stderr_excerpt']['scan_truncated']);self.assertEqual(record['stderr_excerpt']['scanned_lines'],3)
        with patch.object(d,'MAX_STREAM_BYTES',10):record=summarize(b'one\nthis line is incomplete')
        self.assertTrue(record['stderr_excerpt']['scan_truncated']);self.assertEqual(len(record['stderr_excerpt']['lines']),1)
        self.assertSafe(record)

    def test_raw_stdout_never_added_to_excerpt(self):
        record=summarize(b'libtool:   error: unknown useful message\n',b'stdout-private-contents\n')
        self.assertNotIn('stdout-private-contents',json.dumps(record));self.assertFalse(record['stderr_excerpt']['raw_stdout_included'])
        self.assertFalse(record['stderr_excerpt']['raw_full_output_included']);self.assertSafe(record)

    def test_unknown_message_is_not_replaced_by_only_category(self):
        record=summarize('libtool:   error: a previously unrecognized failure involving symbol extraction and archive indexing\n')
        self.assertEqual(record['stderr']['first_error']['category'],'unrecognized_diagnostic')
        self.assertIn('a previously unrecognized failure involving symbol extraction and archive indexing',text(record))
        self.assertSafe(record)

    def test_full_report_cap_prioritizes_excerpt_over_duplicate_event_list(self):
        errors=('libpkgconf/buffer.c:123:4: error: use of undeclared identifier \'pkgconf_buffer_t\'\n')*70
        record=summarize(errors,errors.encode())
        self.assertIn('stderr_excerpt',record);self.assertIsNotNone(record['stderr']['first_error']);self.assertSafe(record)
        with patch.object(d,'MAX_REPORT_BYTES',len(json.dumps(record))-400):
            narrowed=summarize(errors,errors.encode())
        self.assertIn('stderr_excerpt',narrowed);self.assertGreater(narrowed['event_records_omitted_for_excerpt'],0)

    def test_padded_libtool_warning_does_not_become_first_error(self):
        record=summarize('libtool: warning: incidental issue\nlibtool:   error: genuine diagnostic\nmake: *** [libpkgconf.la] Error 1\n')
        self.assertEqual(record['stderr']['first_error']['stream_line'],2)
        self.assertEqual(record['stderr']['severity_counts']['warning'],1)
        self.assertSafe(record)

    def test_revision_and_tests_receipt_bound(self):
        receipt=json.loads((HERE/'review-receipt.json').read_text())
        self.assertEqual(receipt['candidate_revision'],11)
        for name in ('test_stderr_excerpts.py','build_diagnostics.py'):
            self.assertEqual(receipt['sha256'][name],hashlib.sha256((HERE/name).read_bytes()).hexdigest())
        self.assertNotIn('approval',receipt)

if __name__=='__main__':unittest.main(verbosity=2)
