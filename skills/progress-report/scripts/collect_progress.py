#!/usr/bin/env python3
"""Collect GitHub progress data and render a Lark-ready Markdown report."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from ruamel.yaml import YAML
except ImportError:
    print("ruamel.yaml required: python3 -c 'import ruamel.yaml'", file=sys.stderr)
    raise


def load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    yaml = YAML(typ="safe")
    with path.open("r", encoding="utf-8") as f:
        return yaml.load(f) or {}


def deep_merge(base: dict, override: dict) -> dict:
    result = dict(base or {})
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        elif value in (None, "", [], {}):
            result.setdefault(key, value)
        else:
            result[key] = value
    return result


def load_config(path: Path) -> dict:
    cfg = load_yaml(path)
    ext = cfg.get("extends_config")
    if ext:
        ext_path = Path(ext)
        if not ext_path.is_absolute():
            ext_path = Path.cwd() / ext_path
        cfg = deep_merge(load_yaml(ext_path), cfg)
    return cfg


def parse_range(label: str, default_days: int) -> tuple[str, str, str]:
    today = datetime.now().date()
    text = (label or "").strip()
    if text in ("今天", "today"):
        since = until = today
    elif text in ("昨天", "yesterday"):
        since = until = today - timedelta(days=1)
    elif text in ("本周", "this week"):
        since = today - timedelta(days=today.weekday())
        until = today
    elif text in ("上周", "last week"):
        this_monday = today - timedelta(days=today.weekday())
        since = this_monday - timedelta(days=7)
        until = this_monday - timedelta(days=1)
    else:
        m = re.search(r"最近\s*(\d+)\s*天", text)
        days = int(m.group(1)) if m else int(default_days or 7)
        since = today - timedelta(days=days - 1)
        until = today
    return since.isoformat(), until.isoformat(), f"{since.isoformat()} ~ {until.isoformat()}"


def parse_pr_ref(value: str, repos: list[str]) -> tuple[str, int]:
    text = (value or "").strip()
    if not text:
        raise SystemExit("--pr requires a GitHub PR URL, owner/repo#number, or number.")
    url_match = re.search(r"github\.com/([^/\s]+/[^/\s]+)/pull/(\d+)", text)
    if url_match:
        return url_match.group(1), int(url_match.group(2))
    short_match = re.match(r"([^/\s]+/[^#\s]+)#(\d+)$", text)
    if short_match:
        return short_match.group(1), int(short_match.group(2))
    number_match = re.match(r"#?(\d+)$", text)
    if number_match:
        if len(repos) != 1:
            raise SystemExit("PR number alone is only allowed when exactly one github.repos entry is configured.")
        return repos[0], int(number_match.group(1))
    raise SystemExit(f"Cannot parse PR reference: {value}")


def gh_token(cfg: dict) -> str:
    token = os.environ.get("GITHUB_TOKEN") or cfg.get("github", {}).get("token") or ""
    if token:
        return token
    try:
        r = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=10)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    raise SystemExit("GitHub token not found. Set GITHUB_TOKEN, github.token, or run gh auth login.")


def github_get(token: str, endpoint: str, params: dict | None = None, paginate: bool = True):
    results = []
    page = 1
    while True:
        p = dict(params or {})
        if paginate:
            p.update({"per_page": 100, "page": page})
        url = "https://api.github.com" + endpoint
        if p:
            url += "?" + urllib.parse.urlencode(p)
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"token {token}")
        req.add_header("Accept", "application/vnd.github+json")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:300]
            raise RuntimeError(f"GitHub API {endpoint} failed: HTTP {e.code}: {body}") from e
        if not paginate or not isinstance(data, list):
            return data
        results.extend(data)
        if len(data) < 100:
            return results
        page += 1


def aliases_for(username: str, gh_map: dict) -> set[str]:
    raw = [username]
    mapped = gh_map.get(username, "")
    if isinstance(mapped, list):
        raw.extend(mapped)
    else:
        raw.extend(str(mapped or "").replace("|", ";").split(";"))
    return {x.strip().lower() for x in raw if x and x.strip()}


def member_index(cfg: dict):
    members = cfg.get("team", {}).get("members") or []
    gh_map = cfg.get("team", {}).get("gitlab_to_github") or {}
    by_alias = {}
    meta = {}
    for member in members:
        username = member.get("username", "")
        if not username:
            continue
        emails = {e.strip().lower() for e in (member.get("extra_emails") or []) if e}
        aliases = aliases_for(username, gh_map)
        for alias in aliases | emails:
            by_alias[alias] = username
        meta[username] = {
            "display_name": member.get("display_name") or username,
            "aliases": sorted(aliases),
            "emails": sorted(emails),
        }
    return by_alias, meta


def commit_member(commit: dict, by_alias: dict) -> str | None:
    c = commit.get("commit") or {}
    author = c.get("author") or {}
    login = ((commit.get("author") or {}).get("login") or "").lower()
    email = (author.get("email") or "").lower()
    return by_alias.get(login) or by_alias.get(email)


def normalize_commit(repo: str, branch: str, commit: dict, member: str) -> dict:
    c = commit.get("commit") or {}
    author = c.get("author") or {}
    message = c.get("message") or ""
    return {
        "sha": commit.get("sha", ""),
        "repo": repo,
        "branch": branch,
        "member": member,
        "title": message.splitlines()[0].strip(),
        "date": (author.get("date") or "")[:10],
        "url": commit.get("html_url", ""),
        "author": author.get("name", ""),
        "email": (author.get("email") or "").lower(),
    }


def normalize_pr(repo: str, pr: dict) -> dict:
    return {
        "repo": repo,
        "number": pr["number"],
        "title": pr.get("title", ""),
        "state": pr.get("state", ""),
        "url": pr.get("html_url", ""),
        "user": ((pr.get("user") or {}).get("login") or "").lower(),
        "base": (pr.get("base") or {}).get("ref", ""),
        "head": (pr.get("head") or {}).get("ref", ""),
        "updated_at": pr.get("updated_at", ""),
        "created_at": pr.get("created_at", ""),
        "merged_at": pr.get("merged_at"),
        "additions": pr.get("additions", 0),
        "deletions": pr.get("deletions", 0),
        "changed_files": pr.get("changed_files", 0),
    }


def should_include_pr(pr: dict, since: str, until: str, include_open_prs: bool) -> bool:
    updated = (pr.get("updated_at") or "")[:10]
    created = (pr.get("created_at") or "")[:10]
    if created > until:
        return False
    return updated >= since or (include_open_prs and pr.get("state") == "open")


def render_report(raw: dict, max_items: int) -> str:
    if raw.get("mode") == "pr":
        return render_pr_report(raw, max_items)

    date_range = raw["date_range"]
    commits = raw["commits"]
    prs = raw["prs"]
    by_member = defaultdict(list)
    by_repo = defaultdict(list)
    for c in commits:
        by_member[c["member"]].append(c)
        by_repo[c["repo"]].append(c)

    lines = [
        f"# 项目进度同步 ({date_range})",
        "",
        "## 总览",
        "",
        f"- 数据来源: {', '.join(raw['repos'])}",
        f"- 匹配提交: {len(commits)} 次",
        f"- 相关 PR: {len(prs)} 个",
        f"- 活跃成员: {len(by_member)} 人",
        "",
        "## 已完成",
        "",
    ]

    merged = [p for p in prs if p.get("merged_at")]
    if merged:
        for pr in merged[:max_items]:
            lines.append(f"- [{pr['repo']} #{pr['number']}]({pr['url']}) {pr['title']} — 已合并")
    else:
        lines.append("- 未发现该时间范围内已合并 PR。")

    lines.extend(["", "## 进行中", ""])
    open_prs = [p for p in prs if p.get("state") == "open"]
    if open_prs:
        for pr in open_prs[:max_items]:
            lines.append(f"- [{pr['repo']} #{pr['number']}]({pr['url']}) {pr['title']} — 进行中")
    else:
        lines.append("- 未发现打开中的相关 PR。")

    lines.extend(["", "## 代码改动明细", ""])
    if not commits:
        lines.append("- 该范围内未匹配到团队成员代码改动。请检查仓库配置、GitHub 用户映射或时间范围。")
    for member, items in sorted(by_member.items(), key=lambda x: len(x[1]), reverse=True):
        display = raw["members"].get(member, {}).get("display_name", member)
        lines.append(f"### {display} (@{member})")
        for c in sorted(items, key=lambda x: x["date"], reverse=True)[:max_items]:
            lines.append(f"- [{c['sha'][:8]}]({c['url']}) `{c['repo']}:{c['branch']}` {c['title']} — {c['date']}")
        if len(items) > max_items:
            lines.append(f"- ... 及 {len(items) - max_items} 条其他提交")
        lines.append("")

    lines.extend(["## 接下来", ""])
    if open_prs:
        for pr in open_prs[:max_items]:
            lines.append(f"- 推进 PR [{pr['repo']} #{pr['number']}]({pr['url']}) 的 review、验证或合并。")
    else:
        lines.append("- 根据上述改动确认下一步任务拆分；当前没有从打开 PR 中提取到明确待办。")

    lines.extend(["", "## 待确认", ""])
    lines.append("- 未合并分支上的提交不等于已发布；需要结合 PR 状态确认对外交付口径。")
    return "\n".join(lines).rstrip() + "\n"


def render_pr_report(raw: dict, max_items: int) -> str:
    pr = raw["target_pr"]
    commits = raw["commits"]
    files = raw.get("files", [])
    by_member = defaultdict(list)
    for c in commits:
        by_member[c["member"]].append(c)

    status = "已合并" if pr.get("merged_at") else ("进行中" if pr.get("state") == "open" else "已关闭")
    lines = [
        f"# PR 进度同步: {pr['repo']} #{pr['number']}",
        "",
        "## 总览",
        "",
        f"- PR: [{pr['title']}]({pr['url']})",
        f"- 状态: {status}",
        f"- 分支: `{pr.get('head', '')}` -> `{pr.get('base', '')}`",
        f"- 提交: {len(commits)} 次",
        f"- 文件: {pr.get('changed_files', len(files))} 个",
        f"- 代码变更: +{pr.get('additions', 0):,} / -{pr.get('deletions', 0):,}",
        f"- 参与成员: {len(by_member)} 人",
        "",
        "## 这个 PR 做了什么",
        "",
    ]

    if commits:
        for c in commits[:max_items]:
            lines.append(f"- [{c['sha'][:8]}]({c['url']}) {c['title']} — {c['date']}")
        if len(commits) > max_items:
            lines.append(f"- ... 及 {len(commits) - max_items} 条其他提交")
    else:
        lines.append("- 未匹配到团队成员提交；请检查 GitHub 用户映射或 PR 作者。")

    lines.extend(["", "## 涉及范围", ""])
    if files:
        for f in files[:max_items]:
            changes = f"+{f.get('additions', 0)}/-{f.get('deletions', 0)}"
            lines.append(f"- `{f.get('filename', '')}` ({changes})")
        if len(files) > max_items:
            lines.append(f"- ... 及 {len(files) - max_items} 个其他文件")
    else:
        lines.append("- 未获取到文件改动列表。")

    lines.extend(["", "## 成员贡献", ""])
    if by_member:
        for member, items in sorted(by_member.items(), key=lambda x: len(x[1]), reverse=True):
            display = raw["members"].get(member, {}).get("display_name", member)
            lines.append(f"- {display} (@{member}): {len(items)} commits")
    else:
        lines.append("- 未匹配到团队成员。")

    lines.extend(["", "## 接下来", ""])
    if pr.get("state") == "open":
        lines.append("- 完成 review、验证和必要修订后推进合并。")
        lines.append("- 合并前确认上述文件改动是否覆盖预期范围。")
    elif pr.get("merged_at"):
        lines.append("- 跟进合并后的验证、发布或文档同步。")
    else:
        lines.append("- PR 已关闭；确认是否已有替代 PR 或无需继续推进。")

    lines.extend(["", "## 待确认", ""])
    lines.append("- 本报告仅基于 PR commits 和 files；业务效果、上线状态和外部依赖需要人工确认。")
    return "\n".join(lines).rstrip() + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="skills/progress-report/config.yaml")
    parser.add_argument("--range", default="")
    parser.add_argument("--pr", default="", help="GitHub PR URL, owner/repo#number, or number.")
    parser.add_argument("--output", default="/tmp/progress_report.md")
    parser.add_argument("--raw-output", default="/tmp/progress_report_raw.json")
    args = parser.parse_args()

    cfg = load_config(Path(args.config))
    report_cfg = cfg.get("report", {})
    repos = [r for r in (cfg.get("github", {}).get("repos") or []) if r]
    if not repos:
        raise SystemExit("No github.repos configured.")
    since, until, date_range = parse_range(args.range, report_cfg.get("default_days", 7))

    token = gh_token(cfg)
    by_alias, members = member_index(cfg)
    include_all = bool(report_cfg.get("include_all_branches", True))
    include_open_prs = bool(report_cfg.get("include_open_prs", True))
    max_branches = int(report_cfg.get("max_branches_per_repo", 80))
    max_items = int(report_cfg.get("max_commits_per_section", 12))

    if args.pr:
        repo_full, pr_number = parse_pr_ref(args.pr, repos)
        owner, repo = repo_full.split("/", 1)
        pr = github_get(token, f"/repos/{owner}/{repo}/pulls/{pr_number}", paginate=False)
        pr_commits = github_get(token, f"/repos/{owner}/{repo}/pulls/{pr_number}/commits")
        files = github_get(token, f"/repos/{owner}/{repo}/pulls/{pr_number}/files")
        commits = []
        for commit in pr_commits:
            member = commit_member(commit, by_alias)
            if member:
                commits.append(normalize_commit(repo_full, (pr.get("head") or {}).get("ref", ""), commit, member))
        raw = {
            "mode": "pr",
            "repos": [repo_full],
            "members": members,
            "target_pr": normalize_pr(repo_full, pr),
            "commits": sorted(commits, key=lambda x: (x["date"], x["sha"]), reverse=True),
            "files": files,
        }
        Path(args.raw_output).write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
        Path(args.output).write_text(render_report(raw, max_items), encoding="utf-8")
        print(f"wrote {args.output} and {args.raw_output}: PR {repo_full}#{pr_number}, {len(commits)} matched commits")
        return

    commits_by_sha = {}
    prs_by_key = {}
    for repo_full in repos:
        owner, repo = repo_full.split("/", 1)
        branches = [{"name": ""}]
        if include_all:
            branches = github_get(token, f"/repos/{owner}/{repo}/branches")[:max_branches]
        for branch in branches:
            branch_name = branch.get("name") or ""
            params = {"since": f"{since}T00:00:00Z", "until": f"{until}T23:59:59Z"}
            if branch_name:
                params["sha"] = branch_name
            for commit in github_get(token, f"/repos/{owner}/{repo}/commits", params):
                member = commit_member(commit, by_alias)
                if member:
                    item = normalize_commit(repo_full, branch_name or "default", commit, member)
                    commits_by_sha[item["sha"]] = item

        pr_queries = [{
            "state": "all",
            "sort": "updated",
            "direction": "desc",
        }]
        if include_open_prs:
            pr_queries.append({
                "state": "open",
                "sort": "updated",
                "direction": "desc",
            })
        for query in pr_queries:
            for pr in github_get(token, f"/repos/{owner}/{repo}/pulls", query):
                updated = (pr.get("updated_at") or "")[:10]
                if query["state"] == "all" and updated < since:
                    break
                if not should_include_pr(pr, since, until, include_open_prs):
                    continue
                key = (repo_full, pr["number"])
                if key in prs_by_key:
                    continue
                author = ((pr.get("user") or {}).get("login") or "").lower()
                if author not in by_alias:
                    continue
                prs_by_key[key] = normalize_pr(repo_full, pr)

    raw = {
        "mode": "range",
        "since": since,
        "until": until,
        "date_range": date_range,
        "repos": repos,
        "members": members,
        "commits": sorted(commits_by_sha.values(), key=lambda x: (x["date"], x["repo"], x["sha"]), reverse=True),
        "prs": sorted(prs_by_key.values(), key=lambda x: x.get("updated_at", ""), reverse=True),
    }

    Path(args.raw_output).write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    Path(args.output).write_text(render_report(raw, max_items), encoding="utf-8")
    print(f"wrote {args.output} and {args.raw_output}: {len(raw['commits'])} commits, {len(raw['prs'])} PRs")


if __name__ == "__main__":
    main()
