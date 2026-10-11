"""Inert first-party regression fixtures; no downloaded code or native execution."""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('facts', HERE / 'iconv_config_facts.py')
facts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(facts)


class IconvDiagnosticTests(unittest.TestCase):
    def fixture(self, *, result=2, works='no', have=False):
        log = (f'configure:26816: compiler command intentionally not disclosed\n'
               f'configure:26816: $? = 0\nconfigure:26816: ./conftest\n'
               f'configure:26816: $? = {result}\n'
               f'am_cv_func_iconv=yes\nam_cv_func_iconv_works={works}\nam_cv_lib_iconv=no\n').encode()
        header = b'#define HAVE_ICONV 1\n' if have else b'/* #undef HAVE_ICONV */\n'
        make = f'HAVE_ICONV = {int(have)}\nLIBICONV = \nLTLIBICONV = \n'.encode()
        return log, header, make

    def test_semantic_rejection_is_an_observation_not_a_causal_claim(self):
        report = facts.parse(*self.fixture())
        self.assertTrue(report['facts_complete'])
        self.assertEqual(report['facts']['working_iconv_run_exit_codes'], facts.known([2]))
        self.assertEqual(report['facts']['config_header_have_iconv'], facts.known(False))
        self.assertEqual(report['causal_claim'], 'none')

    def test_supported_iconv_remains_reported_without_overriding_it(self):
        report = facts.parse(*self.fixture(result=0, works='yes', have=True))
        self.assertEqual(report['facts']['am_cv_func_iconv_works'], facts.known('yes'))
        self.assertEqual(report['facts']['make_have_iconv'], facts.known(True))

    def test_no_iconv_detection_does_not_require_a_nonexistent_runtime_test(self):
        _, header, make = self.fixture()
        report = facts.parse(b"am_cv_func_iconv='no, consider installing GNU libiconv'\nam_cv_lib_iconv=no\n", header, make)
        self.assertTrue(report['facts_complete'])
        self.assertEqual(report['facts']['working_iconv_run_exit_codes'], facts.unknown())

    def test_unknown_cache_values_are_rejected_without_echo(self):
        log, header, make = self.fixture()
        report = facts.parse(log.replace(b'am_cv_func_iconv=yes', b'am_cv_func_iconv=INVALID_INERT_SECRET_DO_NOT_USE'), header, make)
        self.assertFalse(report['facts_complete'])
        self.assertNotIn('INVALID_INERT_SECRET_DO_NOT_USE', json.dumps(report))

    def test_unrelated_sensitive_lines_are_never_disclosed(self):
        log, header, make = self.fixture()
        report = facts.parse(log + b'password=INVALID_INERT_SECRET_DO_NOT_USE\nAuthorization: INVALID_INERT_SENTINEL\n', header, make)
        self.assertNotIn('INVALID_INERT', json.dumps(report))
        self.assertNotIn('compiler command', json.dumps(report))
        self.assertLessEqual(len(json.dumps(report).encode()), 4096)

    def test_duplicate_cache_values_are_ambiguous(self):
        log, header, make = self.fixture()
        report = facts.parse(log + b'am_cv_func_iconv=yes\n', header, make)
        self.assertEqual(report['facts']['am_cv_func_iconv'], facts.unknown('ambiguous'))

    def test_header_conflicts_and_expressions_are_not_guessed(self):
        log, header, make = self.fixture()
        report = facts.parse(log, header + b'#define HAVE_ICONV 1\n', make)
        self.assertEqual(report['facts']['config_header_have_iconv'], facts.unknown('ambiguous'))
        report = facts.parse(log, b'#define HAVE_ICONV SECRET_EXPRESSION\n', make)
        self.assertEqual(report['facts']['config_header_have_iconv'], facts.unknown('rejected'))

    def test_link_flags_are_classified_without_paths(self):
        log, header, _ = self.fixture()
        report = facts.parse(log, header, b'HAVE_ICONV = 0\nLIBICONV = -liconv\nLTLIBICONV = /INVALID_INERT_PRIVATE_PATH/libiconv.dylib\n')
        self.assertEqual(report['facts']['make_libiconv'], facts.known('sdk_link_flag'))
        self.assertEqual(report['facts']['make_ltlibiconv'], facts.known('other_link_expression'))
        self.assertNotIn('INVALID_INERT_PRIVATE_PATH', json.dumps(report))

    def test_only_execution_status_is_extracted_not_compile_status(self):
        content = b'configure:26816: $? = 1\nconfigure:26816: ./conftest\nconfigure:26816: $? = 2\n'
        self.assertEqual(facts.probe_exits(content.splitlines()), facts.known([2]))

    def test_two_upstream_const_variants_are_bounded(self):
        attempt = b'configure:26816: ./conftest\nconfigure:26816: $? = 2\n'
        self.assertEqual(facts.probe_exits((attempt * 2).splitlines()), facts.known([2, 2]))
        self.assertEqual(facts.probe_exits((attempt * 3).splitlines()), facts.unknown('rejected'))

    def test_invalid_exit_status_and_wrong_source_line_are_rejected(self):
        self.assertEqual(facts.probe_exits(b'configure:26816: ./conftest\nconfigure:26816: $? = 999\n'.splitlines()), facts.unknown('rejected'))
        self.assertEqual(facts.probe_exits(b'configure:26817: ./conftest\nconfigure:26817: $? = 2\n'.splitlines()), facts.unknown())

    def test_oversized_and_missing_inputs_are_explicit_unknowns(self):
        _, header, make = self.fixture()
        for log in (None, 'not bytes', b'x' * (facts.MAX_LOG + 1), b'x' * (facts.MAX_LINE + 1)):
            report = facts.parse(log, header, make)
            self.assertFalse(report['facts_complete'])
            self.assertEqual(report['facts']['am_cv_func_iconv'], facts.unknown('unavailable_or_rejected'))

    def test_collect_no_follow_and_missing_file_handling(self):
        with tempfile.TemporaryDirectory() as td:
            phase = Path(td).resolve()
            (phase / 'config.log').symlink_to('/dev/null')
            report = facts.collect(phase)
            self.assertFalse(report['facts_complete'])
            self.assertEqual(report['facts']['am_cv_func_iconv'], facts.unknown('unavailable_or_rejected'))

    def test_source_bound_working_test_and_exit_bits(self):
        contract = json.loads((HERE / 'iconv-diagnostic-contract.json').read_text())
        source = (HERE / 'source-review/gettext/libtextstyle/configure').read_bytes()
        self.assertEqual(hashlib.sha256(source).hexdigest(), contract['configure_sha256'])
        self.assertEqual(source.splitlines()[facts.PROBE_LINE - 1], b'if ac_fn_c_try_run "$LINENO"')
        region = source.splitlines()[26642:26818]
        for bit in (1, 2, 4, 8, 32):
            self.assertIn(f'result |= {bit};'.encode(), b'\n'.join(region))

    def test_constructor_is_conditional_but_export_and_object_are_unconditional(self):
        source = (HERE / 'source-review/gettext/libtextstyle/lib/iconv-ostream.c').read_text()
        region = source[source.index('#if HAVE_ICONV', source.index('#if HAVE_ICONV') + 1):]
        active, fallback = region.split('#else', 1)
        self.assertIn('iconv_ostream_create (', active)
        self.assertNotIn('iconv_ostream_create (', fallback)
        self.assertIn('iconv_ostream_create\n', (HERE / 'source-review/gettext/libtextstyle/lib/libtextstyle.sym.in').read_text())
        self.assertIn('libtextstyle_la-ialloc.lo libtextstyle_la-iconv-ostream.lo', (HERE / 'source-review/gettext/libtextstyle/lib/Makefile.in').read_text())

    def test_commands_through_configure_are_byte_identical(self):
        source = (HERE / 'stage.py').read_text()
        prefix = source[source.index('    def execute(self, trees):'):source.index("        iconv_facts = load(")]
        contract = json.loads((HERE / 'iconv-diagnostic-contract.json').read_text())
        self.assertEqual(hashlib.sha256(prefix.encode()).hexdigest(), contract['unchanged_execute_prefix_sha256'])

    def test_no_build_or_claim_can_follow_diagnostic_configure(self):
        tree = ast.parse((HERE / 'stage.py').read_text())
        lane = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Lane')
        execute = next(n for n in lane.body if isinstance(n, ast.FunctionDef) and n.name == 'execute')
        calls = [n for n in ast.walk(execute) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == 'run']
        self.assertEqual(calls[-1].args[0].value, 'libtextstyle-configure')
        self.assertNotIn('promote_glib', {n.name for n in lane.body if isinstance(n, ast.FunctionDef)})
        self.assertNotIn('combined-prerequisite-result', (HERE / 'stage.py').read_text())
        workflow = (HERE / 'glib-runtime-macos.yml.template').read_text()
        self.assertIn('stopped before libtextstyle make', workflow)
        self.assertIn('not a repaired native build', workflow)


if __name__ == '__main__':
    unittest.main()
