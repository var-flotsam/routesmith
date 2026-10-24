#!/usr/bin/env sh
# Points git at the repository's hooks in .githooks/.
set -eu
cd "$(git rev-parse --show-toplevel)"
git config core.hooksPath .githooks
chmod +x .githooks/* scripts/*.sh 2>/dev/null || true
echo "core.hooksPath = $(git config core.hooksPath)"
