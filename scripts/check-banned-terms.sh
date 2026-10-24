#!/usr/bin/env sh
# Rejects content matching any pattern in $BANNED_TERMS_FILE
# (default ~/.config/starboard/banned-terms.txt): one extended regex per line,
# case-insensitive; blank lines and lines starting with # are ignored.
#
# Usage:
#   check-banned-terms.sh                 scan staged file contents
#   check-banned-terms.sh <message-file>  scan staged contents and a commit message
#   check-banned-terms.sh --all           scan every tracked file (CI)
#   check-banned-terms.sh --range A..B    scan files and commit messages in a range (CI)
#
# Prints only the paths or commits that match, never the patterns.
set -eu

list="${BANNED_TERMS_FILE:-$HOME/.config/starboard/banned-terms.txt}"
[ -r "$list" ] || { echo "banned-terms list not found at $list; refusing to continue" >&2; exit 1; }

patterns=$(mktemp)
paths=$(mktemp)
trap 'rm -f "$patterns" "$paths"' EXIT
tr -d '\r' < "$list" | grep -Ev '^[[:space:]]*(#|$)' > "$patterns" || true
[ -s "$patterns" ] || { echo "banned-terms list at $list has no patterns; refusing to continue" >&2; exit 1; }

status=0

# $1: how to read a path ("staged" or a commit-ish); paths come from $paths.
scan_paths() {
  source=$1
  while IFS= read -r p; do
    [ -n "$p" ] || continue
    if [ "$source" = staged ]; then
      git cat-file -e ":$p" 2>/dev/null || continue
      git show ":$p" | grep -Eiqf "$patterns" || continue
    else
      git cat-file -e "$source:$p" 2>/dev/null || continue
      git show "$source:$p" | grep -Eiqf "$patterns" || continue
    fi
    echo "banned term in $p" >&2
    status=1
  done < "$paths"
}

case "${1:-}" in
  --all)
    git ls-files > "$paths"
    scan_paths HEAD
    ;;
  --range)
    range=${2:?--range needs A..B}
    git diff --name-only --diff-filter=d "$range" > "$paths"
    scan_paths "${range#*..}"
    for c in $(git rev-list "$range"); do
      if git log -1 --format=%B "$c" | grep -Eiqf "$patterns"; then
        echo "banned term in message of $c" >&2
        status=1
      fi
    done
    ;;
  *)
    git diff --cached --name-only --diff-filter=d > "$paths"
    scan_paths staged
    if [ -n "${1:-}" ] && [ -f "$1" ] && grep -Eiqf "$patterns" "$1"; then
      echo "banned term in commit message" >&2
      status=1
    fi
    ;;
esac

exit $status
