"""Inert exact-symbol regression tests; never runs nm or a native payload."""
import ast
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent

def load(name):
    spec = importlib.util.spec_from_file_location('export_test_' + name, HERE / (name + '.py'))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module

contract, stage = load('glib_export_contract'), load('stage')

def fixture(names=contract.REQUIRED):
    return b''.join(f'00000000000010{i:02x} {"D" if name.startswith("_") else "T"} _{name}\n'.encode() for i, name in enumerate(names))

class ExportContractTests(unittest.TestCase):
    def test_exact_six_required_exports_pass_with_single_and_double_prefix(self):
        self.assertEqual(contract.source_libiconv(fixture(), list(contract.REQUIRED)),
            {'status': 'passed', 'required_export_count': 6, 'missing_required_names': []})

    def test_old_parser_cannot_accept_required_version_spelling(self):
        self.assertNotIn(b'__libiconv_version', set(re.findall(rb'\b_[A-Za-z][A-Za-z0-9_]*$', fixture(), re.M)))
        self.assertEqual(contract._LINE.fullmatch(b'0000000000001000 D __libiconv_version')[1], b'__libiconv_version')

    def test_complete_c_identifier_grammar_including_multiple_underscores(self):
        for symbol in (b'_libiconv', b'__libiconv_version', b'___private_c_name', b'__9'):
            self.assertEqual(contract._LINE.fullmatch(b'00000001 T ' + symbol)[1], symbol)
        for symbol in (b'_9invalid', b'_', b'prefix__libiconv_version', b'__libiconv_version.extra'):
            self.assertIsNone(contract._LINE.fullmatch(b'00000001 T ' + symbol))

    def test_single_or_extra_underscore_is_not_version_symbol(self):
        for wrong in (b'_libiconv_version', b'___libiconv_version'):
            result = contract.source_libiconv(fixture().replace(b'__libiconv_version', wrong), contract.REQUIRED)
            self.assertEqual(result['missing_required_names'], ['_libiconv_version'])
            self.assertEqual(result['status'], 'failed')

    def test_each_required_symbol_is_individually_enforced(self):
        for missing in contract.REQUIRED:
            result = contract.source_libiconv(fixture(tuple(x for x in contract.REQUIRED if x != missing)), contract.REQUIRED)
            self.assertEqual(result['missing_required_names'], [missing])
            self.assertEqual(result['required_export_count'], 6)
            self.assertEqual(result['status'], 'failed')

    def test_missing_all_is_fixed_order_and_bounded(self):
        result = contract.source_libiconv(b'', contract.REQUIRED)
        self.assertEqual(result['missing_required_names'], list(contract.REQUIRED))
        self.assertLess(len(json.dumps(result)), 512)

    def test_required_set_cannot_be_reduced_renamed_reordered_or_duplicated(self):
        for invalid in (contract.REQUIRED[:-1], contract.REQUIRED[::-1], contract.REQUIRED + ('extra',),
                        ['replacement'] * 6, set(contract.REQUIRED), 'libiconv'):
            with self.assertRaisesRegex(ValueError, '^fixed_export_requirement_mismatch$'):
                contract.source_libiconv(fixture(), invalid)

    def test_unrelated_valid_names_and_invalid_inert_sentinel_are_not_disclosed(self):
        output = fixture() + b'0000000000002000 D _INVALID_INERT_SENTINEL_DO_NOT_USE\nINVALID_INERT_PRIVATE_PATH\n'
        result = contract.source_libiconv(output, contract.REQUIRED)
        self.assertNotIn('INVALID_INERT', json.dumps(result))
        self.assertNotIn('2000', json.dumps(result))
        self.assertEqual(result['status'], 'passed')

    def test_partial_substrings_undefined_or_malformed_records_do_not_satisfy(self):
        for line in (b'__libiconv_version', b'         U __libiconv_version',
                     b'00000001 D prefix__libiconv_version', b'00000001 D __libiconv_version suffix',
                     b'nothex D __libiconv_version', b'00000001 DD __libiconv_version'):
            result = contract.source_libiconv(fixture(contract.REQUIRED[:-1]) + line + b'\n', contract.REQUIRED)
            self.assertEqual(result['missing_required_names'], ['_libiconv_version'])

    def test_tabs_crlf_and_duplicate_records_keep_exact_result(self):
        output = fixture().replace(b' ', b'\t').replace(b'\n', b'\r\n')
        self.assertEqual(contract.source_libiconv(output + output, contract.REQUIRED)['status'], 'passed')

    def test_output_type_and_existing_capture_bound(self):
        for invalid in (None, '', bytearray(fixture())):
            with self.assertRaisesRegex(ValueError, '^bounded_export_output_required$'):
                contract.source_libiconv(invalid, contract.REQUIRED)
        self.assertEqual(contract.MAX_OUTPUT, stage.OUTPUT_LIMIT)
        with mock.patch.object(contract, 'MAX_OUTPUT', 4):
            with self.assertRaisesRegex(ValueError, '^bounded_export_output_required$'):
                contract.source_libiconv(b'12345', contract.REQUIRED)

    def test_source_declaration_definition_and_required_call_are_unchanged(self):
        self.assertIn('extern @DLL_VARIABLE@ int _libiconv_version;', (HERE / 'source-review/libiconv/include/iconv.h.in').read_text())
        self.assertIn('int _libiconv_version = _LIBICONV_VERSION;', (HERE / 'source-review/libiconv/lib/iconv.c').read_text())
        tree = ast.parse((HERE / 'iconv_make_stage.py').read_text())
        call = next(n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == 'symbols' and n.args[0].value == 'source-libiconv')
        self.assertEqual(tuple(ast.literal_eval(call.args[2])), contract.REQUIRED)
        self.assertEqual(hashlib.sha256((HERE / 'foundation_stage.py').read_bytes()).hexdigest(), '38f83e48f482bed4051809f7b3aa489e6204bb0cbbca0c929422b1dbb3fc7e2c')

    def test_non_iconv_labels_delegate_to_original_foundation(self):
        lane = object.__new__(stage.Lane)
        with mock.patch.object(stage.foundation.Lane, 'symbols', return_value='inert_delegated') as original:
            for label in ('pcre2', 'libintl', 'source-libffi', 'source-libcharset', 'corrected-libintl'):
                self.assertEqual(lane.symbols(label, Path('/inert'), ['example']), 'inert_delegated')
                original.assert_called_with(label, Path('/inert'), ['example'])

    def test_override_keeps_nm_command_and_emits_only_fixed_missing_contract(self):
        lane = object.__new__(stage.Lane); lane.helpers = HERE; lane.tools = {'nm': '/inert/nm'}
        lane.run = mock.Mock(return_value=(fixture(contract.REQUIRED[:-1]), b'', {}))
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured), self.assertRaises(stage.foundation.LaneError):
            lane.symbols('source-libiconv', Path('/inert/library'), list(contract.REQUIRED))
        lane.run.assert_called_once_with('exports-source-libiconv', ['/inert/nm', '-gU', Path('/inert/library')], timeout=30)
        self.assertEqual(json.loads(captured.getvalue()), {'phase': 'export-contract-source-libiconv', 'status': 'failed',
            'required_export_count': 6, 'missing_required_names': ['_libiconv_version']})

if __name__ == '__main__':
    unittest.main()
