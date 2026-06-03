#!/usr/bin/env python3
"""init_index.py — One-time setup for the weekly report index doc.

Creates a Lark document that serves as the perpetual entry point for weekly
reports. Each weekly run appends a one-line summary just below the top divider.

Updates config.yaml in-place with:
  lark.index_doc.token
  lark.index_doc.url
  lark.index_doc.anchor_block_id  # the top divider's block id (insert anchor)
  lark.index_doc.title

Idempotent: refuses to overwrite an existing token unless --force is passed.
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


DEFAULT_TITLE = "团队工程周报"
# 注意:Lark v2 XML 不支持 <divider/>,被静默丢弃。
# 改用顶部 callout 作为 anchor,每次 block_insert_after callout
# = 新周条目永远紧贴简介下方。
TEMPLATE_XML = """<title>{title}</title>

<callout emoji="📌" background="blue">
<p><b>团队工程周报汇总入口</b></p>
<p>每周自动追加一条,新一周永远在最上面;历史按时间倒序。</p>
<p>触发:每周五 launchd 自动跑 /weekly-report 本周。</p>
</callout>
"""


def _run_lark(cmd, stdin_data=None, check=True):
    """Run a lark-cli command, returning (stdout, parsed_json_or_None)."""
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


def create_doc(xml_content, as_identity="bot"):
    """Create a doc via lark-cli docs +create; returns (doc_token, doc_url)."""
    cmd = [
        "lark-cli", "docs", "+create",
        "--api-version", "v2",
        "--as", as_identity,
        "--doc-format", "xml",
        "--content", "-",  # read XML from stdin
    ]
    _, data = _run_lark(cmd, stdin_data=xml_content)
    if not data or not data.get("ok"):
        raise SystemExit(f"create doc returned not ok: {data}")
    d = data.get("data", {})
    # v2 response: data.document.{document_id, url}
    # v1 / fallback: data.{doc_id, doc_url}
    doc = d.get("document") or {}
    token = doc.get("document_id") or d.get("doc_id") or d.get("document_id")
    url = doc.get("url") or d.get("doc_url") or d.get("url")
    if not token:
        raise SystemExit(f"could not extract document_id from response: {data}")
    return token, url


def fetch_with_ids(doc_token, as_identity="bot"):
    """Fetch the doc XML with block IDs (detail=with-ids).

    Lark v2 returns content under data.document.content.
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
    return doc.get("content") or body.get("content") or body.get("body") or ""


def find_anchor_block_id(xml):
    """Locate the top callout block's id — used as insertion anchor.

    Each new week's entry is inserted via block_insert_after on this anchor,
    so the newest week always sits directly below the intro callout.
    """
    m = re.search(r'<callout\b[^>]*\bid="([^"]+)"', xml)
    return m.group(1) if m else None


def transfer_owner(doc_token, new_owner_id, member_type="openid", as_identity="bot",
                   stay_put=False, remove_old_owner=False, old_owner_perm="full_access"):
    """Hand ownership of the doc to the configured user.

    transfer_owner is gated as high-risk-write — must pass --yes or lark-cli
    exits 10 with confirmation_required and the script silently no-ops.
    The user pre-authorizes by configuring doc_owner_open_ids in config.yaml.
    """
    params = json.dumps({
        "token": doc_token,
        "type": "docx",
        "stay_put": str(bool(stay_put)).lower(),
        "remove_old_owner": str(bool(remove_old_owner)).lower(),
        "old_owner_perm": old_owner_perm,
        "need_notification": "false",
    })
    payload = json.dumps({"member_type": member_type, "member_id": new_owner_id})
    cmd = [
        "lark-cli", "drive", "permission.members", "transfer_owner",
        "--params", params,
        "--data", payload,
        "--as", as_identity,
        "--yes",
    ]
    _, data = _run_lark(cmd, check=True)
    return data


def grant_full_access(doc_token, bot_open_id, as_identity="bot"):
    """Re-grant the bot full_access after ownership transfer so it can append weekly.

    permission.members.create is also gated as high-risk-write; same --yes
    pattern as transfer_owner. Pre-authorized by configuring bot_open_id.
    """
    params = json.dumps({
        "token": doc_token,
        "type": "docx",
        "need_notification": "false",
    })
    payload = json.dumps({
        "member_type": "openid",
        "member_id": bot_open_id,
        "perm": "full_access",
    })
    cmd = [
        "lark-cli", "drive", "permission.members", "create",
        "--params", params,
        "--data", payload,
        "--as", as_identity,
        "--yes",
    ]
    _, data = _run_lark(cmd, check=True)
    return data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="skills/weekly-report/config.yaml",
                        help="path to config.yaml (relative to cwd)")
    parser.add_argument("--title", default=DEFAULT_TITLE)
    parser.add_argument("--force", action="store_true",
                        help="overwrite existing lark.index_doc.token")
    parser.add_argument("--as", dest="as_identity", default="bot", choices=["bot", "user"])
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        raise SystemExit(f"config file not found: {config_path}")

    yaml = YAML()
    yaml.preserve_quotes = True
    with config_path.open("r", encoding="utf-8") as f:
        cfg = yaml.load(f)

    lark = cfg.setdefault("lark", {})
    idx = lark.setdefault("index_doc", {})

    existing_token = idx.get("token") or ""
    if existing_token and not args.force:
        print(f"index_doc.token already set: {existing_token}", file=sys.stderr)
        print("Pass --force to overwrite and create a new index doc.", file=sys.stderr)
        raise SystemExit(2)

    perms = lark.get("permissions", {})
    owner_ids = perms.get("doc_owner_open_ids", [])
    bot_id = perms.get("bot_open_id", "")
    member_type = perms.get("member_type", "openid")

    if not owner_ids:
        raise SystemExit("lark.permissions.doc_owner_open_ids is empty")
    if not bot_id:
        raise SystemExit("lark.permissions.bot_open_id is missing")

    xml = TEMPLATE_XML.format(title=args.title)

    print(f"➤ creating index doc (title={args.title!r}, as={args.as_identity})",
          file=sys.stderr)
    doc_token, doc_url = create_doc(xml, as_identity=args.as_identity)
    print(f"  ✓ created: token={doc_token} url={doc_url}", file=sys.stderr)

    print(f"➤ transferring owner → {owner_ids[0]}", file=sys.stderr)
    transfer_owner(
        doc_token,
        owner_ids[0],
        member_type=member_type,
        as_identity=args.as_identity,
        stay_put=perms.get("stay_put", False),
        remove_old_owner=perms.get("remove_old_owner", False),
        old_owner_perm=perms.get("old_owner_perm", "full_access"),
    )

    print(f"➤ re-granting bot full_access ({bot_id})", file=sys.stderr)
    grant_full_access(doc_token, bot_id, as_identity=args.as_identity)

    print(f"➤ fetching with-ids to find anchor (top callout) block_id", file=sys.stderr)
    xml_with_ids = fetch_with_ids(doc_token, as_identity=args.as_identity)
    anchor_id = find_anchor_block_id(xml_with_ids)
    if anchor_id:
        print(f"  ✓ anchor (callout) block_id: {anchor_id}", file=sys.stderr)
    else:
        print(f"  ⚠ could not find anchor block_id; append_index.py will refetch on use",
              file=sys.stderr)

    idx["token"] = doc_token
    idx["url"] = doc_url
    idx["anchor_block_id"] = anchor_id or ""
    idx["title"] = args.title

    with config_path.open("w", encoding="utf-8") as f:
        yaml.dump(cfg, f)

    print(f"\n✅ index doc initialized; config updated: {config_path}", file=sys.stderr)
    print(f"   token: {doc_token}", file=sys.stderr)
    print(f"   url:   {doc_url}", file=sys.stderr)
    print(f"   anchor_block_id: {anchor_id or '(empty — will refetch)'}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
