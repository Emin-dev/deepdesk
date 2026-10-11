"""Inert exact-byte and quote-combination fixtures for conservative -D suffix removal."""
from pathlib import Path
import hashlib
import importlib.util
import itertools
import json
import sys
sys.dont_write_bytecode=True
import unittest
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('suffix_build_diagnostics',HERE/'build_diagnostics.py')
d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d)

def summarize(raw):
    if isinstance(raw,str):raw=raw.encode()
    return d.summarize('pkgconf-build',b'',raw,HERE/'build-diagnostic-catalog.json','/safe/immutable','/safe/phase','/safe/control')

def output(record):return '\n'.join(row['text'] for row in record['stderr_excerpt']['lines'])

class DefinitionSuffixTests(unittest.TestCase):
    def safe(self,raw):
        record=summarize(raw);encoded=json.dumps(record)
        for secret in ('SHORTPRIVATE','SECONDPRIVATE','SECRET TRAILING VALUE'):
            self.assertNotIn(secret,encoded)
        self.assertLessEqual(len(encoded.encode()),d.MAX_REPORT_BYTES)
        self.assertLessEqual(len(json.dumps(record['stderr_excerpt']).encode()),d.MAX_EXCERPT_BYTES)
        return record

    def test_four_exact_review_text_and_hex_fixtures(self):
        path=HERE/'nested-definition-regression-fixtures.json'
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),'7fb9d89f43cab9ff46ab14e52618c4a8edef76e65998ad63c1bcb1c591828ba9')
        rows=json.loads(path.read_text());self.assertEqual(len(rows),4)
        for row in rows:
            with self.subTest(case=row['case']):
                raw=bytes.fromhex(row['synthetic_stderr_hex']);self.assertEqual(raw,row['synthetic_stderr'].encode())
                record=self.safe(raw)
                self.assertEqual(output(record),'libtool: error: unexpected [compiler-define redacted]')
                self.assertNotIn('while linking',output(record))

    def test_nested_escaped_quote_combinations_do_not_need_parsing(self):
        # 2 quote forms x 5 outer escape lengths x 9 inner lengths x 4 -D forms.
        for quote,outer_count,inner_count,flag in itertools.product(('"',"'"),range(5),range(9),('-DNAME=','-D NAME=','-D\tNAME=','"-DNAME=')):
            with self.subTest(quote=quote,outer=outer_count,inner=inner_count,flag=flag):
                outer='\\'*outer_count+quote;inner='\\'*inner_count+quote
                raw='libtool: error: unexpected '+flag+outer+'prefix '+inner+'SHORTPRIVATE'+inner+' suffix'+outer+' SECRET TRAILING VALUE\n'
                record=self.safe(raw)
                self.assertIn('libtool: error: unexpected',output(record))
                self.assertIn('[compiler-define redacted]',output(record))
                self.assertNotIn(' suffix',output(record))

    def test_first_definition_discards_everything_after_it_only_on_that_line(self):
        for definition in ('-DNAME=SHORTPRIVATE','-D NAME="SHORTPRIVATE"','-DNAME=\\"SHORTPRIVATE','-D','-D\\"NAME=SHORTPRIVATE'):
            record=self.safe('libtool: error: unsupported '+definition+' -DOTHER=SECONDPRIVATE SECRET TRAILING VALUE\nlibtool:   error: archive symbol extraction failed\n')
            self.assertIn('libtool: error: unsupported [compiler-define redacted]',output(record))
            self.assertIn('libtool:   error: archive symbol extraction failed',output(record))

    def test_nondefinition_unfamiliar_errors_and_continuations_remain_exact(self):
        rows=['libtool:   error: cannot extract exported symbols from this static library',
              'libtool:          please inspect whether the symbol extraction command succeeded',
              'ld: unsupported tapi file type in the selected SDK stub',
              'libtool: link: warning: unfamiliar public archive format',
              'libtool: error: Mach-Darwin library format is unsupported']
        record=self.safe('\n'.join(rows)+'\n')
        self.assertEqual(output(record),'\n'.join(rows))
        self.assertFalse(hasattr(d,'_shell_word_spans'))

    def test_prior_sized_23_line_2119_byte_fixture_is_still_complete(self):
        rows=['public build error context '+str(i)+' '+('word '*6) for i in range(21)]
        rows+=['libtool:   error: unfamiliar underlying archive-index failure','make: *** [libpkgconf.la] Error 1']
        padding=2119-len(('\n'.join(rows)+'\n').encode());self.assertGreater(padding,0)
        for i in range(padding):rows[i%21]+='x'
        raw='\n'.join(rows)+'\n';self.assertEqual(len(raw.encode()),2119)
        record=self.safe(raw)
        self.assertEqual(len(record['stderr_excerpt']['lines']),23)
        self.assertEqual(record['stderr_excerpt']['omitted_lines'],0)
        self.assertIn('unfamiliar underlying archive-index failure',output(record))

    def test_receipt_binds_current_revision_and_exact_regression_data(self):
        receipt=json.loads((HERE/'review-receipt.json').read_text())
        self.assertEqual(receipt['candidate_revision'],10)
        for name in ('test_definition_suffix.py','nested-definition-regression-fixtures.json','build_diagnostics.py'):
            self.assertEqual(receipt['sha256'][name],hashlib.sha256((HERE/name).read_bytes()).hexdigest())
        for gate in ('execution_approved','independent_review_passed','temporary_linker_adhoc_signing_approved','install_name_linker_assignment_approved'):
            self.assertIs(receipt[gate],False)

if __name__=='__main__':unittest.main(verbosity=2)
