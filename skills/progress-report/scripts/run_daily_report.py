#!/usr/bin/env python3
"""Resumable daily report: collect, write, validate, send, archive.

Only the narrative is delegated to Codex. Delivery receipts come directly from
Lark JSON; neither model prose nor a string in its log can mark a run successful.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from xml.etree import ElementTree

from collect_progress import load_config, parse_range

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = Path(__file__).parent


def save(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def run(argv, *, cwd=ROOT, timeout=180, log=None):
    with subprocess.Popen(argv, cwd=cwd, text=True, stdout=log or subprocess.PIPE,
                          stderr=log or subprocess.PIPE, start_new_session=True) as process:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate()
            raise
        if process.returncode:
            raise RuntimeError(f'{argv[0]} failed ({process.returncode}): {(stderr or "see stage log")[-1500:]}')
        return stdout or ''


def lark(*args, cwd=ROOT):
    raw = run([os.environ.get('LARK_CLI_BIN', 'lark-cli'), *args, '--as', 'bot', '--format', 'json'], cwd=cwd)
    value = json.loads(raw)
    if value.get('ok') is not True:
        raise RuntimeError(f'Lark did not return ok=true: {value}')
    return value


def sent_message_id(receipt):
    if receipt.get('ok') is not True:
        raise ValueError('Missing successful Lark receipt')
    data = receipt.get('data') or {}
    message_id = data.get('message_id') or (data.get('message') or {}).get('message_id')
    if not re.fullmatch(r'om_[A-Za-z0-9]{16,}', message_id or ''):
        raise ValueError('Missing real message_id in Lark receipt')
    return message_id


def document_has_marker(content, marker):
    if not content.strip():
        return False
    # Keyword fetch echoes the search term in an XML attribute, even when a
    # fuzzy match returned different text. Only actual document text is proof.
    text = ''.join(ElementTree.fromstring(content).itertext())
    return marker in text


def validate_body(body, raw):
    stats = raw['stats']
    expected = f"过去 24 小时团队 {stats['active_member_count']} 人活跃，共 {stats['commit_count']} 次提交、{stats['active_pr_count']} 个活跃 PR"
    if not body.startswith(expected):
        raise ValueError('Narrative total must match raw.stats exactly')
    for member in stats['by_member'].values():
        heading = f"**{member['display_name']}**（{member['commit_count']} 提交 / {member['active_pr_count']} PR）"
        if heading not in body:
            raise ValueError(f'Missing exact member statistics: {heading}')
    if '查看日报留档' in body:
        raise ValueError('Narrative must not include the archive link')


def deliver(folder, config, state):
    raw = json.loads((folder / 'raw.json').read_text())
    body = (folder / 'body.md').read_text().strip()
    validate_body(body, raw)
    archive = config['lark']['daily_log_doc']
    if archive['url'] in body:
        raise ValueError('Archive must not link to itself')
    marker = state['marker']
    fingerprint = hashlib.sha256(json.dumps([body, archive, config['delivery']['targets']], sort_keys=True).encode()).hexdigest()
    if state.get('delivery_fingerprint') not in (None, fingerprint):
        raise RuntimeError('Content or recipients changed after delivery preparation; inspect saved receipts')
    state['delivery_fingerprint'] = fingerprint
    save(folder / 'state.json', state)
    message = body + f"\n\n[查看日报留档]({archive['url']})\n"
    archive_body = f"## {state['date']}\n\n{body}\n\n统计标识：{marker}\n\n---\n"
    for name, text in [('message.md', message), ('archive.md', archive_body)]:
        path = folder / name
        path.write_text(text, encoding='utf-8')
        for flags in (['--fix'], []):
            run([sys.executable, str(SCRIPTS / 'validate_lark_markdown.py'), *flags, str(path)])
    receipts = state.setdefault('messages', {})
    for target in config['delivery']['targets']:
        if target['type'] != 'user':
            raise ValueError('Daily report delivery must be a private user target')
        target_id = target['id']
        if target_id not in receipts:
            key = hashlib.sha256(f'{marker}:{target_id}'.encode()).hexdigest()[:40]
            # Lark's send idempotency expires after 1 hour. Ambiguous old sends
            # require reconciliation, never a blind resend the next day.
            attempted = state.setdefault('send_attempted_at', {}).get(target_id)
            if attempted and time.time() - attempted > 3500:
                raise RuntimeError('Unconfirmed send is older than idempotency window; inspect chat before retry')
            state['send_attempted_at'][target_id] = attempted or time.time()
            save(folder / 'state.json', state)
            receipt = lark('im', '+messages-send', '--user-id', target_id,
                           '--markdown', (folder / 'message.md').read_text(), '--idempotency-key', key)
            receipts[target_id] = receipt
            save(folder / 'state.json', state)
            sent_message_id(receipt)
        message_id = sent_message_id(receipts[target_id])
        readback = lark('im', '+messages-mget', '--message-ids', message_id, '--no-reactions')
        messages = readback['data'].get('messages', [])
        if not any(item.get('message_id') == message_id for item in messages):
            raise RuntimeError('Message receipt could not be read back')
        save(folder / ('readback-' + target_id + '.json'), readback)
        print(f'[daily] message verified: {message_id}', flush=True)
    if not state.get('archived'):
        receipt_path = folder / 'archive-receipt.json'
        if receipt_path.exists() and json.loads(receipt_path.read_text())['data'].get('result') != 'success':
            raise RuntimeError('Previous archive insert was partial; repair the existing blocks before continuing')
        # Read before every insert: a previous request may have succeeded even
        # if its response was lost. The persisted marker identifies this run.
        snapshot = lark('docs', '+fetch', '--doc', archive['token'], '--scope', 'keyword', '--keyword', marker)
        content = snapshot['data']['document']['content']
        if not document_has_marker(content, marker):
            result = lark('docs', '+update', '--doc', archive['token'], '--command', 'block_insert_after',
                          '--block-id', '0', '--doc-format', 'markdown', '--content', '@./archive.md', cwd=folder)
            save(folder / 'archive-receipt.json', result)
            if result['data'].get('result') != 'success':
                raise RuntimeError('Archive insert not fully successful; inspect receipt before retry')
        verified = lark('docs', '+fetch', '--doc', archive['token'], '--scope', 'keyword', '--keyword', marker)
        if not document_has_marker(verified['data']['document']['content'], marker):
            raise RuntimeError('Archive marker missing on readback')
        state['archived'] = True
        save(folder / 'state.json', state)
    print('[daily] archive verified', flush=True)


def process(folder, config, state, deliver_only=False, collect_only=False, prepare_only=False):
    if not (folder / 'raw.json').exists() or not (folder / 'report.md').exists():
        if deliver_only:
            raise ValueError('Delivery requires collected raw.json')
        print('[daily] collecting ' + state['range'], flush=True)
        with (folder / 'collect.log').open('a') as log:
            run([sys.executable, str(SCRIPTS / 'collect_progress.py'), '--config', str(ROOT / 'skills/progress-report/config.yaml'),
                 '--range', state['range'], '--output', str(folder / 'report.md'), '--raw-output', str(folder / 'raw.json'),
                 '--cache-dir', str(folder / 'cache')], timeout=int(os.environ.get('DAILY_TEAM_REPORT_TIMEOUT', '1200')), log=log)
    if collect_only:
        return
    raw = json.loads((folder / 'raw.json').read_text())
    if (raw['since'], raw['until']) != (state['since'], state['until']):
        raise ValueError('Cached data window differs from this run')
    body_path = folder / 'body.md'
    if body_path.exists():
        try:
            validate_body(body_path.read_text().strip(), raw)
        except ValueError:
            if deliver_only or state.get('messages'):
                raise
            body_path.rename(folder / f'invalid-body-{time.time_ns()}.md')
    if not body_path.exists():
        if deliver_only:
            raise ValueError('Delivery requires body.md')
        prompt = f'''使用 progress-report 技能的叙事规则，把 {folder / 'raw.json'} 和 {folder / 'report.md'} 改写为负责人私聊的团队日报。
本次只写本地正文 {body_path}，不要调用飞书或 GitHub，不要发送消息、创建文档或再次采集。已采集统计窗口固定为 {state['range']}。
开头必须严格采用：过去 24 小时团队 N 人活跃，共 X 次提交、Y 个活跃 PR，主线是……。N/X/Y 逐字取 raw.stats。
每个成员都用标题 **姓名**（X 提交 / Y PR），数字取 raw.stats.by_member，包括零活动成员。每人 2–3 句介绍事项、进展及已有证据中的阻塞。
仅使用采集事实；区分已合并、进行中、上线和验收。PR 链接必须取自 raw，附简短事项说明。没有活动只能写窗口内无代码提交，不能推断没有工作。
注明北京时间统计窗口。控制篇幅，不要列完整 commit 清单。正文不包含留档链接。不要使用 ASCII 波浪号。
团队待关注如有则独立加粗标题，说明事项负责人。完成文件写入并检查后结束。'''
        print('[daily] generating narrative', flush=True)
        with (folder / 'codex.log').open('a') as log:
            run([os.environ.get('CODEX_BIN', 'codex'), 'exec', '--dangerously-bypass-approvals-and-sandbox',
                 '--ephemeral', '-C', str(ROOT), prompt], timeout=600, log=log)
    validate_body(body_path.read_text().strip(), raw)
    if not prepare_only:
        deliver(folder, config, state)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--range', help='Fixed local time range for backfill')
    parser.add_argument('--run-dir', type=Path)
    parser.add_argument('--deliver-only', action='store_true')
    parser.add_argument('--collect-only', action='store_true')
    parser.add_argument('--prepare-only', action='store_true', help='Generate and validate without any Lark writes')
    args = parser.parse_args()
    os.chdir(ROOT)
    os.environ['LARKSUITE_CLI_NO_UPDATE_NOTIFIER'] = '1'
    os.environ['LARKSUITE_CLI_NO_SKILLS_NOTIFIER'] = '1'
    base = ROOT / '.state/daily-report'
    base.mkdir(parents=True, exist_ok=True)
    with (base / 'run.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('Another daily report is already running')
        end = datetime.now().astimezone().replace(hour=21, minute=0, second=0, microsecond=0)
        if end > datetime.now().astimezone():
            end -= timedelta(days=1)
        interval = args.range or f'{end - timedelta(days=1):%Y-%m-%d %H:%M}至{end:%Y-%m-%d %H:%M}'
        since, until, _ = parse_range(interval, 1)
        folder = (args.run_dir or base / until.replace(':', '')).resolve()
        folder.mkdir(parents=True, exist_ok=True)
        config = load_config(ROOT / 'skills/progress-report/config.yaml')
        state_file = folder / 'state.json'
        if state_file.exists():
            state = json.loads(state_file.read_text())
            if args.range and (since, until) != (state['since'], state['until']):
                raise ValueError('Existing run has a different fixed window')
        else:
            date = datetime.fromisoformat(until.replace('Z', '+00:00')).astimezone().strftime('%Y-%m-%d')
            state = {'range': interval, 'since': since, 'until': until, 'date': date,
                     'marker': 'daily-' + hashlib.sha256(f'{since}/{until}'.encode()).hexdigest()[:16]}
            save(state_file, state)
        attempts = int(os.environ.get('DAILY_TEAM_REPORT_MAX_ATTEMPTS', '3'))
        error = None
        for attempt in range(attempts):
            try:
                process(folder, config, state, args.deliver_only, args.collect_only, args.prepare_only)
                print(f'[daily] complete; state: {state_file}', flush=True)
                return
            except Exception as exc:
                error = exc
                print(f'[daily] attempt {attempt + 1}/{attempts}: {exc}', file=sys.stderr, flush=True)
                if attempt + 1 < attempts:
                    time.sleep(min(60, int(os.environ.get('DAILY_TEAM_REPORT_RETRY_DELAY', '10'))))
        if not args.collect_only and not args.prepare_only:
            status = '消息已发，留档或回读未完成' if state.get('messages') else '日报未确认发送'
            for target in config['delivery']['targets']:
                if target['type'] == 'user':
                    try:
                        lark('im', '+messages-send', '--user-id', target['id'], '--markdown',
                             f'⚠️ 团队日报执行失败\n\n{status}。\n统计窗口：{state["range"]}\n原因：{error}\n执行记录：{folder}')
                    except Exception as alert_error:
                        print(f'[daily] failure notification failed: {alert_error}', file=sys.stderr)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
