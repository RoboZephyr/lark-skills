#!/usr/bin/env bash
# Use the same interpreter for interactive skills and unattended jobs.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
candidate="${PYTHON_BIN:-$REPO_DIR/.venv/bin/python}"
if ! PYTHON_BIN="$(command -v "$candidate")"; then
    echo "Python environment missing: $candidate" >&2
    echo "Create .venv and install requirements.txt as described in README.md." >&2
    exit 2
fi

if ! "$PYTHON_BIN" -c 'import sys; sys.version_info >= (3, 9) or sys.exit("Python 3.9+ required"); from ruamel.yaml import YAML'; then
    echo "Install requirements.txt into the selected interpreter: $PYTHON_BIN" >&2
    exit 2
fi

export PYTHON_BIN
export PATH="$(dirname "$PYTHON_BIN"):$PATH"
case "${1:-}" in
    --check)
        echo "Python environment ready: $PYTHON_BIN"
        exit 0
        ;;
    --exec)
        shift
        if [ "$#" -eq 0 ]; then
            echo "--exec requires a command" >&2
            exit 2
        fi
        exec "$@"
        ;;
esac
exec "$PYTHON_BIN" "$@"
