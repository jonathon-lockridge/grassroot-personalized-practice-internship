#!/usr/bin/env bash
# Fails if anything that looks like a real secret is in the repo.
# Used by the pre-commit hook (gets the staged file names as arguments) and by CI (no arguments: scans all tracked files).
set -uo pipefail

pattern='(sk-ant-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)'
self='scripts/check_secrets.sh'

if [ "$#" -gt 0 ]; then
  hits=$(grep -nIE "$pattern" -- "$@" 2>/dev/null | grep -v "^${self}:" || true)
else
  hits=$(git grep -nIE "$pattern" -- . ":!${self}" || true)
fi

if [ -n "$hits" ]; then
  echo "Possible secret found:"
  echo "$hits"
  echo
  echo "If it is real: rotate it now (create a new one, disable the old one). Deleting the line is not enough, git keeps history."
  exit 1
fi

echo "No secrets found."
