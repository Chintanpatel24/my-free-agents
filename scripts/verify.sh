#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
python3 -m compileall -q my_claudecode_python
PYTHONPATH="$ROOT" python3 -m unittest discover -s tests -p 'test_*.py'
PYTHONPATH="$ROOT" python3 tests/smoke_proxy.py
bash -n install.sh scripts/install.sh uninstall.sh scripts/uninstall.sh
printf 'All verification checks passed.\n'
