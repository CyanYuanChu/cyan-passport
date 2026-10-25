#!/bin/zsh
set -euo pipefail
cd "$(dirname "$0")/.."
"build/Cyan Passport.app/Contents/MacOS/Cyan Passport" --self-test
codesign --verify --deep --strict "build/Cyan Passport.app"
