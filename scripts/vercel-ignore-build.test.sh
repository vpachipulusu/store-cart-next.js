#!/usr/bin/env bash
# Dry-run test for scripts/vercel-ignore-build.sh and the vercel.json files that call it.
# Run from the repo root:
#   bash scripts/vercel-ignore-build.test.sh
# Exit code of the script under test: 1 = build, 0 = skip.

set -u
here="$(cd "$(dirname "$0")" && pwd)"
script="$here/vercel-ignore-build.sh"
root="$(dirname "$here")"
failures=0

fail() { echo "FAIL: $1"; failures=$((failures + 1)); }

check() {
  local name="$1" expected="$2" ref="$3" message="$4" out code
  out="$(VERCEL_GIT_COMMIT_REF="$ref" VERCEL_GIT_COMMIT_MESSAGE="$message" bash "$script" 2>&1)"
  code=$?
  if [ "$code" != "$expected" ]; then
    fail "$name (expected exit $expected, got $code)"
  elif [ -n "${message//\[deploy preview\]/}" ] && [[ "${out//\[deploy preview\]/}" == *"${message//\[deploy preview\]/}"* ]]; then
    fail "$name (output echoes the commit message)"
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

# Hostile messages: quotes, $, backticks, command substitution must neither execute nor break matching.
sentinel="$(mktemp -u)"
check "quotes and \$ do not break skip" 0 "fix/x" "fix: \"q\" 'q' \$HOME \${PATH} \\n"
check "backticks and \$() are not executed" 0 "fix/x" "fix: \`touch $sentinel\` \$(touch $sentinel)"
[ -e "$sentinel" ] && { fail "hostile message executed a command"; rm -f "$sentinel"; } || echo "ok:   hostile message executed nothing"
check "marker on a later line builds" 1 "fix/x" $'fix: title\n\nbody line\n[deploy preview]'
check "hostile ref skips" 0 "x\"; exit 1; \"" "fix: y"
check "hostile ref with marker builds" 1 "\$(echo main)" "[deploy preview]"

# Unset variables entirely (not just empty) must also fail open.
env -u VERCEL_GIT_COMMIT_REF -u VERCEL_GIT_COMMIT_MESSAGE bash "$script" >/dev/null
[ $? -eq 1 ] && echo "ok:   unset env builds" || fail "unset env must build"

# Both vercel.json files must parse and point their ignoreCommand at an existing script.
for cfg in vercel.json fastapi_backend/vercel.json; do
  dir="$(dirname "$cfg")"
  cmd="$(node -e 'const c=JSON.parse(require("fs").readFileSync(process.argv[1],"utf8"));process.stdout.write(c.ignoreCommand||"")' "$root/$cfg" 2>/dev/null)"
  if [ -z "$cmd" ]; then fail "$cfg: invalid JSON or no ignoreCommand"; continue; fi
  target="${cmd#bash }"
  if [ "$target" = "$cmd" ] || [ ! -f "$root/$dir/$target" ]; then
    fail "$cfg: ignoreCommand '$cmd' does not resolve to an existing file from $dir"
  else
    echo "ok:   $cfg ignoreCommand resolves"
  fi
done

[ "$failures" -eq 0 ] && echo "all passed" || { echo "$failures failed"; exit 1; }
