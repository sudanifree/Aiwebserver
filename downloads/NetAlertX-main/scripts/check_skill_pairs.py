#!/usr/bin/env python3
"""
Flag PRs that touch some but not all files in a group of mirrored skill
files (`.gemini/skills/`, `.github/skills/`, `.claude/skills/`) without
touching the others. `.gemini/skills/skills-index/SKILL.md` documents these
groups and says to "keep body content identical" across them - but nothing
previously enforced that, and the plugin-development pair had already
drifted apart before this check existed.

This can't verify the files still say the *same thing* (that needs
judgment - some groups are intentionally different in depth, and the three
devcontainer-management targets each cover only part of the Gemini file),
only that a change to one file didn't forget the others exist. Exit
non-zero (but the CI step calling this is non-blocking) when a group looks
one-sided.

    python3 scripts/check_skill_pairs.py origin/main
"""

import subprocess
import sys

# Kept in sync with the tables in .gemini/skills/skills-index/SKILL.md and
# .github/skills/skills-overview/SKILL.md. Most groups are 2 files (Gemini +
# Copilot); a few skills are also mirrored to .claude/skills/ as a 3rd member.
GROUPS = [
    [".gemini/skills/plugin-development/plugin-skill.md", ".github/skills/plugin-run-development/SKILL.md", ".claude/skills/plugin-development/SKILL.md"],
    [".gemini/skills/plugin-readme/plugin-readme-skill.md", ".github/skills/plugin-readme/SKILL.md", ".claude/skills/plugin-readme/SKILL.md"],
    [".gemini/skills/testing-workflow/SKILL.md", ".github/skills/testing-workflow/SKILL.md", ".claude/skills/testing-workflow/SKILL.md"],
    [".gemini/skills/pr-analysis/SKILL.md", ".github/skills/pr-analysis/SKILL.md", ".claude/skills/pr-analysis/SKILL.md"],
    [".gemini/skills/scan-pipeline/SKILL.md", ".github/skills/scan-pipeline/SKILL.md", ".claude/skills/scan-pipeline/SKILL.md"],
    [".gemini/skills/database-patterns/SKILL.md", ".github/skills/database-patterns/SKILL.md", ".claude/skills/database-patterns/SKILL.md"],
    [".gemini/skills/prd-writing/SKILL.md", ".github/skills/prd-writing/SKILL.md", ".claude/skills/prd-writing/SKILL.md"],
    [".gemini/skills/ux-design-patterns/SKILL.md", ".github/skills/ux-design-patterns/SKILL.md", ".claude/skills/ux-design-patterns/SKILL.md"],
    [".gemini/skills/skill-hygiene/SKILL.md", ".github/skills/skill-hygiene/SKILL.md", ".claude/skills/skill-hygiene/SKILL.md"],
    [".gemini/skills/plugin-review/SKILL.md", ".github/skills/plugin-review/SKILL.md", ".claude/skills/plugin-review/SKILL.md"],
    [".gemini/skills/install-scripts/SKILL.md", ".github/skills/install-scripts/SKILL.md", ".claude/skills/install-scripts/SKILL.md"],
    [".gemini/skills/settings/SKILL.md", ".github/skills/settings-management/SKILL.md"],
    [".gemini/skills/mcp-activation/SKILL.md", ".github/skills/mcp-activation/SKILL.md"],
    [".gemini/skills/project-navigation/SKILL.md", ".github/skills/project-navigation/SKILL.md"],
    [".gemini/skills/logging-standards/SKILL.md", ".github/skills/logging-standards/SKILL.md"],
    [".gemini/skills/devcontainer-management/SKILL.md", ".github/skills/devcontainer-services/SKILL.md"],
    [".gemini/skills/devcontainer-management/SKILL.md", ".github/skills/devcontainer-setup/SKILL.md"],
    [".gemini/skills/devcontainer-management/SKILL.md", ".github/skills/devcontainer-configs/SKILL.md"],
]


def changed_files(base_ref):
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base_ref}...HEAD"],
        capture_output=True, text=True, check=True,
    )
    return set(result.stdout.splitlines())


def main():
    if len(sys.argv) != 2:
        print("usage: check_skill_pairs.py <base-ref>", file=sys.stderr)
        return 2

    changed = changed_files(sys.argv[1])
    problems = []
    for group in GROUPS:
        touched = [path for path in group if path in changed]
        untouched = [path for path in group if path not in changed]
        if touched and untouched:
            problems.append(
                f"- touched {', '.join(touched)} but not {', '.join(untouched)}."
            )

    if problems:
        print("Possible skill-group drift (only some mirrored files were touched):")
        print("\n".join(problems))
        print("\nIf the change is genuinely tool-specific, ignore this. "
              "Otherwise update the other file(s) too - see .gemini/skills/skills-index/SKILL.md.")
        return 1

    print("No skill-group drift detected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
