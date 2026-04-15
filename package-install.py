#!/usr/bin/env python3
"""
Universal Agent Packager
Translates universal agent roles and skills into Claude, Gemini, and Codex CLI formats.

Usage:
    python package-install.py          # Install from repo root
"""
import json
import os
import shutil
from pathlib import Path

try:
    import yaml
except ImportError:
    # Minimal YAML parser for frontmatter (avoids requiring PyYAML)
    yaml = None

REPO_ROOT = Path(__file__).parent
SOURCE_SKILLS = REPO_ROOT / "skills"
SOURCE_ROLES = REPO_ROOT / "agent-roles"

TARGET_DIRS = {
    "claude": {
        "skills": REPO_ROOT / ".claude" / "skills",
        "agents": REPO_ROOT / ".claude" / "agents",
    },
    "gemini": {
        "skills": REPO_ROOT / ".gemini" / "skills",
        "agents": REPO_ROOT / ".gemini" / "agents",
    },
    "codex": {
        "skills": REPO_ROOT / ".agents" / "skills",
        "agents": REPO_ROOT / ".codex" / "agents",
    },
}


def ensure_dirs():
    for cli, paths in TARGET_DIRS.items():
        paths["skills"].mkdir(parents=True, exist_ok=True)
        paths["agents"].mkdir(parents=True, exist_ok=True)


def sync_skills():
    if not SOURCE_SKILLS.exists():
        print("  No skills/ directory found — skipping skill sync.")
        return
    count = 0
    for skill_dir in sorted(SOURCE_SKILLS.iterdir()):
        if not skill_dir.is_dir():
            continue
        if not (skill_dir / "SKILL.md").exists():
            continue
        for cli, paths in TARGET_DIRS.items():
            target_path = paths["skills"] / skill_dir.name
            if target_path.exists():
                if target_path.is_symlink():
                    target_path.unlink()
                else:
                    shutil.rmtree(target_path)
            os.symlink(skill_dir.resolve(), target_path)
        count += 1
        print(f"  Linked skill '{skill_dir.name}' -> all CLIs")
    print(f"  {count} skill(s) synced.")


def _parse_frontmatter(text: str) -> tuple:
    """Split ---frontmatter--- from body. Returns (dict, body_str)."""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    fm_text = parts[1].strip()
    body = parts[2].strip()
    if yaml:
        meta = yaml.safe_load(fm_text) or {}
    else:
        # Minimal key: value parser for simple frontmatter
        meta = {}
        for line in fm_text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" in line:
                key, _, val = line.partition(":")
                val = val.strip().strip('"').strip("'")
                if val.lower() in ("true", "false"):
                    val = val.lower() == "true"
                elif val.isdigit():
                    val = int(val)
                meta[key.strip()] = val
    return meta, body


def build_agents():
    if not SOURCE_ROLES.exists():
        print("  No agent-roles/ directory found — skipping agent build.")
        return
    count = 0
    for role_file in sorted(SOURCE_ROLES.glob("*.md")):
        meta, body = _parse_frontmatter(role_file.read_text())
        role_name = meta.get("role") or role_file.stem
        desc = meta.get("description", "")

        # -- Claude Code format: copy the file as-is (it already uses Claude frontmatter) --
        claude_path = TARGET_DIRS["claude"]["agents"] / f"{role_name}.md"
        claude_path.write_text(role_file.read_text())

        # -- Gemini CLI format: markdown with name/description frontmatter --
        gemini_meta = {"name": role_name, "description": desc}
        if "model" in meta:
            gemini_meta["model"] = meta["model"]
        if "maxTurns" in meta:
            gemini_meta["max_turns"] = meta["maxTurns"]
        gemini_fm = "\n".join(f"{k}: {v}" for k, v in gemini_meta.items())
        gemini_text = f"---\n{gemini_fm}\n---\n\n{body}"
        (TARGET_DIRS["gemini"]["agents"] / f"{role_name}.md").write_text(gemini_text)

        # -- Codex CLI format: TOML with developer_instructions --
        codex_lines = [
            f'name = {json.dumps(role_name)}',
            f'description = {json.dumps(desc)}',
            f'developer_instructions = {json.dumps(body)}',
        ]
        if "model" in meta:
            codex_lines.append(f'model = {json.dumps(meta["model"])}')
        (TARGET_DIRS["codex"]["agents"] / f"{role_name}.toml").write_text(
            "\n".join(codex_lines) + "\n"
        )

        count += 1
        print(f"  Built agent '{role_name}' -> Claude, Gemini, Codex")
    print(f"  {count} agent(s) built.")


def main():
    print("=== Universal Agent Packager ===")
    print(f"Repo root: {REPO_ROOT}")
    print()
    print("1. Creating target directories...")
    ensure_dirs()
    print("2. Syncing skills...")
    sync_skills()
    print("3. Building agent roles...")
    build_agents()
    print()
    print("Done! Agents and skills are installed for Claude, Gemini, and Codex.")


if __name__ == "__main__":
    main()
