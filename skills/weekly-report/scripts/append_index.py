#!/usr/bin/env python3
"""append_index.py — Append one week's entry to the index doc.

Reads lark.index_doc.{token, anchor_block_id} from config.yaml and uses
`lark-cli docs +update --command block_insert_after` to insert a callout
block just below the top divider (newest week stays on top).

If anchor_block_id is missing/stale, refetches the doc, locates the divider,
and persists the fresh anchor back to config.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

try:
    from ruamel.yaml import YAML
except ImportError:
    print("ruamel.yaml required: pip install ruamel.yaml", file=sys.stderr)
    sys.exit(1)


ENTRY_XML = """<callout emoji="📅" background="grey">
<p><b>{week_label}</b> · {date_range}</p>
<p>{stats}</p>
<p>📊 <a href="{raw_url}">原始数据</a> · 📝 <a href="{analysis_url}">汇总分析</a></p>
</callout>"""


def _run_lark(cmd, stdin_data=None, check=True):
    r = subprocess.run(cmd, input=stdin_data, capture_output=True, text=True)
    if check and r.returncode != 0:
        print(f"\ncommand failed (exit {r.returncode}):", file=sys.stderr)
        print(f"  {' '.join(cmd)}", file=sys.stderr)
        print(f"stderr: {r.stderr.strip()}", file=sys.stderr)
        raise SystemExit(r.returncode)
    parsed = None
    if r.stdout.strip():
        try:
            parsed = json.loads(r.stdout)
        except json.JSONDecodeError:
            pass
    return r.stdout, parsed


def find_anchor_block_id(doc_token, as_identity="bot"):
    """Refetch the doc and locate the top callout block (anchor for insertion).

    Lark v2 doesn't preserve <divider/> tags, so we anchor on the intro callout
    (created by init_index.py). New entries are inserted via block_insert_after
    on this anchor — the newest week always sits directly below the callout.
    """
    cmd = [
        "lark-cli", "docs", "+fetch",
        "--api-version", "v2",
        "--as", as_identity,
        "--doc", doc_token,
        "--detail", "with-ids",
        "--doc-format", "xml",
    ]
    _, data = _run_lark(cmd)
    if not data or not data.get("ok"):
        raise SystemExit(f"fetch doc returned not ok: {data}")
    body = data.get("data", {})
    doc = body.get("document") or {}
    xml = doc.get("content") or body.get("content") or body.get("body") or ""
    m = re.search(r'<callout\b[^>]*\bid="([^"]+)"', xml)
    return m.group(1) if m else None


def append_entry(doc_token, anchor_block_id, xml_content, as_identity="bot"):
    cmd = [
        "lark-cli", "docs", "+update",
        "--api-version", "v2",
        "--as", as_identity,
        "--doc", doc_token,
        "--command", "block_insert_after",
        "--block-id", anchor_block_id,
        "--doc-format", "xml",
        "--content", "-",
    ]
    _, data = _run_lark(cmd, stdin_data=xml_content)
    return data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="skills/weekly-report/config.yaml")
    parser.add_argument("--week-label", required=True,
                        help="e.g. 'W23 2026' or '2026 第 23 周'")
    parser.add_argument("--date-range", required=True,
                        help="e.g. '2026-06-01 ~ 2026-06-07'")
    parser.add_argument("--raw-url", required=True)
    parser.add_argument("--analysis-url", required=True)
    parser.add_argument("--stats", default="",
                        help="one-line aggregate, e.g. '3 人 · 122 commits · +33k/-10k'")
    parser.add_argument("--as", dest="as_identity", default="bot", choices=["bot", "user"])
    parser.add_argument("--dry-run", action="store_true",
                        help="print XML that would be inserted; do not call lark-cli")
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        raise SystemExit(f"config file not found: {config_path}")

    yaml = YAML()
    yaml.preserve_quotes = True
    with config_path.open("r", encoding="utf-8") as f:
        cfg = yaml.load(f)

    idx = cfg.get("lark", {}).get("index_doc", {})
    token = idx.get("token", "")
    anchor = idx.get("anchor_block_id", "")

    if not token:
        raise SystemExit("lark.index_doc.token is empty — run init_index.py first")

    xml = ENTRY_XML.format(
        week_label=args.week_label,
        date_range=args.date_range,
        stats=args.stats or "(无聚合统计)",
        raw_url=args.raw_url,
        analysis_url=args.analysis_url,
    )

    if args.dry_run:
        print(xml)
        print(f"\n(dry-run) would block_insert_after token={token} block={anchor or '<unknown>'}",
              file=sys.stderr)
        return

    if not anchor:
        print("anchor_block_id is empty; refetching doc to find top callout...",
              file=sys.stderr)
        anchor = find_anchor_block_id(token, as_identity=args.as_identity)
        if not anchor:
            raise SystemExit("could not locate anchor (callout) block_id in doc")
        idx["anchor_block_id"] = anchor
        with config_path.open("w", encoding="utf-8") as f:
            yaml.dump(cfg, f)
        print(f"  ✓ refreshed anchor_block_id = {anchor}", file=sys.stderr)

    print(f"➤ appending entry to {token} after block {anchor}", file=sys.stderr)
    result = append_entry(token, anchor, xml, as_identity=args.as_identity)
    if result and not result.get("ok"):
        print(f"  ⚠ update returned: {result}", file=sys.stderr)
        raise SystemExit(1)
    print(f"✅ index doc appended: {idx.get('url')}", file=sys.stderr)


if __name__ == "__main__":
    main()
