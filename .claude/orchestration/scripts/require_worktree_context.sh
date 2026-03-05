#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 <expected_worktree_abs_path> <expected_branch_prefix>" >&2
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ $# -ne 2 ]]; then
  usage
  exit 2
fi

expected_worktree="${1%/}"
expected_branch_prefix="$2"

if [[ ! -d "$expected_worktree" ]]; then
  echo "ERROR: expected worktree does not exist: $expected_worktree" >&2
  exit 2
fi

actual_pwd="$(pwd -P)"
if [[ "$actual_pwd" != "$expected_worktree"* ]]; then
  echo "ERROR: wrong working directory: $actual_pwd (expected under $expected_worktree)" >&2
  exit 1
fi

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "ERROR: not inside a git worktree: $actual_pwd" >&2
  exit 1
fi

actual_branch="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$actual_branch" != "$expected_branch_prefix"* ]]; then
  echo "ERROR: wrong branch: $actual_branch (expected prefix $expected_branch_prefix)" >&2
  exit 1
fi

echo "worktree context ok: cwd=$actual_pwd branch=$actual_branch"
