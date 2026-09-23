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

    def test_archive_failure_resumes_without_sending_again(self):
        raw = {'stats': {'active_member_count': 1, 'commit_count': 2, 'active_pr_count': 1,
                        'by_member': {'dev': {'display_name': 'Dev', 'commit_count': 2, 'active_pr_count': 1}}}}
        body = '过去 24 小时团队 1 人活跃，共 2 次提交、1 个活跃 PR，主线是测试。\n\n**Dev**（2 提交 / 1 PR）\n完成测试。'
        cfg = {'delivery': {'targets': [{'type': 'user', 'id': 'ou_test'}]},
               'lark': {'daily_log_doc': {'token': 'doc', 'url': 'https://example.test/doc'}}}
        state = {'marker': 'daily-test', 'date': '2026-09-22'}
        calls = []
        inserted = False
        def api(*args, **kwargs):
            nonlocal inserted
            calls.append(args)
            if args[1] == '+messages-send':
                return {'ok': True, 'data': {'message_id': MESSAGE_ID}}
            if args[1] == '+messages-mget':
                return {'ok': True, 'data': {'messages': [{'message_id': MESSAGE_ID}]}}
            if args[1] == '+fetch':
                return {'ok': True, 'data': {'document': {'content': '<p>daily-test</p>' if inserted else ''}}}
            if args[1] == '+update':
                inserted = True
                raise TimeoutError('response lost after archive insert')
            self.fail(args)
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / 'raw.json').write_text(json.dumps(raw))
            (folder / 'body.md').write_text(body)
            with patch.object(MODULE, 'lark', side_effect=api), patch.object(MODULE, 'run'):
                with self.assertRaises(TimeoutError):
                    MODULE.deliver(folder, cfg, state)
                # Reload persisted state as after a process restart.
                state = json.loads((folder / 'state.json').read_text())
                MODULE.deliver(folder, cfg, state)
                self.assertTrue(state['archived'])
                self.assertEqual(sum(c[1] == '+messages-send' for c in calls), 1)
                self.assertEqual(sum(c[1] == '+update' for c in calls), 1)
                (folder / 'body.md').write_text(body + '\n意外修改')
                with self.assertRaises(RuntimeError):
                    MODULE.deliver(folder, cfg, state)


class AmbiguousArchiveTest(unittest.TestCase):
    def test_partial_insert_with_lost_response_is_not_inserted_again(self):
        raw = {'stats': {'active_member_count': 0, 'commit_count': 0,
                        'active_pr_count': 0, 'by_member': {}}}
        config = {'delivery': {'targets': [{'type': 'user', 'id': 'ou_test'}]},
                  'lark': {'daily_log_doc': {'token': 'doc', 'url': 'https://example.test/doc'}}}
        state = {'marker': 'daily-test', 'date': '2026-09-22'}
        inserts = []

        def api(*args, **kwargs):
            if args[1] == '+messages-send':
                return {'ok': True, 'data': {'message_id': MESSAGE_ID}}
            if args[1] == '+messages-mget':
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
            (folder / 'body.md').write_text('过去 24 小时团队 0 人活跃，共 0 次提交、0 个活跃 PR，窗口内无活动。')
            with patch.object(MODULE, 'lark', side_effect=api), patch.object(MODULE, 'run'):
                with self.assertRaises(TimeoutError):
                    MODULE.deliver(folder, config, state)
                state = json.loads((folder / 'state.json').read_text())
                with self.assertRaisesRegex(RuntimeError, '[Uu]nconfirmed archive'):
                    MODULE.deliver(folder, config, state)
            self.assertEqual(len(inserts), 1)


if __name__ == '__main__':
    unittest.main()
