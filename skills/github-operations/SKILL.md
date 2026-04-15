---
name: github-operations
description: >
  Patterns for interacting with GitHub Enterprise via CLI tools and MCP.
  Use when performing git operations, PR workflows, or repository management.
metadata:
  domain: github
---

# GitHub Operations

## Tool Discovery
- Use `gh` CLI for all GitHub operations (PRs, issues, releases, checks).
- Use `git` for local repository operations.
- If given a GitHub URL, use `gh` to fetch the information.

## PR Workflow
1. Create a feature branch from main.
2. Make focused commits with clear messages.
3. Push with `-u` flag to set upstream tracking.
4. Create PR with `gh pr create` — include summary and test plan.

## Commit Standards
- Prefix: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`
- Keep subject line under 70 characters.
- Body explains "why" not "what".

## Branch Naming
- `feat/short-description`
- `fix/issue-number-description`
- `refactor/component-name`
