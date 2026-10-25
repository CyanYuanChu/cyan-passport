#!/bin/zsh
set -euo pipefail
CYAN_RUNTIME="$HOME/Library/Application Support/CyanPassport/venv"
CYAN_PYTHON="${CYAN_PYTHON:-}"
if [[ -z "$CYAN_PYTHON" ]]; then
  for candidate in /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
    if [[ -x "$candidate" ]] && "$candidate" -c 'import sys; assert (3,10) <= sys.version_info < (3,15)' 2>/dev/null; then CYAN_PYTHON="$candidate"; break; fi
  done
fi
[[ -n "$CYAN_PYTHON" ]] || { print '需要 Python 3.10–3.14，请先安装 Python。'; exit 1; }
"$CYAN_PYTHON" -m venv "$CYAN_RUNTIME"
"$CYAN_RUNTIME/bin/python" -m pip install --disable-pip-version-check -r "$1"
