#!/usr/bin/env python3
"""
Team Commit Summary Script
Fetches commit activity from GitLab and/or GitHub for specified users over a
date range and generates a unified Markdown report grouped by person.

Supports:
- GitLab: push events + MR-based discovery
- GitHub: direct commit + PR queries per repo

Optimized for minimal LLM token usage:
- Single invocation produces complete report
- All data fetching, filtering, grouping done in Python
- Concurrent API calls for speed
- Compact stderr progress, structured stdout output
"""

import argparse
import http.client
import json
import socket
import subprocess
import sys
import time
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timedelta
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed


# Transient network errors that should trigger retry with backoff.
# IncompleteRead / RemoteDisconnected happen mid-body on flaky GitHub responses.
RETRYABLE_ERRORS = (
    http.client.IncompleteRead,
    http.client.RemoteDisconnected,
    urllib.error.URLError,
    socket.timeout,
    TimeoutError,
    ConnectionError,
)
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 1.5  # seconds, exponential


# ============================================================
# GitLab API
# ============================================================

def _http_get_json(req, label):
    """Execute an HTTP GET with retry on transient network errors.

    Returns (data, fatal_error_message_or_None). On fatal error, data is None.
    On retry exhaustion of transient errors, data is None and a message is set.
    """
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode('utf-8')), None
        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8', errors='replace')[:200]
            return None, f"HTTP {e.code}: {label} — {body}"
        except RETRYABLE_ERRORS as e:
            last_err = e
            if attempt < MAX_RETRIES:
                sleep_for = RETRY_BACKOFF_BASE ** attempt
                print(f"  ↻ retry {attempt}/{MAX_RETRIES - 1} after {sleep_for:.1f}s: {label} — {type(e).__name__}",
                      file=sys.stderr)
                time.sleep(sleep_for)
                continue
            return None, f"{label} — exhausted retries: {type(e).__name__}: {e}"
        except Exception as e:
            return None, f"{label} — {type(e).__name__}: {e}"
    return None, f"{label} — {type(last_err).__name__ if last_err else 'unknown'}"


def gitlab_api(base_url, token, endpoint, params=None):
    """Make a GitLab API GET request with pagination support."""
    results = []
    page = 1
    per_page = 100
    while page <= 50:
        url = f"{base_url}/api/v4{endpoint}"
        p = params.copy() if params else {}
        p['per_page'] = str(per_page)
        p['page'] = str(page)
        query = urllib.parse.urlencode(p)
        url = f"{url}?{query}"

        req = urllib.request.Request(url)
        req.add_header('PRIVATE-TOKEN', token)

        data, err = _http_get_json(req, endpoint)
        if err:
            print(f"  ✗ API {err}", file=sys.stderr)
            break
        if not data:
            break
        if isinstance(data, list):
            results.extend(data)
            if len(data) < per_page:
                break
        else:
            return data
        page += 1
    return results


# ============================================================
# GitHub API
# ============================================================

def github_api(token, endpoint, params=None):
    """Make a GitHub API GET request with pagination support."""
    results = []
    page = 1
    per_page = 100
    while page <= 50:
        url = f"https://api.github.com{endpoint}"
        p = params.copy() if params else {}
        p['per_page'] = str(per_page)
        p['page'] = str(page)
        query = urllib.parse.urlencode(p)
        url = f"{url}?{query}"

        req = urllib.request.Request(url)
        req.add_header('Authorization', f'token {token}')
        req.add_header('Accept', 'application/vnd.github.v3+json')

        data, err = _http_get_json(req, f"GitHub {endpoint}")
        if err:
            print(f"  ✗ {err}", file=sys.stderr)
            break
        if not data:
            break
        if isinstance(data, list):
            results.extend(data)
            if len(data) < per_page:
                break
        else:
            return data
        page += 1
    return results


def github_get_token():
    """Try to get GitHub token from gh CLI."""
    try:
        result = subprocess.run(
            ['gh', 'auth', 'token'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def github_fetch_repo_commits(token, owner, repo, since, until):
    """Fetch all commits in a GitHub repo within a date range."""
    commits = github_api(token, f'/repos/{owner}/{repo}/commits', {
        'since': f"{since}T00:00:00Z",
        'until': f"{until}T23:59:59Z",
    })
    return commits


def github_fetch_commit_detail(token, owner, repo, sha):
    """Fetch a single commit with stats."""
    result = github_api(token, f'/repos/{owner}/{repo}/commits/{sha}')
    return sha, result


def github_fetch_repo_prs(token, owner, repo, since, until):
    """Fetch PRs updated in the date range."""
    since_dt = datetime.strptime(since, '%Y-%m-%d')
    # Fetch recently updated PRs and filter by date
    prs = github_api(token, f'/repos/{owner}/{repo}/pulls', {
        'state': 'all',
        'sort': 'updated',
        'direction': 'desc',
    })
    # Filter to date range
    filtered = []
    for pr in prs:
        updated = pr.get('updated_at', '')[:10]
        created = pr.get('created_at', '')[:10]
        if updated >= since and created <= until:
            filtered.append(pr)
        elif updated < since:
            break  # sorted by updated desc, so we can stop
    return filtered


def github_fetch_pr_commits(token, owner, repo, pr_number):
    """Fetch commits belonging to a specific PR."""
    commits = github_api(token, f'/repos/{owner}/{repo}/pulls/{pr_number}/commits')
    return pr_number, commits


def normalize_github_commit(commit, owner, repo):
    """Normalize a GitHub commit to match our internal format."""
    c = commit.get('commit', {})
    author = c.get('author', {})
    stats = commit.get('stats', {})
    sha = commit.get('sha', '')
    message = c.get('message', '')
    title = message.split('\n')[0].strip()

    return {
        'id': sha,
        'title': title,
        'message': message,
        'author_email': author.get('email', '').strip().lower(),
        'author_name': author.get('name', ''),
        'committed_date': author.get('date', ''),
        'stats': {
            'additions': stats.get('additions', 0),
            'deletions': stats.get('deletions', 0),
        } if stats else {},
        '_source': 'github',
        '_url': f"https://github.com/{owner}/{repo}/commit/{sha}",
    }


def normalize_github_pr(pr, owner, repo):
    """Normalize a GitHub PR to match our MR format."""
    state = pr.get('state', '')
    if pr.get('merged_at'):
        state = 'merged'

    reviewers = pr.get('requested_reviewers', [])
    reviewer_list = [{'name': r.get('login', ''), 'username': r.get('login', '')}
                     for r in reviewers]

    return {
        'id': pr.get('id'),
        'iid': pr.get('number'),
        'title': pr.get('title', ''),
        'web_url': pr.get('html_url', ''),
        'state': state,
        'source_branch': pr.get('head', {}).get('ref', ''),
        'target_branch': pr.get('base', {}).get('ref', ''),
        'created_at': pr.get('created_at', ''),
        'merged_at': pr.get('merged_at'),
        'reviewers': reviewer_list,
        'project_id': f'gh:{owner}/{repo}',
        '_source': 'github',
    }


# ============================================================
# GitLab-specific functions
# ============================================================

def resolve_users_batch(base_url, token, usernames):
    """Resolve multiple usernames concurrently."""
    def _resolve(username):
        users = gitlab_api(base_url, token, '/users', {'search': username})
        if users:
            for u in users:
                if u.get('username') == username or u.get('email') == username:
                    return username, u
            return username, users[0]
        return username, None

    results = {}
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(_resolve, u): u for u in usernames}
        for f in as_completed(futures):
            uname, user = f.result()
            results[uname] = user
    return results


def collect_user_emails(user):
    """Collect all known email addresses for a user (lowercased)."""
    emails = set()
    for key in ('email', 'commit_email', 'public_email'):
        val = user.get(key, '')
        if val:
            emails.add(val.strip().lower())
    return emails


def get_user_push_events(base_url, token, user_id, since, until):
    """Get push events for a user within a date range."""
    since_dt = datetime.strptime(since, '%Y-%m-%d')
    until_dt = datetime.strptime(until, '%Y-%m-%d')
    after_date = (since_dt - timedelta(days=1)).strftime('%Y-%m-%d')
    before_date = (until_dt + timedelta(days=1)).strftime('%Y-%m-%d')

    return gitlab_api(base_url, token, f'/users/{user_id}/events', {
        'action': 'pushed',
        'after': after_date,
        'before': before_date,
        'sort': 'desc',
    })


def fetch_project_info(base_url, token, project_id):
    """Fetch project info."""
    return project_id, gitlab_api(base_url, token, f'/projects/{project_id}')


def fetch_project_branch_commits(base_url, token, project_id, ref_name, since, until):
    """Fetch commits for a specific project+branch, including line stats."""
    params = {
        'since': f"{since}T00:00:00Z",
        'until': f"{until}T23:59:59Z",
        'with_stats': 'true',
    }
    if ref_name:
        params['ref_name'] = ref_name
    commits = gitlab_api(base_url, token,
                         f'/projects/{project_id}/repository/commits', params)
    return project_id, ref_name, commits


def fetch_user_merge_requests(base_url, token, username, since, until):
    """Fetch merge requests authored by a user in the date range.

    Fetches both MRs created in the range AND MRs updated in the range
    (to catch MRs created earlier but merged/active during this period).
    """
    created_mrs = gitlab_api(base_url, token, '/merge_requests', {
        'author_username': username,
        'created_after': f"{since}T00:00:00Z",
        'created_before': f"{until}T23:59:59Z",
        'scope': 'all',
    })
    updated_mrs = gitlab_api(base_url, token, '/merge_requests', {
        'author_username': username,
        'updated_after': f"{since}T00:00:00Z",
        'updated_before': f"{until}T23:59:59Z",
        'scope': 'all',
    })
    # Deduplicate by MR id
    seen_ids = set()
    all_mrs = []
    for mr in created_mrs + updated_mrs:
        mid = mr.get('id')
        if mid not in seen_ids:
            seen_ids.add(mid)
            all_mrs.append(mr)
    return username, all_mrs


def fetch_mr_commits(base_url, token, project_id, mr_iid):
    """Fetch commits belonging to a specific merge request."""
    commits = gitlab_api(base_url, token,
                         f'/projects/{project_id}/merge_requests/{mr_iid}/commits')
    return project_id, mr_iid, commits


def fetch_commit_detail(base_url, token, project_id, commit_sha):
    """Fetch a single commit with stats."""
    result = gitlab_api(base_url, token,
                        f'/projects/{project_id}/repository/commits/{commit_sha}',
                        {'stats': 'true'})
    return project_id, commit_sha, result


# ============================================================
# Shared logic
# ============================================================

def summarize_commits(commits):
    """Categorize commits by conventional-commit prefix."""
    if not commits:
        return ""

    themes = defaultdict(int)
    for c in commits:
        msg = c.get('title', c.get('message', '')).split('\n')[0].strip().lower()
        for prefix in ['feat', 'fix', 'docs', 'test', 'refactor', 'chore', 'style', 'perf', 'ci']:
            if msg.startswith(prefix):
                themes[prefix] += 1
                break
        else:
            if msg.startswith('merge'):
                themes['merge'] += 1
            else:
                themes['other'] += 1

    labels = {
        'feat': '新功能开发', 'fix': 'Bug修复', 'docs': '文档更新',
        'test': '测试', 'refactor': '代码重构', 'chore': '工程维护',
        'style': '代码风格', 'perf': '性能优化', 'ci': 'CI/CD',
        'merge': '分支合并', 'other': '其他',
    }
    parts = [f"{labels.get(t, t)}({n})" for t, n in sorted(themes.items(), key=lambda x: -x[1])]
    return "、".join(parts)


def commit_fingerprint(c):
    """Generate a content-based fingerprint for dedup across branches."""
    title = c.get('title', c.get('message', '')).split('\n')[0].strip()
    email = c.get('author_email', '').strip().lower()
    return (title, email)


def dedup_commits(commits):
    """Remove duplicate commits by SHA and by content fingerprint."""
    seen_ids = set()
    seen_fps = {}
    result = []
    for c in commits:
        cid = c.get('id', '')
        if cid in seen_ids:
            continue
        seen_ids.add(cid)
        fp = commit_fingerprint(c)
        if fp in seen_fps:
            existing = seen_fps[fp]
            if not existing.get('stats') and c.get('stats'):
                result = [c if r is existing else r for r in result]
                seen_fps[fp] = c
            continue
        seen_fps[fp] = c
        result.append(c)
    return result


LARGE_COMMIT_THRESHOLD = 20000


def is_merge_commit(c):
    """Check if a commit is an auto-generated merge commit."""
    title = c.get('title', c.get('message', '')).split('\n')[0].strip().lower()
    return title.startswith('merge branch') or title.startswith('merge pull request')


def is_large_commit(c):
    """Check if a commit exceeds the large commit threshold."""
    stats = c.get('stats', {})
    total = stats.get('additions', 0) + stats.get('deletions', 0)
    return total > LARGE_COMMIT_THRESHOLD


def is_excluded_commit(c):
    """Check if a commit should be excluded from stats."""
    return is_merge_commit(c) or is_large_commit(c)


def compute_commit_stats(commits):
    """Sum up additions/deletions across commits, excluding merge and large commits."""
    adds, dels = 0, 0
    for c in commits:
        if is_excluded_commit(c):
            continue
        stats = c.get('stats', {})
        adds += stats.get('additions', 0)
        dels += stats.get('deletions', 0)
    return adds, dels


def build_commit_mr_map(user_mr_commits, user_mrs):
    """Build a mapping from (project_id, commit_sha) -> MR/PR info."""
    commit_mr = {}
    mr_lookup = {}
    for username, mrs in user_mrs.items():
        for mr in mrs:
            pid = mr.get('project_id')
            iid = mr.get('iid')
            if pid and iid:
                mr_lookup[(pid, iid)] = mr

    for username, mr_map in user_mr_commits.items():
        for (pid, iid), commits in mr_map.items():
            mr = mr_lookup.get((pid, iid))
            if not mr:
                continue
            is_gh = mr.get('_source') == 'github'
            for c in commits:
                sha = c.get('id', '')
                if sha:
                    commit_mr[(pid, sha)] = {
                        'iid': iid,
                        'title': mr.get('title', ''),
                        'web_url': mr.get('web_url', ''),
                        'prefix': '#' if is_gh else '!',
                    }
    return commit_mr


def get_commit_url(commit, gitlab_base_url, project_path):
    """Get the web URL for a commit, handling both GitLab and GitHub."""
    if commit.get('_url'):
        return commit['_url']
    return f"{gitlab_base_url}/{project_path}/-/commit/{commit.get('id', '')}"


def get_project_url(pid, project_path, gitlab_base_url):
    """Get the web URL for a project."""
    if isinstance(pid, str) and pid.startswith('gh:'):
        repo_path = pid[3:]
        return f"https://github.com/{repo_path}"
    return f"{gitlab_base_url}/{project_path}"


# ============================================================
# Report generation
# ============================================================

def generate_report(gitlab_base_url, users_data, since, until, commit_mr_map, no_header=False):
    """Generate the final Markdown report."""
    lines = [] if no_header else [f"## 📊 团队提交总结 ({since} ~ {until})", ""]

    # --- Team-wide stats ---
    team_total_commits = 0
    team_total_adds = 0
    team_total_dels = 0
    team_total_mrs = 0
    team_active_users = 0
    project_agg = defaultdict(lambda: {
        'path': '', 'pid': None, 'users': set(), 'commits': [], 'mrs': [],
        'adds': 0, 'dels': 0,
    })

    for user_info, commits_by_project, user_mrs in users_data:
        username = user_info.get('username', '')
        all_commits = [c for cs in commits_by_project.values() for c in cs]
        effective_commits = [c for c in all_commits if not is_excluded_commit(c)]
        adds, dels = compute_commit_stats(all_commits)
        team_total_commits += len(effective_commits)
        team_total_adds += adds
        team_total_dels += dels
        team_total_mrs += len(user_mrs)
        if effective_commits or user_mrs:
            team_active_users += 1

        for (pid, project_path), commits in commits_by_project.items():
            agg = project_agg[pid]
            agg['path'] = project_path
            agg['pid'] = pid
            agg['users'].add(username)
            agg['commits'].extend(commits)
            p_adds, p_dels = compute_commit_stats(commits)
            agg['adds'] += p_adds
            agg['dels'] += p_dels

        for mr in user_mrs:
            pid = mr.get('project_id')
            if pid:
                project_agg[pid]['mrs'].append(mr)
                project_agg[pid]['users'].add(username)

    # Team overview header
    if not no_header:
        lines.append("### 📋 团队总览")
        lines.append(
            f"**活跃成员**: {team_active_users} 人 | "
            f"**总提交**: {team_total_commits} 次 | "
            f"**总MR/PR**: {team_total_mrs} 个 | "
            f"**代码变更**: +{team_total_adds:,} / -{team_total_dels:,} 行"
        )
        lines.append("")

    # --- Project dimension summary ---
    if not no_header:
        lines.append("### 🏗️ 项目维度总览")
        lines.append("")
    sorted_projects = sorted(project_agg.items(),
                             key=lambda x: len([c for c in x[1]['commits'] if not is_excluded_commit(c)]),
                             reverse=True)
    if no_header:
        sorted_projects = []  # skip project overview entirely
    for pid, agg in sorted_projects:
        path = agg['path']
        eff_commits = [c for c in agg['commits'] if not is_excluded_commit(c)]
        deduped = dedup_commits(eff_commits)
        num_commits = len(deduped)
        if num_commits == 0 and not agg['mrs']:
            continue
        project_url = get_project_url(pid, path, gitlab_base_url)
        is_gh = isinstance(pid, str) and pid.startswith('gh:')
        platform_tag = " 🐙" if is_gh else ""
        users_str = ', '.join(f"@{u}" for u in sorted(agg['users']))
        stats_str = f"+{agg['adds']:,}/-{agg['dels']:,}" if (agg['adds'] or agg['dels']) else ""
        line = f"- **[{path}]({project_url})**{platform_tag} — {num_commits} commits"
        if stats_str:
            line += f" ({stats_str})"
        line += f" — {users_str}"
        seen_mr_ids = set()
        mr_links = []
        for mr in agg['mrs']:
            mid = mr.get('id')
            if mid in seen_mr_ids:
                continue
            seen_mr_ids.add(mid)
            state = mr.get('state', '')
            state_icon = {'merged': '✅', 'opened': '🟡', 'open': '🟡', 'closed': '🔴'}.get(state, '⚪')
            prefix = '#' if mr.get('_source') == 'github' else '!'
            mr_links.append(f"{state_icon}[{prefix}{mr.get('iid', '')}]({mr.get('web_url', '')})")
        if mr_links:
            mr_label = "PR" if is_gh else "MR"
            line += f" | {mr_label}: {' '.join(mr_links)}"
        lines.append(line)

    if not no_header:
        lines.extend(["", "---", ""])

    # --- Per-user detail ---
    for user_info, commits_by_project, user_mrs in users_data:
        name = user_info.get('name', user_info.get('username', 'Unknown'))
        username = user_info.get('username', '')
        all_commits = [c for cs in commits_by_project.values() for c in cs]
        effective_commits = [c for c in all_commits if not is_excluded_commit(c)]
        total_commits = len(effective_commits)
        num_projects = len(commits_by_project)
        total_adds, total_dels = compute_commit_stats(all_commits)

        lines.append(f"### 👤 {name} (@{username})")
        stat_parts = [f"**提交**: {total_commits} 次", f"**活跃项目**: {num_projects} 个"]
        if total_adds or total_dels:
            stat_parts.append(f"**代码变更**: +{total_adds:,} / -{total_dels:,} 行")
        lines.append(" | ".join(stat_parts))
        lines.append("")

        if total_commits == 0 and not user_mrs:
            lines.append("_该时间段内无提交记录_")
            lines.extend(["", "---", ""])
            continue

        summary = summarize_commits(effective_commits)
        if summary:
            lines.extend([f"**工作概要**: {summary}", ""])

        # --- MR/PR section ---
        if user_mrs:
            # Separate GitLab MRs and GitHub PRs
            gl_mrs = [m for m in user_mrs if m.get('_source') != 'github']
            gh_prs = [m for m in user_mrs if m.get('_source') == 'github']

            for label, items in [("Merge Requests", gl_mrs), ("Pull Requests", gh_prs)]:
                if not items:
                    continue
                merged = [m for m in items if m.get('state') == 'merged']
                opened = [m for m in items if m.get('state') in ('opened', 'open')]
                closed = [m for m in items if m.get('state') == 'closed']
                summary_parts = []
                if merged:
                    summary_parts.append(f"已合并 {len(merged)}")
                if opened:
                    summary_parts.append(f"进行中 {len(opened)}")
                if closed:
                    summary_parts.append(f"已关闭 {len(closed)}")
                icon = "🔀" if label == "Merge Requests" else "🐙"
                lines.append(f"{icon} **{label}** ({', '.join(summary_parts)})")
                prefix = '#' if label == "Pull Requests" else '!'
                for mr in items:
                    state = mr.get('state', '')
                    state_icon = {'merged': '✅', 'opened': '🟡', 'open': '🟡', 'closed': '🔴'}.get(state, '⚪')
                    title = mr.get('title', '')
                    url = mr.get('web_url', '')
                    src = mr.get('source_branch', '')
                    tgt = mr.get('target_branch', '')
                    reviewers = mr.get('reviewers', [])
                    reviewer_names = ', '.join(r.get('name', r.get('username', '')) for r in reviewers)
                    date_str = (mr.get('merged_at') or mr.get('created_at', ''))[:10]
                    line = f"- {state_icon} [{title}]({url}) (`{src}` → `{tgt}`)"
                    if reviewer_names:
                        line += f" — 审核: {reviewer_names}"
                    line += f" — {date_str}"
                    lines.append(line)
                lines.append("")

        # --- Commits by project (compact: group by MR, cap standalone) ---
        MAX_STANDALONE_COMMITS = 8  # max commits shown outside MR groups

        for (_pid, project_path), commits in sorted(commits_by_project.items(), key=lambda x: -len(x[1])):
            proj_adds, proj_dels = compute_commit_stats(commits)
            effective_count = len([c for c in commits if not is_excluded_commit(c)])
            stats_str = f", +{proj_adds:,}/-{proj_dels:,}" if (proj_adds or proj_dels) else ""
            project_url = get_project_url(_pid, project_path, gitlab_base_url)
            is_gh = isinstance(_pid, str) and _pid.startswith('gh:')
            platform_tag = " 🐙" if is_gh else ""
            lines.append(f"📦 **[{project_path}]({project_url})**{platform_tag} ({effective_count} commits{stats_str})")

            # Partition commits into MR-grouped and standalone
            mr_groups = defaultdict(list)  # mr_key -> [commits]
            standalone = []
            seen = set()
            sorted_commits = sorted(commits, key=lambda c: c.get('committed_date', c.get('created_at', '')), reverse=True)
            for commit in sorted_commits:
                cid = commit.get('id', '')
                if cid in seen:
                    continue
                seen.add(cid)
                mr_info = commit_mr_map.get((_pid, cid))
                if mr_info:
                    mr_key = (mr_info.get('prefix', '!'), mr_info.get('iid', ''), mr_info.get('web_url', ''), mr_info.get('title', ''))
                    mr_groups[mr_key].append(commit)
                else:
                    standalone.append(commit)

            # Render MR groups (one line per MR with commit count)
            for (prefix, iid, web_url, title), mr_commits in mr_groups.items():
                mr_adds = sum(c.get('stats', {}).get('additions', 0) for c in mr_commits if not is_excluded_commit(c))
                mr_dels = sum(c.get('stats', {}).get('deletions', 0) for c in mr_commits if not is_excluded_commit(c))
                mr_stats = f" `+{mr_adds:,}/-{mr_dels:,}`" if (mr_adds or mr_dels) else ""
                date_str = mr_commits[0].get('committed_date', mr_commits[0].get('created_at', ''))[:10]
                lines.append(
                    f"- [{prefix}{iid}]({web_url}) {title} ({len(mr_commits)} commits{mr_stats}) — {date_str}"
                )

            # Render standalone commits (capped)
            for commit in standalone[:MAX_STANDALONE_COMMITS]:
                cid = commit.get('id', '')
                msg = commit.get('title', commit.get('message', '')).split('\n')[0].strip()
                date_str = commit.get('committed_date', commit.get('created_at', ''))[:10]
                stats = commit.get('stats', {})
                cs = ""
                if stats.get('additions') or stats.get('deletions'):
                    cs = f" `+{stats.get('additions', 0)}/-{stats.get('deletions', 0)}`"
                if is_large_commit(commit):
                    large_tag = " ⚠️ *超大提交，已排除出统计*"
                elif is_merge_commit(commit):
                    large_tag = " *(merge)*"
                else:
                    large_tag = ""
                commit_url = get_commit_url(commit, gitlab_base_url, project_path)
                lines.append(
                    f"- [`{cid[:8]}`]({commit_url}) {msg}{cs}{large_tag} — {date_str}"
                )
            remaining = len(standalone) - MAX_STANDALONE_COMMITS
            if remaining > 0:
                lines.append(f"- _... 及 {remaining} 条其他提交_")

            lines.append("")

        lines.extend(["---", ""])

    return '\n'.join(lines)


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(description='Team Commit Summary')
    parser.add_argument('--gitlab-url', default='', help='GitLab base URL')
    parser.add_argument('--token', default='', help='GitLab personal access token')
    parser.add_argument('--users', required=True, help='Comma-separated usernames')
    parser.add_argument('--since', required=True, help='Start date YYYY-MM-DD')
    parser.add_argument('--until', required=True, help='End date YYYY-MM-DD')
    parser.add_argument('--github-repos', default='', help='Comma-separated GitHub repos (owner/repo)')
    parser.add_argument('--github-token', default='', help='GitHub token (default: from gh CLI)')
    parser.add_argument('--github-users', default='',
                        help='GitLab-to-GitHub user mapping: gl1=gh1,gl2=gh2')
    parser.add_argument('--output', default='', help='Write report to file instead of stdout')
    parser.add_argument('--no-header', action='store_true', help='Skip team overview header, only output per-user sections')
    parser.add_argument('--extra-emails', default='',
                        help='Extra email mappings: user1=email1;email2,user2=email3')
    parser.add_argument('--display-names', default='',
                        help='Display name overrides: user1=张三,user2=李四 (shown in report header)')
    args = parser.parse_args()

    base_url = args.gitlab_url.rstrip('/') if args.gitlab_url else ''
    gl_token = args.token
    user_list = [u.strip() for u in args.users.split(',') if u.strip()]
    since, until = args.since, args.until
    github_repos = [r.strip() for r in args.github_repos.split(',') if r.strip()]
    github_token = args.github_token

    # Parse GitHub user mapping
    gh_user_map = {}  # gitlab_username -> github_username
    if args.github_users:
        for pair in args.github_users.split(','):
            if '=' in pair:
                gl, gh = pair.strip().split('=', 1)
                gh_user_map[gl.strip()] = gh.strip()

    # Parse display name overrides: user1=Name1,user2=Name2
    display_names_map = {}
    if args.display_names:
        for pair in args.display_names.split(','):
            if '=' in pair:
                u, name = pair.strip().split('=', 1)
                display_names_map[u.strip()] = name.strip()

    # Parse extra email mappings: user1=email1;email2,user2=email3
    extra_emails_map = defaultdict(set)  # username -> {emails}
    if args.extra_emails:
        for mapping in args.extra_emails.split(','):
            if '=' in mapping:
                user, emails_str = mapping.strip().split('=', 1)
                for email in emails_str.split(';'):
                    email = email.strip().lower()
                    if email:
                        extra_emails_map[user.strip()].add(email)
        if extra_emails_map:
            print(f"📧 额外邮箱映射: {dict(extra_emails_map)}", file=sys.stderr)

    # Get GitHub token if needed
    if github_repos and not github_token:
        github_token = github_get_token()
        if not github_token:
            print("⚠️ 无法获取 GitHub token，跳过 GitHub 数据", file=sys.stderr)
            github_repos = []

    has_gitlab = bool(base_url and gl_token)

    # ============================================================
    # GitLab data collection
    # ============================================================

    resolved = {}
    user_events = {}
    all_project_ids = set()
    project_cache = {}
    branch_commits_cache = {}
    user_mrs = {}
    user_mr_commits = defaultdict(dict)
    user_emails_map = {}
    mr_commit_details = {}
    commit_mr_map = {}

    if has_gitlab:
        # --- Phase 1: Resolve all users concurrently ---
        print(f"🔍 解析 {len(user_list)} 个用户...", file=sys.stderr)
        user_map = resolve_users_batch(base_url, gl_token, user_list)

        resolved = {u: info for u, info in user_map.items() if info}
        missing = [u for u, info in user_map.items() if not info]
        if missing:
            print(f"⚠️ 未找到用户: {', '.join(missing)}", file=sys.stderr)

        # Pre-seed user_emails_map with profile emails + extra_emails
        for username, user in resolved.items():
            user_emails_map[username] = collect_user_emails(user)
            if username in extra_emails_map:
                user_emails_map[username].update(extra_emails_map[username])
                print(f"  {username}: 注入额外邮箱 {extra_emails_map[username]}", file=sys.stderr)

        # --- Phase 2: Get push events ---
        print("📡 获取推送事件...", file=sys.stderr)

        def _get_events(username, user):
            events = get_user_push_events(base_url, gl_token, user['id'], since, until)
            pid_branches = defaultdict(set)
            for e in events:
                pid = e.get('project_id')
                if not pid:
                    continue
                push = e.get('push_data', {})
                ref = push.get('ref', '')
                pid_branches[pid].add(ref if ref else None)
            return username, events, pid_branches

        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(_get_events, u, info) for u, info in resolved.items()]
            for f in as_completed(futures):
                uname, events, pid_branches = f.result()
                user_events[uname] = (events, pid_branches)
                all_project_ids.update(pid_branches.keys())
                branches_count = sum(len(bs) for bs in pid_branches.values())
                print(f"  {uname}: {len(events)} 事件, {len(pid_branches)} 项目, {branches_count} 分支", file=sys.stderr)

        # --- Phase 3: Fetch project info + commits ---
        all_pid_branches = defaultdict(set)
        for uname, (events, pid_branches) in user_events.items():
            for pid, branches in pid_branches.items():
                all_pid_branches[pid].update(branches)

        print(f"📦 获取 {len(all_project_ids)} 个项目的提交数据...", file=sys.stderr)

        with ThreadPoolExecutor(max_workers=8) as pool:
            info_futures = {pool.submit(fetch_project_info, base_url, gl_token, pid): pid
                            for pid in all_project_ids}
            commit_futures = {}
            for pid, branches in all_pid_branches.items():
                for branch in branches:
                    commit_futures[pool.submit(
                        fetch_project_branch_commits, base_url, gl_token, pid, branch, since, until
                    )] = (pid, branch)

            for f in as_completed(info_futures):
                pid, pinfo = f.result()
                if pinfo:
                    project_cache[pid] = pinfo

            for f in as_completed(commit_futures):
                pid, branch, commits = f.result()
                branch_commits_cache[(pid, branch)] = commits

        for pid, pinfo in project_cache.items():
            path = pinfo.get('path_with_namespace', f'project-{pid}')
            branches = all_pid_branches.get(pid, set())
            total = sum(len(branch_commits_cache.get((pid, b), [])) for b in branches)
            branch_names = ', '.join(b or 'default' for b in branches)
            print(f"  {path} [{branch_names}]: {total} 提交", file=sys.stderr)

        # --- Phase 4: Fetch MRs ---
        print("🔀 获取 Merge Requests...", file=sys.stderr)

        with ThreadPoolExecutor(max_workers=5) as pool:
            mr_futures = [pool.submit(fetch_user_merge_requests, base_url, gl_token, u, since, until)
                          for u in resolved]
            for f in as_completed(mr_futures):
                uname, mrs = f.result()
                user_mrs[uname] = mrs
                print(f"  {uname}: {len(mrs)} MRs", file=sys.stderr)

        # --- Phase 4.5: Fetch MR commits ---
        print("📧 获取 MR 提交记录以发现额外邮箱...", file=sys.stderr)

        for username, user in resolved.items():
            profile_emails = collect_user_emails(user)
            if username in user_emails_map:
                user_emails_map[username].update(profile_emails)
            else:
                user_emails_map[username] = profile_emails
            # Re-inject extra emails (in case this is the first init for some users)
            if username in extra_emails_map:
                user_emails_map[username].update(extra_emails_map[username])

        mr_commit_tasks = []
        for username, mrs in user_mrs.items():
            for mr in mrs:
                pid = mr.get('project_id')
                iid = mr.get('iid')
                if pid and iid:
                    mr_commit_tasks.append((username, pid, iid))

        if mr_commit_tasks:
            with ThreadPoolExecutor(max_workers=8) as pool:
                futures = {}
                for username, pid, iid in mr_commit_tasks:
                    fut = pool.submit(fetch_mr_commits, base_url, gl_token, pid, iid)
                    futures[fut] = (username, pid, iid)

                for f in as_completed(futures):
                    username, pid, iid = futures[f]
                    _, _, commits = f.result()
                    user_mr_commits[username][(pid, iid)] = commits
                    # Only learn emails from commits authored by this user
                    # (MRs may contain commits from other contributors)
                    known_emails = user_emails_map.get(username, set())
                    user_name_lower = username.lower()
                    for c in commits:
                        email = c.get('author_email', '').strip().lower()
                        if not email:
                            continue
                        author_name = c.get('author_name', '').strip().lower()
                        # Only add if author name contains the username or email prefix matches
                        email_prefix = email.split('@')[0].lower() if '@' in email else ''
                        if (user_name_lower in author_name
                                or user_name_lower == email_prefix
                                or email in known_emails):
                            user_emails_map[username].add(email)

        for username in resolved:
            profile_emails = collect_user_emails(resolved[username])
            extra = user_emails_map[username] - profile_emails
            if extra:
                print(f"  {username}: 发现额外邮箱 {extra}", file=sys.stderr)

        # --- Phase 4.6: Fetch stats for MR commits ---
        print("📊 补充 MR 提交统计...", file=sys.stderr)
        detail_tasks = []
        for username, mr_map in user_mr_commits.items():
            for (pid, iid), commits in mr_map.items():
                for c in commits:
                    sha = c.get('id', '')
                    if sha and (pid, sha) not in mr_commit_details:
                        found = False
                        for key, cached in branch_commits_cache.items():
                            if key[0] == pid:
                                for cc in cached:
                                    if cc.get('id') == sha:
                                        mr_commit_details[(pid, sha)] = cc
                                        found = True
                                        break
                            if found:
                                break
                        if not found:
                            detail_tasks.append((pid, sha))

        if detail_tasks:
            detail_tasks = list(set(detail_tasks))
            with ThreadPoolExecutor(max_workers=8) as pool:
                futures = [pool.submit(fetch_commit_detail, base_url, gl_token, pid, sha)
                           for pid, sha in detail_tasks]
                for f in as_completed(futures):
                    pid, sha, detail = f.result()
                    if detail and isinstance(detail, dict):
                        mr_commit_details[(pid, sha)] = detail
            print(f"  获取了 {len(detail_tasks)} 个提交的详细信息", file=sys.stderr)

        # --- Phase 4.7: Build commit → MR mapping ---
        commit_mr_map = build_commit_mr_map(user_mr_commits, user_mrs)
        print(f"🔗 建立了 {len(commit_mr_map)} 个 commit→MR 映射", file=sys.stderr)

    # Initialize emails for non-GitLab users
    for u in user_list:
        if u not in user_emails_map:
            user_emails_map[u] = set()

    # ============================================================
    # GitHub data collection
    # ============================================================

    # github_user_commits[username][(gh_pid, path)] = [commits]
    github_user_commits = defaultdict(lambda: defaultdict(list))
    # github_user_mrs[username] = [normalized PRs]
    github_user_mrs = defaultdict(list)
    # github_mr_commits for commit→PR mapping
    github_mr_commits = defaultdict(dict)

    if github_repos:
        print(f"\n🐙 GitHub: 获取 {len(github_repos)} 个仓库的数据...", file=sys.stderr)

        for repo_full in github_repos:
            parts = repo_full.split('/')
            if len(parts) != 2:
                print(f"  ✗ 无效的仓库格式: {repo_full}", file=sys.stderr)
                continue
            owner, repo = parts
            gh_pid = f'gh:{owner}/{repo}'

            # Fetch all commits in the repo for the date range
            print(f"  📦 {owner}/{repo}: 获取提交...", file=sys.stderr)
            raw_commits = github_fetch_repo_commits(github_token, owner, repo, since, until)
            print(f"    {len(raw_commits)} 原始提交", file=sys.stderr)

            # Fetch commit details (for stats) concurrently
            # GitHub list commits endpoint doesn't include stats
            detailed_commits = []
            with ThreadPoolExecutor(max_workers=8) as pool:
                futures = {
                    pool.submit(github_fetch_commit_detail, github_token, owner, repo, c.get('sha', '')): c
                    for c in raw_commits
                }
                for f in as_completed(futures):
                    sha, detail = f.result()
                    if detail and isinstance(detail, dict):
                        detailed_commits.append(normalize_github_commit(detail, owner, repo))
                    else:
                        # Fallback to basic commit
                        raw = futures[f]
                        detailed_commits.append(normalize_github_commit(raw, owner, repo))

            # Assign commits to users by email
            for nc in detailed_commits:
                email = nc.get('author_email', '')
                assigned = False
                for username in user_list:
                    gh_username = gh_user_map.get(username, username)
                    emails = user_emails_map.get(username, set())
                    if email in emails or email == gh_username:
                        github_user_commits[username][(gh_pid, f'{owner}/{repo}')].append(nc)
                        assigned = True
                        break
                if not assigned:
                    # Try matching by GitHub username from commit author
                    for raw_c in raw_commits:
                        if raw_c.get('sha') == nc.get('id'):
                            gh_author = (raw_c.get('author') or {}).get('login', '')
                            for username in user_list:
                                gh_username = gh_user_map.get(username, username)
                                if gh_author == gh_username:
                                    github_user_commits[username][(gh_pid, f'{owner}/{repo}')].append(nc)
                                    # Also learn this email
                                    if email:
                                        user_emails_map[username].add(email)
                                    assigned = True
                                    break
                            break

            # Fetch PRs
            print(f"  🔀 {owner}/{repo}: 获取 Pull Requests...", file=sys.stderr)
            raw_prs = github_fetch_repo_prs(github_token, owner, repo, since, until)

            for pr in raw_prs:
                pr_author = (pr.get('user') or {}).get('login', '')
                for username in user_list:
                    gh_username = gh_user_map.get(username, username)
                    if pr_author == gh_username:
                        norm_pr = normalize_github_pr(pr, owner, repo)
                        github_user_mrs[username].append(norm_pr)

                        # Fetch PR commits for mapping
                        pr_number = pr.get('number')
                        if pr_number:
                            _, pr_commits = github_fetch_pr_commits(
                                github_token, owner, repo, pr_number
                            )
                            normalized_pr_commits = [
                                normalize_github_commit(c, owner, repo)
                                for c in (pr_commits or [])
                                if isinstance(c, dict) and c.get('sha')
                            ]
                            github_mr_commits[username][(gh_pid, pr_number)] = normalized_pr_commits
                        break

            # Print per-user GitHub stats
            for username in user_list:
                commits = github_user_commits.get(username, {}).get((gh_pid, f'{owner}/{repo}'), [])
                prs = [p for p in github_user_mrs.get(username, []) if p.get('project_id') == gh_pid]
                if commits or prs:
                    print(f"    {username}: {len(commits)} commits, {len(prs)} PRs", file=sys.stderr)

    # Build GitHub commit→PR mapping
    if github_mr_commits:
        gh_commit_mr = build_commit_mr_map(github_mr_commits, {u: mrs for u, mrs in github_user_mrs.items()})
        commit_mr_map.update(gh_commit_mr)
        print(f"🔗 GitHub: 建立了 {len(gh_commit_mr)} 个 commit→PR 映射", file=sys.stderr)

    # ============================================================
    # Phase 5: Assemble per-user report data
    # ============================================================

    users_data = []
    for username in user_list:
        user = resolved.get(username)
        if user:
            # GitLab-resolved: still honor explicit display_name override
            if username in display_names_map:
                user = {**user, 'name': display_names_map[username]}
        else:
            # GitHub-only: keep config username as @handle, prefer display_name for header
            gh_username = gh_user_map.get(username, username)
            user = {
                'username': username,
                'name': display_names_map.get(username, gh_username),
            }

        user_emails = user_emails_map.get(username, set())
        commits_by_project = {}

        # GitLab commits
        if has_gitlab and username in resolved:
            _, pid_branches = user_events.get(username, ([], {}))

            for pid, branches in pid_branches.items():
                pinfo = project_cache.get(pid, {})
                path = pinfo.get('path_with_namespace', f'project-{pid}')

                seen_ids = set()
                user_commits = []
                for branch in branches:
                    for c in branch_commits_cache.get((pid, branch), []):
                        cid = c.get('id', '')
                        if cid in seen_ids:
                            continue
                        if c.get('author_email', '').strip().lower() in user_emails:
                            seen_ids.add(cid)
                            user_commits.append(c)

                if user_commits:
                    commits_by_project[(pid, path)] = user_commits

            for (pid, iid), mr_commits_list in user_mr_commits.get(username, {}).items():
                pinfo = project_cache.get(pid, {})
                if not pinfo:
                    _, pinfo = fetch_project_info(base_url, gl_token, pid)
                    if pinfo:
                        project_cache[pid] = pinfo
                path = pinfo.get('path_with_namespace', f'project-{pid}') if pinfo else f'project-{pid}'
                key = (pid, path)

                if key not in commits_by_project:
                    commits_by_project[key] = []

                existing_ids = {c.get('id') for c in commits_by_project[key]}
                for c in mr_commits_list:
                    cid = c.get('id', '')
                    if cid in existing_ids:
                        continue
                    if c.get('author_email', '').strip().lower() in user_emails:
                        detailed = mr_commit_details.get((pid, cid))
                        commits_by_project[key].append(detailed if detailed else c)
                        existing_ids.add(cid)

                if not commits_by_project[key]:
                    del commits_by_project[key]

        # GitHub commits
        for proj_key, commits in github_user_commits.get(username, {}).items():
            if proj_key in commits_by_project:
                existing_ids = {c.get('id') for c in commits_by_project[proj_key]}
                for c in commits:
                    if c.get('id') not in existing_ids:
                        commits_by_project[proj_key].append(c)
                        existing_ids.add(c.get('id'))
            else:
                commits_by_project[proj_key] = list(commits)

        # Dedup
        for proj_key in list(commits_by_project.keys()):
            before = len(commits_by_project[proj_key])
            commits_by_project[proj_key] = dedup_commits(commits_by_project[proj_key])
            after = len(commits_by_project[proj_key])
            if before != after:
                ppath = proj_key[1]
                print(f"  {username}/{ppath}: 去重 {before} → {after} 提交", file=sys.stderr)

        # Merge MRs/PRs
        combined_mrs = user_mrs.get(username, []) + github_user_mrs.get(username, [])

        users_data.append((user, commits_by_project, combined_mrs))

    # --- Phase 6: Generate and output report ---
    report = generate_report(base_url, users_data, since, until, commit_mr_map, no_header=args.no_header)

    total_projects = len(all_project_ids) + len(github_repos)
    sources = []
    if has_gitlab:
        sources.append(f"GitLab {len(all_project_ids)} 项目")
    if github_repos:
        sources.append(f"GitHub {len(github_repos)} 仓库")

    output_path = args.output.strip() if args.output else ''
    if output_path:
        import os
        os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(report)
        print(f"✅ 报告已保存到 {output_path} ({len(report)} 字符, {len(user_list)} 用户, {' + '.join(sources)})")
    else:
        print(report)

    print(f"\n✅ 完成: {len(user_list)} 用户, {' + '.join(sources)}", file=sys.stderr)


if __name__ == '__main__':
    main()
