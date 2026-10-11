"""Offline first-party fixtures only; no configure, compiler, make or downloaded code."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
sys.dont_write_bytecode = True
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

def load(name):
    spec = importlib.util.spec_from_file_location('test_build_'+name, HERE/(name+'.py'))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module

d = load('build_diagnostics')
s = load('stage')
b = load('bounds')
a = load('archive_tools')
n = load('native_checks')
CATALOG = HERE/'build-diagnostic-catalog.json'
SECRET = 'ghp_DO_NOT_PRINT_123456789 https://secret.invalid/x?token=PRIVATE ::error:: forged'
IMMUTABLE = '/private/review-secret/immutable'
SOURCE = IMMUTABLE+'/tree-pkgconf/pkgconf-3.0.8'
PHASE = '/private/review-secret/phases/pkgconf-build'
CONTROL = '/private/review-secret/repository'

def summary(stdout=b'', stderr=b'', phase='pkgconf-build'):
    return d.summarize(phase, stdout, stderr, CATALOG, IMMUTABLE, PHASE, CONTROL)

class DiagnosticTests(unittest.TestCase):
    def assertPrivate(self, record):
        # v4's strict no-unknown-text contract still applies to structured fields.
        # v5's separately tested stderr excerpt intentionally preserves unfamiliar prose.
        encoded = json.dumps({k:v for k,v in record.items() if k != 'stderr_excerpt'})
        for secret in ('ghp_', 'DO_NOT_PRINT', 'secret.invalid', 'PRIVATE', '::error', '/private/review-secret', '/Users/', '\\u001b', 'credential-value'):
            self.assertNotIn(secret, encoded)
        self.assertLessEqual(len(encoded.encode()), d.MAX_REPORT_BYTES)

    def test_catalog_matches_exact_pinned_member_hashes(self):
        catalog = json.loads(CATALOG.read_text())
        manifest = HERE/'members/pkgconf.json'; members = json.loads(manifest.read_text())
        records = {r['path']:r for r in members['members']}
        self.assertEqual(catalog['archive_sha256'], s.INPUT_HASHES['pkgconf'])
        self.assertEqual(catalog['member_manifest_sha256'], hashlib.sha256(manifest.read_bytes()).hexdigest())
        self.assertEqual((len(catalog['files']),len(catalog['targets']),len(catalog['outputs'])), (46,43,50))
        for name, item in catalog['files'].items():
            self.assertEqual(item['sha256'], records['pkgconf-3.0.8/'+name]['sha256'])
            self.assertGreater(item['line_count'],0)
        self.assertEqual(catalog['targets']['cli/pkgconf-main.o']['rule_line'],1969)
        self.assertEqual(catalog['targets']['Makefile.in']['role'],'automake_regeneration')

    def test_source_location_preserves_public_identifier(self):
        record = summary(stderr=(SOURCE+"/libpkgconf/buffer.c:123:4: error: use of undeclared identifier 'pkgconf_buffer_t'\n").encode())
        event = record['stderr']['first_error']
        self.assertEqual(event['category'],'undeclared_identifier')
        self.assertEqual(event['message'],"use of undeclared identifier 'pkgconf_buffer_t'")
        self.assertEqual(event['source']['file'],'buffer.c')
        self.assertEqual(event['source']['line'],123)
        self.assertEqual(event['source']['column'],4)
        self.assertEqual(event['source']['source_sha256'],json.loads(CATALOG.read_text())['files']['libpkgconf/buffer.c']['sha256'])
        self.assertPrivate(record)

    def test_secret_identifier_and_unknown_path_redacted_individually(self):
        raw = b"/Users/credential-value/main.c:12:3: error: unknown type name 'ghp_DO_NOT_PRINT_123456789'\n"
        record = summary(stderr=raw); event=record['stderr']['first_error']
        self.assertEqual(event['message'],"unknown type name '[unreviewed-identifier]'")
        self.assertEqual(event['source_status'],'unreviewed_or_out_of_range')
        self.assertPrivate(record)

    def test_secret_url_header_and_unknown_library_redacted(self):
        raw = b"cli/main.c:20:1: fatal error: 'https://secret.invalid/x?token=PRIVATE' file not found\nld: error: library not found for -lcredential-value\n"
        record = summary(stderr=raw)
        self.assertEqual(record['stderr']['first_error']['message'],"'[unreviewed-header]' file not found")
        self.assertEqual(record['stderr']['events'][1]['category'],'link_library_not_found')
        self.assertPrivate(record)

    def test_known_literal_header_survives(self):
        catalog=json.loads(CATALOG.read_text()); self.assertIn('stdlib.h',catalog['public_headers'])
        record=summary(stderr=b"cli/main.c:20:1: fatal error: 'stdlib.h' file not found\n")
        self.assertEqual(record['stderr']['first_error']['message'],"'stdlib.h' file not found")

    def test_incidental_permission_and_warning_do_not_become_failure(self):
        raw = b"xcode-select incidental Operation not permitted\nclang: warning: credential-value\nmake: *** Waiting for unfinished jobs....\n"
        record = summary(stderr=raw)
        self.assertIsNone(record['stderr']['first_error'])
        self.assertIsNone(record['stderr']['first_failing_make_target'])
        self.assertEqual(record['stderr']['severity_counts']['warning'],1)
        self.assertEqual(record['causal_claim'],'none')
        self.assertTrue(record['legacy_classifications_are_mentions_only'])
        self.assertPrivate(record)

    def test_warning_before_fatal_error_keeps_actual_severity(self):
        raw = b"clang: warning: Permission denied\nclang: error: unable to execute command: posix_spawn failed: Operation not permitted\nmake: *** [cli/pkgconf-main.o] Error 1\n"
        record=summary(stderr=raw); stream=record['stderr']
        self.assertEqual(stream['first_error']['category'],'compiler_spawn_operation_not_permitted')
        self.assertEqual(stream['first_error']['stream_line'],2)
        self.assertEqual(stream['first_failing_make_target']['target'],'cli/pkgconf-main.o')
        self.assertEqual(stream['first_failing_make_target']['target_role'],'cli_compile')
        self.assertPrivate(record)

    def test_unprefixed_frontend_output_denial_has_known_output(self):
        raw=("error: unable to open output file '"+PHASE+"/cli/.deps/pkgconf-main.Tpo': 'Operation not permitted'\n").encode()
        record=summary(stderr=raw); event=record['stderr']['first_error']
        self.assertEqual(event['category'],'file_access_operation_not_permitted')
        self.assertEqual(event['message'],"unable to open output file 'cli/.deps/pkgconf-main.Tpo': Operation not permitted")
        self.assertPrivate(record)

    def test_secret_paths_keep_only_fixed_role(self):
        raw=("clang: error: unable to open output file '"+IMMUTABLE+"/credential-value': Permission denied\n"+
             "clang: error: unable to open output file '/Users/credential-value': Permission denied\n").encode()
        record=summary(stderr=raw)
        self.assertIn('[immutable_input_or_provider]',record['stderr']['events'][0]['message'])
        self.assertIn('[unreviewed-path]',record['stderr']['events'][1]['message'])
        self.assertPrivate(record)

    def test_first_failing_target_independently_in_each_stream(self):
        stdout=b'make[1]: *** [Makefile:1970: cli/pkgconf-main.o] Error 1\nmake: *** [pkgconf] Error 2\n'
        stderr=b'make[2]: *** [libpkgconf/buffer.lo] Error 1\nmake: *** [libpkgconf.la] Error 2\n'
        record=summary(stdout,stderr)
        self.assertEqual(record['stdout']['first_failing_make_target']['target'],'cli/pkgconf-main.o')
        self.assertEqual(record['stderr']['first_failing_make_target']['target'],'libpkgconf/buffer.lo')
        self.assertEqual(record['stream_order'],'per_stream_only_cross_stream_order_unavailable')
        self.assertNotIn('first_global_error',record)

    def test_first_unknown_make_target_is_not_skipped(self):
        record=summary(stderr=b'make: *** [/Users/credential-value] Error 1\nmake: *** [pkgconf] Error 2\n')
        first=record['stderr']['first_failing_make_target']
        self.assertEqual(first['target_status'],'unreviewed_target')
        self.assertNotIn('target',first)
        self.assertEqual(record['stderr']['events'][1]['target'],'pkgconf')
        self.assertPrivate(record)

    def test_ignored_recipe_is_warning_not_first_failure(self):
        record=summary(stderr=b'make: *** [pkgconf] Error 1 (ignored)\nmake: *** [libpkgconf.la] Error 2\n')
        self.assertEqual(record['stderr']['events'][0]['severity'],'warning')
        self.assertEqual(record['stderr']['first_failing_make_target']['target'],'libpkgconf.la')

    def test_regeneration_evidence_requires_error_context(self):
        record=summary(stderr=("config log contains automake-1.18 and autoconf-2.72\nmake: *** ["+SOURCE+"/Makefile.in] Error 127\n").encode())
        first=record['stderr']['first_failing_make_target']
        self.assertEqual(first['target_role'],'automake_regeneration')
        self.assertEqual(first['target'],'Makefile.in')
        self.assertEqual(record['stderr']['scanned_lines'],2)
        self.assertPrivate(record)

    def test_missing_make_target_public_and_private_operands(self):
        record=summary(stderr=b"make: *** No rule to make target 'credential-value', needed by 'pkgconf'.  Stop.\n")
        event=record['stderr']['first_error']
        self.assertEqual(event['category'],'make_no_rule')
        self.assertEqual(event['target_status'],'unreviewed_target')
        self.assertEqual(event['needed_by']['target'],'pkgconf')
        self.assertPrivate(record)

    def test_shell_command_denial_has_fixed_role_without_path(self):
        record=summary(stderr=b'/bin/sh: /Users/credential-value/clang: Operation not permitted\n')
        self.assertEqual(record['stderr']['first_error']['command_role'],'compiler_driver')
        self.assertEqual(record['stderr']['first_error']['category'],'command_operation_not_permitted')
        self.assertPrivate(record)

    def test_command_observation_never_claimed_causal(self):
        raw=("/Applications/credential-value/clang -DSECRET=credential-value -c -o cli/pkgconf-main.o "+SOURCE+"/cli/main.c\n").encode()
        record=summary(stdout=raw,stderr=b'make: *** [cli/pkgconf-main.o] Error 1\n')
        observed=record['stdout']['last_observed_command']
        self.assertEqual(observed['command_role'],'compiler_driver')
        self.assertEqual(observed['target'],'cli/pkgconf-main.o')
        self.assertEqual(observed['relationship'],'observed_command_only_not_proven_failed')
        self.assertIsNone(record['stderr']['last_observed_command'])
        self.assertPrivate(record)

    def test_control_workflow_unicode_and_oversized_lines_rejected(self):
        raw=(b'clang: error: '+SECRET.encode()+b'\n'+b'clang: error: \x1b[31mcredential-value\n'+
             b'clang: error: \x00credential-value\n'+b'clang: error: \xffcredential-value\n'+
             b'x'*(d.MAX_LINE_BYTES+1)+b'\n'+b'make: *** [pkgconf] Error 2\r\n')
        record=summary(stderr=raw)
        self.assertEqual(record['stderr']['rejected_lines'],5)
        self.assertEqual(record['stderr']['first_error']['target'],'pkgconf')
        self.assertPrivate(record)

    def test_invalid_locations_not_public(self):
        for path,line in [('cli/main.c','999999'),('cli/../cli/main.c','2'),('/Users/credential-value/cli/main.c','2')]:
            with self.subTest(path=path,line=line):
                record=summary(stderr=(path+':'+line+":1: error: unknown type name 'pkgconf_client_t'\n").encode())
                self.assertEqual(record['stderr']['first_error']['source_status'],'unreviewed_or_out_of_range')
                self.assertPrivate(record)

    def test_unknown_messages_never_echo(self):
        raw=b'clang: error: credentials credential-value a brand new error\n'
        record=summary(stderr=raw)
        self.assertEqual(record['stderr']['first_error']['category'],'unrecognized_diagnostic')
        self.assertEqual(record['stderr']['first_error']['message'],'[message withheld: no reviewed grammar]')
        self.assertPrivate(record)

    def test_events_caps_keep_late_first_failure(self):
        raw=b'clang: warning: unknown\n'*100+b'make: *** [pkgconf] Error 2\n'
        record=summary(raw,raw)
        for label in ('stdout','stderr'):
            self.assertEqual(len(record[label]['events']),d.MAX_EVENTS)
            self.assertEqual(record[label]['omitted_events'],101-d.MAX_EVENTS)
            self.assertEqual(record[label]['first_failing_make_target']['stream_line'],101)
        self.assertPrivate(record)

    def test_stream_byte_line_caps_and_invalid_stream_types(self):
        record=summary(stderr=b'x\n'*(d.MAX_LINES+5))
        self.assertTrue(record['stderr']['scan_truncated'])
        self.assertEqual(record['stderr']['scanned_lines'],d.MAX_LINES)
        with patch.object(d,'MAX_STREAM_BYTES',30):
            record=summary(stderr=b'clang: error: '+b'x'*100)
        self.assertTrue(record['stderr']['scan_truncated'])
        self.assertIsNone(record['stderr']['first_error'])
        record=summary(stderr=SECRET)
        self.assertEqual(record['stderr']['input_status'],'invalid_stream_type')
        self.assertPrivate(record)

    def test_malformed_messages_and_unavailable_catalog_fail_closed(self):
        for raw in (b"clang: error: 'unclosed\n",b'make: *** [unterminated\n',b'clang: error: unknown argument: credential-value\n'):
            self.assertPrivate(summary(stderr=raw))
        with patch.object(d,'_load_catalog',side_effect=ValueError(SECRET)):
            record=summary(stderr=b'make: *** [pkgconf] Error 2\n')
        self.assertEqual(record['status'],'diagnostic_unavailable')
        self.assertPrivate(record)

    def test_other_phases_do_not_borrow_pkgconf_names(self):
        for phase in d.BUILD_PHASES[1:]:
            record=summary(stderr=b"cli/main.c:2:1: error: unknown type name 'pkgconf_client_t'\nmake: *** [pkgconf] Error 2\n",phase=phase)
            self.assertEqual(record['source_catalog_scope'],'generic_grammar_only')
            self.assertEqual(record['stderr']['first_error']['source_status'],'unreviewed_or_out_of_range')
            self.assertEqual(record['stderr']['first_failing_make_target']['target_status'],'unreviewed_target')
        self.assertEqual(summary(phase='unapproved-build')['status'],'phase_not_supported')

    def test_lane_integration_preserves_failed_record_command_and_budget(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); work=root/'work'; work.mkdir(); lane=s.Lane(root,HERE,work,(a,b,n))
            phase=lane.directory('pkgconf-build'); out=b'Operation not permitted\n'; err=b'make: *** [cli/pkgconf-main.o] Error 2\n'
            original={'status':'failed','failure_class':'child_exit','exit_code':2,'stdout_bytes':len(out),'stderr_bytes':len(err)}
            with patch.object(b,'run',return_value=(original,out,err)) as run, patch.object(lane,'checkpoint'), patch('sys.stdout',new_callable=io.StringIO) as printed:
                with self.assertRaises(s.PhaseError) as caught:
                    lane.run('pkgconf-build',['/usr/bin/make','-j2','pkgconf'],directory=phase,timeout=90)
            self.assertEqual(caught.exception.record['failure_class'],'child_exit')
            self.assertEqual(caught.exception.record['exit_code'],2)
            self.assertEqual(caught.exception.record['build_diagnostics']['stderr']['first_failing_make_target']['target'],'cli/pkgconf-main.o')
            self.assertEqual(run.call_args.args[0][-3:],['/usr/bin/make','-j2','pkgconf'])
            self.assertEqual(run.call_args.kwargs['output_remaining'],8*1024**2)
            self.assertEqual(lane.output,len(out)+len(err)); self.assertEqual(len(lane.steps),1)
            self.assertNotIn('Operation not permitted',printed.getvalue())

    def test_success_and_nonbuild_failure_do_not_load_diagnostics(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); work=root/'work'; work.mkdir(); lane=s.Lane(root,HERE,work,(a,b,n)); phase=lane.directory('pkgconf-build')
            for name,status in [('pkgconf-build','passed'),('pkgconf-configure','failed')]:
                record={'status':status,'failure_class':None if status=='passed' else 'child_exit','exit_code':0 if status=='passed' else 1,'stdout_bytes':0,'stderr_bytes':0}
                with patch.object(b,'run',return_value=(record,b'',b'')),patch.object(lane,'checkpoint'),patch.object(s,'load_module') as loaded,patch('sys.stdout',new_callable=io.StringIO):
                    if status=='passed': lane.run(name,['mock-never-executed'],directory=phase)
                    else:
                        with self.assertRaises(s.PhaseError): lane.run(name,['mock-never-executed'],directory=phase)
                loaded.assert_not_called()

    def test_diagnostic_output_fails_closed_at_absolute_cap(self):
        with patch.object(d,'MAX_REPORT_BYTES',100):
            record=summary(stderr=b'make: *** [pkgconf] Error 2\n')
        self.assertEqual(record['status'],'diagnostic_output_cap')
        self.assertNotIn('stdout',record)

    def test_all_new_files_receipt_bound_and_approval_closed(self):
        receipt=json.loads((HERE/'review-receipt.json').read_text())
        for name in ('build_diagnostics.py','build-diagnostic-catalog.json','test_build_diagnostics.py'):
            self.assertEqual(receipt['sha256'][name],hashlib.sha256((HERE/name).read_bytes()).hexdigest())
        self.assertEqual(receipt['candidate_revision'],11)
        self.assertNotIn('approval',receipt)
        for gate in ('execution_approved','independent_review_passed','temporary_linker_adhoc_signing_approved','install_name_linker_assignment_approved'):
            self.assertIs(receipt[gate],False)

if __name__=='__main__': unittest.main(verbosity=2)
