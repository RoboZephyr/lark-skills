from __future__ import annotations

import importlib.util
import unittest
import http.client
from unittest.mock import patch, MagicMock
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = (
    REPO_ROOT / "skills" / "progress-report" / "scripts" / "collect_progress.py"
)
SPEC = importlib.util.spec_from_file_location("collect_progress", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


SINCE = "2026-08-20T13:10:15Z"
UNTIL = "2026-08-21T13:10:15Z"


def github_commit(sha: str, timestamp: str, login: str = "a404") -> dict:
    return {
        "sha": sha,
        "html_url": f"https://example.test/commit/{sha}",
        "author": {"login": login},
        "commit": {
            "author": {
                "name": login,
                "email": f"{login}@example.test",
                "date": timestamp,
            },
            "committer": {"date": timestamp},
            "message": f"commit {sha}",
        },
    }


def pull_request(**overrides) -> dict:
    value = {
        "repo": "momentstream/studio",
        "number": 1,
        "title": "test",
        "state": "closed",
        "url": "https://example.test/pull/1",
        "user": "a404",
        "base": "main",
        "head": "feature",
        "updated_at": "2026-08-21T10:56:28Z",
        "created_at": "2026-08-19T10:00:00Z",
        "closed_at": "2026-08-19T11:00:00Z",
        "merged_at": "2026-08-19T11:00:00Z",
        "merge_commit_sha": "old-merge",
        "additions": 0,
        "deletions": 0,
        "changed_files": 0,
    }
    value.update(overrides)
    return value


class PullRequestActivityTest(unittest.TestCase):
    def test_retries_incomplete_response(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'[]'
        with patch.object(MODULE.urllib.request, 'urlopen', side_effect=[http.client.IncompleteRead(b'x', 1), response]) as request, patch.object(MODULE.time, 'sleep'):
            self.assertEqual(MODULE.github_get('test', '/test'), [])
            self.assertEqual(request.call_count, 2)

    def test_pr_pagination_stops_at_window_boundary(self):
        page = [{'number': n, 'updated_at': SINCE if n < 3 else '2026-01-01T00:00:00Z'} for n in range(30)]
        with patch.object(MODULE, 'github_get', return_value=page) as request:
            prs = MODULE.recent_pull_requests('test', 'owner/repo', SINCE)
        self.assertEqual([p['number'] for p in prs], [0, 1, 2])
        self.assertEqual(request.call_count, 1)

    def test_graphql_reads_all_branch_and_commit_pages(self):
        def node(sha):
            return {'oid': sha, 'url': 'https://example.test/' + sha, 'message': sha, 'committedDate': UNTIL, 'author': {'email': 'a404@example.test', 'name': 'Dev', 'user': {'login': 'a404'}}}
        def connection(nodes, more=False, cursor=None):
            return {'nodes': nodes, 'pageInfo': {'hasNextPage': more, 'endCursor': cursor}}
        def ref(name, history):
            return {'name': name, 'target': {'oid': name + '-tip', 'history': history}}
        pages = [
            {'repository': {'refs': connection([ref('feature', connection([node('one')], True, 'commits-next'))], True, 'branches-next')}},
            {'repository': {'object': {'history': connection([node('two')])}}},
            {'repository': {'refs': connection([ref('main', connection([node('one')]))])}},
        ]
        with patch.object(MODULE, 'github_graphql', side_effect=pages) as request:
            commits = MODULE.collect_branch_commits('test', 'owner/repo', SINCE, UNTIL, {'a404': 'a404'}, True)
        self.assertEqual(set(commits), {'one', 'two'})
        self.assertEqual(request.call_count, 3)
        self.assertEqual(request.call_args_list[1].args[2]['oid'], 'feature-tip')
        self.assertEqual(request.call_args_list[2].args[2]['cursor'], 'branches-next')

    def test_graphql_errors_are_not_treated_as_empty_activity(self):
        with patch.object(MODULE, 'github_request', return_value={'data': {'repository': None}, 'errors': [{'message': 'unavailable'}]}):
            with self.assertRaises(RuntimeError):
                MODULE.github_graphql('test', 'query { viewer { login } }', {})

    def test_ignores_historical_pr_updated_only_by_head_ref_deleted(self) -> None:
        activity = MODULE.classify_pr_activity(
            pull_request(),
            commits=[github_commit("old", "2026-08-19T10:30:00Z")],
            timeline=[
                {
                    "event": "head_ref_deleted",
                    "created_at": "2026-08-21T10:56:28Z",
                }
            ],
            since=SINCE,
            until=UNTIL,
        )

        self.assertFalse(activity["active"])
        self.assertEqual(activity["reasons"], [])
        self.assertEqual(activity["ignored_events"][0]["kind"], "head_ref_deleted")

    def test_recovers_original_commits_and_excludes_squash_commit(self) -> None:
        pr = pull_request(
            number=154,
            created_at="2026-08-21T10:50:21Z",
            closed_at="2026-08-21T12:24:33Z",
            merged_at="2026-08-21T12:24:33Z",
            merge_commit_sha="squash",
        )
        originals = [
            github_commit("original-1", "2026-08-21T11:00:00Z"),
            github_commit("original-2", "2026-08-21T12:00:00Z"),
        ]
        activity = MODULE.classify_pr_activity(
            pr,
            commits=originals,
            timeline=[],
            since=SINCE,
            until=UNTIL,
        )
        branch_commits = {
            "squash": MODULE.normalize_commit(
                pr["repo"], "main", github_commit("squash", "2026-08-21T12:24:33Z"), "a404"
            ),
            "direct": MODULE.normalize_commit(
                pr["repo"], "main", github_commit("direct", "2026-08-21T12:30:00Z"), "a404"
            ),
        }

        commits = MODULE.build_activity_commit_index(
            branch_commits=branch_commits,
            evidence=[activity],
            by_alias={"a404": "a404", "a404@example.test": "a404"},
            since=SINCE,
            until=UNTIL,
        )

        self.assertEqual(set(commits), {"original-1", "original-2", "direct"})


if __name__ == "__main__":
    unittest.main()
