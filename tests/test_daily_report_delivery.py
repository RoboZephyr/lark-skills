import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/progress-report/scripts'
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location('daily_report', SCRIPTS / 'run_daily_report.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
MESSAGE_ID = 'om_x' + '1' * 31


class LarkProfileTest(unittest.TestCase):
    def test_explicit_profile_applies_to_reads_and_writes(self):
        with patch.dict(MODULE.os.environ, {'LARK_CLI_PROFILE': 'test-app'}, clear=True), \
                patch.object(MODULE, 'run', return_value='{"ok": true}') as run:
            MODULE.lark('docs', '+fetch', '--doc', 'test-doc')
            MODULE.lark('im', '+messages-send', '--user-id', 'test-user')
        for call in run.call_args_list:
            argv = call.args[0]
            self.assertEqual(argv[:3], ['lark-cli', '--profile', 'test-app'])
            self.assertEqual(argv[-4:], ['--as', 'bot', '--format', 'json'])

    def test_unconfigured_profile_keeps_cli_default(self):
        for env in ({}, {'LARK_CLI_PROFILE': ''}):
            with self.subTest(env=env), patch.dict(MODULE.os.environ, env, clear=True), \
                    patch.object(MODULE, 'run', return_value='{"ok": true}') as run:
                MODULE.lark('docs', '+fetch', '--doc', 'test-doc')
                self.assertNotIn('--profile', run.call_args.args[0])


class DeliveryTest(unittest.TestCase):
    def test_archive_search_attribute_is_not_delivery_proof(self):
        self.assertFalse(MODULE.document_has_marker('<fragment keyword="daily-test"><p>daily-other</p></fragment>', 'daily-test'))
        self.assertTrue(MODULE.document_has_marker('<fragment><p>统计标识：daily-test</p></fragment>', 'daily-test'))

    def test_requires_successful_structured_receipt(self):
        for receipt in ({'text': 'om_workflow'}, {'ok': True, 'data': {'message_id': 'om_workflow'}},
                        {'ok': False, 'data': {'message_id': MESSAGE_ID}}):
            with self.assertRaises(ValueError):
                MODULE.sent_message_id(receipt)
        self.assertEqual(MODULE.sent_message_id({'ok': True, 'data': {'message_id': MESSAGE_ID}}), MESSAGE_ID)

class AccountingNarrativeTest(unittest.TestCase):
    def test_prepare_generates_statistics_in_code_without_delivering(self):
        from progress_accounting import enrich
        raw = enrich({'repos': [], 'commits': [], 'prs': [], 'members': {
            'dev': {'display_name': 'Dev', 'aliases': ['dev']}},
            'since': '2026-10-23T13:00:00Z', 'until': '2026-10-24T13:00:00Z',
            'date_range': '2026-10-23 21:00至2026-10-24 21:00'}, lambda c: None)
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / 'raw.json').write_text(json.dumps(raw))
            (folder / 'report.md').write_text('fact sheet')
            def generate(argv, **kwargs):
                context = json.loads((folder / 'narrative-context.json').read_text())
                self.assertEqual(context['commits'], [])
                self.assertIn(str(folder / 'narrative-context.json'), argv[-1])
                (folder / 'narrative.md').write_text('本期无工程活动。\n\n**Dev**\n- 窗口内未采集到代码或 PR 活动。')
            with patch.object(MODULE, 'run', side_effect=generate), patch.object(MODULE, 'lark') as lark:
                MODULE.process(folder, {}, {'since': raw['since'], 'until': raw['until'], 'range': raw['date_range']}, prepare_only=True)
                lark.assert_not_called()
            MODULE.validate_body((folder / 'body.md').read_text(), raw)
            self.assertNotIn('统计附表', (folder / 'body.md').read_text())
            self.assertIn('统计附表', (folder / 'statistics.md').read_text())

class AmbiguousArchiveTest(unittest.TestCase):
    def test_partial_insert_with_lost_response_is_not_inserted_again(self):
        raw = {'accounting_version': 2, 'until': '2026-01-02T13:00:00Z',
               'stats': {'by_member': {}}}
        config = {'delivery': {'targets': [{'type': 'user', 'id': 'ou_test'}]},
                  'lark': {'daily_log_doc': {'token': 'doc', 'url': 'https://example.test/doc'}}}
        state = {'marker': 'daily-test', 'date': '2026-09-22'}
        inserts = []

        def api(*args, **kwargs):
            if args[1] == '+messages-send':
                self.assertEqual(kwargs.get('identity'), 'bot')
                return {'ok': True, 'data': {'message_id': MESSAGE_ID}}
            if args[1] == '+messages-mget':
                self.assertEqual(kwargs.get('identity'), 'bot')
                return {'ok': True, 'data': {'messages': [{'message_id': MESSAGE_ID}]}}
            if args[1] == '+fetch':
                # A partially inserted document has no trailing run marker.
                content = '<p>日报开头已写入</p>' if inserts else ''
                return {'ok': True, 'data': {'document': {'content': content}}}
            if args[1] == '+update':
                inserts.append(args)
                raise TimeoutError('response lost after only some blocks were inserted')
            self.fail(args)

        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / 'raw.json').write_text(json.dumps(raw))
            (folder / 'body.md').write_text('窗口内无活动。')
            with patch.object(MODULE, 'lark', side_effect=api), patch.object(MODULE, 'run'):
                with self.assertRaises(TimeoutError):
                    MODULE.deliver(folder, config, state)
                state = json.loads((folder / 'state.json').read_text())
                with self.assertRaisesRegex(RuntimeError, '[Uu]nconfirmed archive'):
                    MODULE.deliver(folder, config, state)
            self.assertEqual(len(inserts), 1)


if __name__ == '__main__':
    unittest.main()
