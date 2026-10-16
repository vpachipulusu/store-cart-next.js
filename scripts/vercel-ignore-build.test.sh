#!/usr/bin/env bash
# Dry-run test for scripts/vercel-ignore-build.sh. Run from the repo root:
#   bash scripts/vercel-ignore-build.test.sh
# Exit code of the script under test: 1 = build, 0 = skip.

set -u
script="$(dirname "$0")/vercel-ignore-build.sh"
failures=0

check() {
  local name="$1" expected="$2" ref="$3" message="$4" out code
  out="$(VERCEL_GIT_COMMIT_REF="$ref" VERCEL_GIT_COMMIT_MESSAGE="$message" bash "$script")"
  code=$?
  if [ "$code" != "$expected" ]; then
    echo "FAIL: $name (expected exit $expected, got $code)"
    failures=$((failures + 1))
  elif [ -n "$message" ] && printf '%s' "$out" | grep -qF -- "$message"; then
    echo "FAIL: $name (output echoes the commit message)"
    failures=$((failures + 1))
  else
    echo "ok:   $name"
  fi
}

check "main builds" 1 "main" "feat: anything"
check "feature branch skips" 0 "feat/KAN-1-x" "feat(KAN-1): work"
check "feature branch with marker builds" 1 "feat/KAN-1-x" "feat(KAN-1): work [deploy preview]"
check "marker is case-insensitive" 1 "feat/KAN-1-x" "wip [Deploy Preview]"
check "marker mid-message builds" 1 "fix/x" "fix: a [deploy preview] b"
check "similar text skips" 0 "fix/x" "fix: deploy preview later"
check "empty message skips" 0 "fix/x" ""
check "branch named like main skips" 0 "main-fix" "fix: x"
check "no branch info builds (manual deploy)" 1 "" ""

# Unset variables entirely (not just empty) must also fail open.
env -u VERCEL_GIT_COMMIT_REF -u VERCEL_GIT_COMMIT_MESSAGE bash "$script" >/dev/null
if [ $? -ne 1 ]; then echo "FAIL: unset env must build"; failures=$((failures + 1)); else echo "ok:   unset env builds"; fi

[ "$failures" -eq 0 ] && echo "all passed" || { echo "$failures failed"; exit 1; }
