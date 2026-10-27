import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/progress-report/scripts'))
from daily_report_card import build_card
import run_daily_report as report


class CardTest(unittest.TestCase):
    def setUp(self):
        self.raw = {'accounting_version': 2, 'until': '2026-10-24T13:00:00Z', 'stats': {'by_member': {
            'dev': {'display_name': 'Dev', 'active_pr_count': 3, 'observed_commit_count': 5,
                    'prs': {'merged_main': 2, 'ongoing': 1}},
            'idle': {'display_name': 'Idle', 'active_pr_count': 0, 'observed_commit_count': 0, 'prs': {}}}}}
        self.body = '发布检查已合入，启用待验证。\n\n**Dev**\n- **发布保护｜已合入**：环境验证待完成。\n\n**Idle**\n- 本期无活动。\n\n**团队待关注**\n- Dev 核对环境启用。'

    def test_preserves_approved_layout_and_uses_audited_numbers(self):
        card = build_card(self.body, self.raw)
        self.assertEqual(card['schema'], '2.0')
        self.assertIn('21:00', card['header']['subtitle']['content'])
        self.assertEqual(len(card['body']['elements']), 3)
        self.assertTrue(card['body']['elements'][1]['expanded'])
        text = json.dumps(card, ensure_ascii=False)
        for value in ['主干合入 2', '期内仍开放 1', 'Idle：本期未采集到', '环境验证待完成']:
            self.assertIn(value, text)
        self.assertNotIn('阅读口径', text)

    def test_rejects_missing_member_and_unstructured_prose(self):
        for body in [self.body.replace('**Dev**', '**Wrong**'),
                     self.body.replace('- **发布保护', '**发布保护'),
                     self.body + '\n阅读口径：说明']:
            with self.assertRaises(ValueError):
                build_card(body, self.raw)

    def test_card_delivery_recovers_archive_failure_without_resending(self):
        state = {'date': '2026-10-24', 'marker': 'daily-card-test'}
        config = {'delivery': {'targets': [{'type': 'user', 'id': 'ou_test'}]},
                  'lark': {'daily_log_doc': {'token': 'doc', 'url': 'https://example.test/doc'}}}
        mid = 'om_x' + '1' * 31
        sent, inserted = [], []
        def api(*args, **kwargs):
            if args[1] == '+messages-send':
                self.assertEqual(kwargs['identity'], 'bot')
                self.assertIn('interactive', args)
                self.assertNotIn('--markdown', args)
                sent.append(json.loads(args[args.index('--content') + 1]))
                return {'ok': True, 'data': {'message_id': mid}}
            if args[1] == '+messages-mget':
                self.assertEqual(kwargs['identity'], 'bot')
                return {'ok': True, 'data': {'messages': [{'message_id': mid}]}}
            if args[1] == '+fetch':
                return {'ok': True, 'data': {'document': {'content': '<p>daily-card-test</p>' if inserted else ''}}}
            if args[1] == '+update':
                inserted.append(True)
                raise TimeoutError('response lost')
            self.fail(args)
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / 'raw.json').write_text(json.dumps(self.raw))
            (folder / 'body.md').write_text(self.body)
            with patch.object(report, 'lark', side_effect=api), patch.object(report, 'run'):
                with self.assertRaises(TimeoutError):
                    report.deliver(folder, config, state)
                state = json.loads((folder / 'state.json').read_text())
                report.deliver(folder, config, state)
                self.assertTrue(state['archived'])
                self.assertEqual(len(sent), 1)
                self.assertEqual(len(inserted), 1)
                self.assertEqual(json.loads((folder / 'card.json').read_text()), sent[0])
                self.raw['stats']['by_member']['dev']['prs']['merged_main'] = 9
                (folder / 'raw.json').write_text(json.dumps(self.raw))
                with self.assertRaises(RuntimeError):
                    report.deliver(folder, config, state)


    def test_ambiguous_card_send_retries_with_same_key_and_payload(self):
        state = {'date': '2026-10-24', 'marker': 'retry-card', 'archived': True}
        config = {'delivery': {'targets': [{'type': 'user', 'id': 'ou_test'}]},
                  'lark': {'daily_log_doc': {'token': 'doc', 'url': 'https://example.test/doc'}}}
        mid = 'om_x' + '1' * 31
        attempts = []
        def api(*args, **kwargs):
            if args[1] == '+messages-send':
                attempts.append(args)
                if len(attempts) == 1:
                    raise TimeoutError('send response lost')
                return {'ok': True, 'data': {'message_id': mid}}
            return {'ok': True, 'data': {'messages': [{'message_id': mid}]}}
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / 'raw.json').write_text(json.dumps(self.raw))
            (folder / 'body.md').write_text(self.body)
            with patch.object(report, 'lark', side_effect=api), patch.object(report, 'run'), patch.object(report.time, 'time', return_value=100):
                with self.assertRaises(TimeoutError):
                    report.deliver(folder, config, state)
                state = json.loads((folder / 'state.json').read_text())
                report.deliver(folder, config, state)
                report.deliver(folder, config, state)
            self.assertEqual(len(attempts), 2)
            self.assertEqual(attempts[0], attempts[1])

    def test_expired_ambiguous_card_send_is_not_repeated(self):
        state = {'date': '2026-10-24', 'marker': 'expired-card', 'archived': True,
                 'send_attempted_at': {'ou_test': 100}}
        config = {'delivery': {'targets': [{'type': 'user', 'id': 'ou_test'}]},
                  'lark': {'daily_log_doc': {'token': 'doc', 'url': 'https://example.test/doc'}}}
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / 'raw.json').write_text(json.dumps(self.raw))
            (folder / 'body.md').write_text(self.body)
            with patch.object(report, 'lark') as api, patch.object(report, 'run'), patch.object(report.time, 'time', return_value=4000):
                with self.assertRaisesRegex(RuntimeError, 'idempotency window'):
                    report.deliver(folder, config, state)
                api.assert_not_called()
