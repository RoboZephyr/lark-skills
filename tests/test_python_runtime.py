"""Exercise runtime selection with isolated files and no real agent/API calls."""
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PythonRuntimeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'repo with spaces'
        self.root.mkdir()
        for relative in (
            'scripts/python.sh', 'install.sh', 'launchd/run-daily-team-report.sh',
            'skills/progress-report/scripts/run_daily_report.py',
            'skills/progress-report/scripts/collect_progress.py',
        ):
            destination = self.root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, destination)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.make_script(self.bin / 'caffeinate', '#!/bin/sh\nexit 0\n')
        self.venv_python = self.root / '.venv/bin/python'
        self.venv_python.parent.mkdir(parents=True)
        # Delegate to the test interpreter, whose dependencies are already
        # installed, without downloading anything or copying a real venv.
        for name in ('python', 'python3'):
            self.make_script(self.venv_python.parent / name,
                             f'#!/bin/sh\nexec {shlex.quote(sys.executable)} "$@"\n')
        self.env = {'PATH': f'{self.bin}:/usr/bin:/bin', 'PYTHONNOUSERSITE': '1'}

    @staticmethod
    def make_script(path, content):
        path.write_text(content)
        path.chmod(0o755)

    def run_command(self, *args, entry='scripts/python.sh', env=None):
        return subprocess.run(
            ['/bin/bash', str(self.root / entry), *args], cwd=self.root,
            env={**self.env, **(env or {})}, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15,
        )

    def test_default_environment_works_without_activation(self):
        result = self.run_command('-c', 'import os, ruamel.yaml; print(os.environ["PYTHON_BIN"])')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), str(self.venv_python))

    def test_missing_environment_does_not_fall_back_to_system_python(self):
        self.venv_python.unlink()
        result = self.run_command('-c', 'print("must not execute")')
        self.assertEqual(result.returncode, 2)
        self.assertIn('Python environment missing', result.stderr)
        self.assertNotIn('must not execute', result.stdout)

    def test_explicit_interpreter_override(self):
        self.venv_python.unlink()
        result = self.run_command('--check', env={'PYTHON_BIN': sys.executable})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(sys.executable, result.stdout)

    def test_missing_dependency_stops_before_running_the_script(self):
        self.make_script(self.venv_python,
                         f'#!/bin/sh\nexec {shlex.quote(sys.executable)} -I -S "$@"\n')
        result = self.run_command('-c', 'print("must not execute")')
        self.assertEqual(result.returncode, 2)
        self.assertIn('requirements.txt', result.stderr)
        self.assertNotIn('must not execute', result.stdout)

    def test_agent_child_inherits_the_selected_environment(self):
        code = 'import os, json, shutil, ruamel.yaml; print(json.dumps([os.environ["PYTHON_BIN"], shutil.which("python3")]))'
        result = self.run_command('--exec', 'python3', '-c', code)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout),
                         [str(self.venv_python), str(self.venv_python.parent / 'python3')])

    def test_daily_help_needs_neither_github_credentials_nor_codex(self):
        marker = self.root / 'unexpected-auth'
        gh = self.bin / 'gh'
        self.make_script(gh, f'#!/bin/sh\ntouch {shlex.quote(str(marker))}\nexit 97\n')
        result = self.run_command('--help', entry='launchd/run-daily-team-report.sh',
                                  env={'GH_BIN': str(gh), 'CODEX_BIN': '/missing/codex'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--deliver-only', result.stdout)
        self.assertFalse(marker.exists())
        self.assertFalse((self.root / '.state').exists())

    def test_conflicting_delivery_modes_are_rejected_before_work(self):
        result = self.run_command('--collect-only', '--deliver-only',
                                  entry='launchd/run-daily-team-report.sh')
        self.assertEqual(result.returncode, 2)
        self.assertIn('not allowed with argument', result.stderr)
        self.assertFalse((self.root / '.state').exists())

    def test_installer_check_reports_missing_python_environment(self):
        self.venv_python.unlink()
        result = self.run_command('--check', entry='install.sh')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Python report dependencies unavailable', result.stdout)


if __name__ == '__main__':
    unittest.main()
