#!/usr/bin/env bash
# Vercel "Ignored Build Step" for the StoreCart project (KAN-212).
#
# Vercel semantics: exit 1 = run the build, exit 0 = skip it (a skipped build does
# not count against the Hobby plan's daily deployment quota).
#
# Build only when:
#   - the branch is main (production), or
#   - the head commit message contains "[deploy preview]" (opt-in preview), or
#   - there is no git branch information at all (CLI/manual deploys; fail open).
# Everything else is skipped.
#
# Reads only VERCEL_GIT_COMMIT_REF and VERCEL_GIT_COMMIT_MESSAGE. Prints a one-line
# decision and never prints the commit message or any other environment value.

set -u

ref="${VERCEL_GIT_COMMIT_REF:-}"
message="${VERCEL_GIT_COMMIT_MESSAGE:-}"
marker='[deploy preview]'

if [ -z "$ref" ]; then
  echo "vercel-ignore-build: no git branch info, building"
  exit 1
fi

if [ "$ref" = "main" ]; then
  echo "vercel-ignore-build: main branch, building"
  exit 1
fi

message_lower="$(printf '%s' "$message" | tr '[:upper:]' '[:lower:]')"
case "$message_lower" in
  *"$marker"*)
    echo "vercel-ignore-build: $marker requested, building preview"
    exit 1
    ;;
esac

echo "vercel-ignore-build: branch is not main and no $marker in the commit message, skipping"
exit 0
