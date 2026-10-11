"""Inert known-syntax disclosure regressions; no shell, dependency or native execution."""
from pathlib import Path
import hashlib
import importlib.util
import itertools
import json
import sys
sys.dont_write_bytecode=True
import unittest
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('structural_build_diagnostics',HERE/'build_diagnostics.py')
d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d)
CATALOG=HERE/'build-diagnostic-catalog.json'

def summarize(raw):
    if isinstance(raw,str):raw=raw.encode()
    return d.summarize('pkgconf-build',b'',raw,CATALOG,'/safe/immutable','/safe/phase','/safe/control')

def output(record):return '\n'.join(line['text'] for line in record['stderr_excerpt']['lines'])

class StructuralTests(unittest.TestCase):
    def safe(self,raw,secrets=('INVALID_TEST_VALUE','INVALID TEST VALUE','INVALID TEST TAIL','INVALID_TEST_OTHER')):
        record=summarize(raw);encoded=json.dumps(record)
        self.assertIn('stderr_excerpt',record)
        for secret in secrets:self.assertNotIn(secret,encoded)
        self.assertLessEqual(len(encoded.encode()),d.MAX_REPORT_BYTES)
        self.assertLessEqual(len(json.dumps(record['stderr_excerpt']).encode()),d.MAX_EXCERPT_BYTES)
        self.assertNotIn('::',output(record))
        self.assertTrue(all(32<=ord(char)<=126 or char=='\n' for char in output(record)))
        return record

    def test_all_14_exact_independent_review_fixtures(self):
        fixtures=json.loads((HERE/'disclosure-regression-fixtures.json').read_text())
        self.assertEqual(len(fixtures),14)
        self.assertEqual(hashlib.sha256((HERE/'disclosure-regression-fixtures.json').read_bytes()).hexdigest(),'567c3a486b541eb98da52bbb1abb3c7fac020fdaeb1e2ebbb7fdac2a56d18ebe')
        for case in fixtures:
            with self.subTest(case=case['case']):
                self.safe(case['synthetic_stderr'],(case['unexpected_retained_value'],))

    def test_known_tools_wrappers_quoting_whitespace_and_colors_matrix(self):
        tools=('/usr/bin/libtool','/usr/bin/xcrun','/usr/bin/nm','/usr/bin/env','/bin/sh','env','command','exec')
        contexts=('', 'libtool: link: ', 'libtool:\tcompile:\t', 'libtool: execute: ')
        quotes=('', '"', "'")
        colors=('', '\x1b[32m', '\x1b[1;31m')
        for tool,context,quote,color in itertools.product(tools,contexts,quotes,colors):
            with self.subTest(tool=tool,context=context,quote=quote,color=repr(color)):
                self.safe(color+context+quote+tool+quote+'\tCUSTOM=INVALID_TEST_VALUE\x1b[0m\n')

    def test_explicit_libtool_command_context_suppresses_unfamiliar_executable(self):
        for prefix in ('link','compile','execute'):
            record=self.safe('libtool: '+prefix+': /some/unreviewed/tool --value INVALID_TEST_VALUE\n')
            self.assertEqual(output(record),'[command-line redacted]')

    def test_assignments_exports_declarations_and_quoted_wrappers(self):
        prefixes=('', '\x1b[32m', '\x00\x07', '\t')
        statements=('CUSTOM=INVALID_TEST_VALUE','CUSTOM = INVALID_TEST_VALUE','export CUSTOM=INVALID_TEST_VALUE',
                    'declare -xr CUSTOM=INVALID_TEST_VALUE','readonly CUSTOM=INVALID_TEST_VALUE','typeset CUSTOM=INVALID_TEST_VALUE',
                    'printf %s INVALID_TEST_VALUE','echo INVALID_TEST_VALUE','printenv CUSTOM INVALID_TEST_VALUE',
                    'eval /usr/bin/nm INVALID_TEST_VALUE','env -S "nm INVALID_TEST_VALUE"',
                    '"CUSTOM=INVALID_TEST_VALUE" /usr/bin/nm','"/usr/bin/env" CUSTOM=INVALID_TEST_VALUE /usr/bin/nm',
                    '( /usr/bin/nm INVALID_TEST_VALUE )','libtool: link: CUSTOM=INVALID_TEST_VALUE /usr/bin/nm')
        for prefix,statement in itertools.product(prefixes,statements):
            with self.subTest(statement=statement,prefix=repr(prefix)):
                self.safe(prefix+statement+'\n')

    def test_nested_colored_control_interrupted_shell_trace_prefixes(self):
        for plus,color,space in itertools.product(('+','++','++++'),('', '\x1b[32m','\x00'),(' ','\t','')):
            self.safe(color+plus+space+'env CUSTOM=INVALID_TEST_VALUE\x1b[0m\n')
        self.safe('e\x00nv CUSTOM=INVALID_TEST_VALUE\n')
        self.safe('CUSTOM\x00=INVALID_TEST_VALUE\n')
        self.safe(b'\x9b32m++ env CUSTOM=INVALID_TEST_VALUE\x9b0m\n')

    def test_quoted_json_and_escaped_credential_label_matrix(self):
        keys=('password','PASSWORD','token','api_key','client-secret','Authorization','GITHUB_TOKEN')
        quotes=('', '"', "'", '\\"', "\\'")
        separators=(':','=', ' : ', '\t=\t')
        for key,quote,separator in itertools.product(keys,quotes,separators):
            with self.subTest(key=key,quote=quote,separator=separator):
                record=self.safe('libtool: error: {'+quote+key+quote+separator+'"INVALID TEST VALUE"} tail\n')
                self.assertIn('libtool: error:',output(record))

    def test_quoted_password_operands_and_escaped_operand_quotes(self):
        for label,label_quote,value_quote,space in itertools.product(('password','passwd','token','api-key'),('', '"', "'"),('"',"'",'\\"'),(' ','\t','  ')):
            self.safe('libtool:   error: '+label_quote+label+label_quote+space+value_quote+'INVALID TEST VALUE'+value_quote+' trailing text\n')

    def test_empty_quoted_labels_survive_multiple_blank_lines(self):
        labels=('token:', '"token":', "'password' =", '{"api_key":', '\\"token\\":')
        blank_runs=('', '\n', '\n\n', ' \t\n\t\n')
        indentation=('', ' ', '\t')
        for label,blanks,indent in itertools.product(labels,blank_runs,indentation):
            with self.subTest(label=label,blanks=repr(blanks),indent=repr(indent)):
                record=self.safe('libtool: error: '+label+'\n'+blanks+indent+'INVALID_TEST_VALUE\n\n  INVALID_TEST_OTHER\nlibtool:   error: archive indexing failed\n')
                self.assertIn('archive indexing failed',output(record))

    def test_colored_empty_label_and_omitted_blank_region_preserve_state(self):
        raw='public context\n'*16+'\x1b[32mlibtool: error: "token":\x1b[0m\n'+'\n'*80+'INVALID_TEST_VALUE\nlibtool: error: symbol extraction failed\n'
        record=self.safe(raw)
        self.assertGreater(record['stderr_excerpt']['omitted_lines'],0)
        self.assertIn('symbol extraction failed',output(record))

    def test_complete_compiler_define_quote_escape_and_separate_flag_matrix(self):
        operands=(
            '-DPRIVATE="INVALID TEST VALUE"',
            "-DPRIVATE='INVALID TEST VALUE'",
            '"-DPRIVATE=INVALID TEST VALUE"',
            "'-DPRIVATE=INVALID TEST VALUE'",
            '-D PRIVATE="INVALID TEST VALUE"',
            '-D\t"PRIVATE=INVALID TEST VALUE"',
            "-D'PRIVATE=INVALID TEST VALUE'",
            '-DPRIVATE=SHORT\\ PRIVATE\\ VALUE',
            '-DPRIVATE=\\"INVALID TEST VALUE\\"',
            '-DPRIVATE=\\"SHORT\\ PRIVATE\\ VALUE\\"',
            "-DPRIVATE=\\'INVALID TEST VALUE\\'",
        )
        for operand,color in itertools.product(operands,('', '\x1b[32m')):
            with self.subTest(operand=operand,color=repr(color)):
                record=self.safe('libtool: error: unexpected '+color+operand+'\x1b[0m while linking\n')
                self.assertIn('unexpected',output(record));self.assertNotIn('while linking',output(record))
                self.assertIn('[compiler-define redacted]',output(record))

    def test_multiple_defines_and_malformed_defines_do_not_leak(self):
        record=self.safe('libtool: error: unexpected -DONE="INVALID TEST VALUE" -DTWO=INVALID_TEST_OTHER while linking\n')
        self.assertNotIn('while linking',output(record))
        for operand in ('-DPRIVATE="INVALID TEST VALUE',"-DPRIVATE='INVALID TEST VALUE",'-DPRIVATE=\\"INVALID TEST VALUE'):
            self.safe('libtool: error: invalid '+operand+'\n')

    def test_controls_and_malformed_quote_cannot_hide_known_command(self):
        self.safe('\x1b]0;window\x07"/usr/bin/nm" INVALID_TEST_VALUE\n')
        self.safe('"/usr/bin/nm INVALID_TEST_VALUE\n')
        self.safe('\x1b[unterminated env CUSTOM=INVALID_TEST_VALUE\n')

    def test_secret_free_unfamiliar_error_and_continuation_prose_is_preserved(self):
        messages=(
            'libtool:   error: cannot extract exported symbols from the selected library',
            'libtool:          please inspect whether the symbol extraction command succeeded',
            'ld: unsupported tapi file type in the selected SDK stub',
            'libtool: link: warning: unknown public archive format',
            'libtool: compile: error: a new compiler failure which is not in the fixed grammar',
            'clang: error: archive indexing did not provide the expected table',
            'libtool:          password handling is unrelated to this archive error',
            'libtool:          token was not a recognized public parser category',
        )
        record=self.safe('\n'.join(messages)+'\n')
        for message in messages:self.assertIn(message,output(record))
        self.assertEqual(record['stderr_excerpt']['omitted_lines'],0)

    def test_no_category_only_fallback_and_current_failure_sized_fixture_complete(self):
        messages=['public diagnostic context '+str(i)+' '+('word '*7) for i in range(21)]
        messages+=['libtool:   error: novel static archive index failure','make: *** [libpkgconf.la] Error 1']
        extra=2119-len(('\n'.join(messages)+'\n').encode());self.assertGreater(extra,0)
        for i in range(extra):messages[i%21]+='x'
        raw='\n'.join(messages)+'\n';self.assertEqual(len(raw.encode()),2119)
        record=self.safe(raw)
        self.assertEqual(len(record['stderr_excerpt']['lines']),23)
        self.assertEqual(record['stderr_excerpt']['omitted_lines'],0)
        self.assertIn('novel static archive index failure',output(record))

    def test_new_regressions_receipt_bound_and_current_revision_closed(self):
        receipt=json.loads((HERE/'review-receipt.json').read_text())
        for name in ('test_disclosure_structures.py','disclosure-regression-fixtures.json','build_diagnostics.py'):
            self.assertEqual(receipt['sha256'][name],hashlib.sha256((HERE/name).read_bytes()).hexdigest())
        self.assertEqual(receipt['candidate_revision'],9)
        for gate in ('execution_approved','independent_review_passed','temporary_linker_adhoc_signing_approved','install_name_linker_assignment_approved'):
            self.assertIs(receipt[gate],False)

if __name__=='__main__':unittest.main(verbosity=2)
