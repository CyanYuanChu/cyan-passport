#!/bin/zsh
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -c 'import json,subprocess; m=json.load(open("module.json")); subprocess.run(["build/"+m["appName"]+"/Contents/MacOS/"+m["name"],"--self-test"],check=True); subprocess.run(["codesign","--verify","--deep","--strict","build/"+m["moduleName"]],check=True); subprocess.run(["codesign","--verify","--deep","--strict","build/"+m["appName"]],check=True)'
