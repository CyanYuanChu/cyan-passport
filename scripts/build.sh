#!/bin/zsh
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -c 'import runpy; runpy.run_path("scripts/build.py", run_name="__main__")'
