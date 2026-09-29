---
name: pr-analysis
description: How to analyze and respond to GitHub PR review comments in NetAlertX. Use this whenever you are addressing PR feedback, review threads, or inline code comments.
---

# PR Analysis

## Standing Rule: A Repeated Comment Becomes a Skill Update

If a review comment corrects something a skill *should* already cover, don't just fix that one instance — update the relevant skill as part of addressing the comment, same PR, same turn. If no skill covers it yet, that's the signal to create one. Check the skill first, though — sometimes it already covers the point and just wasn't consulted; the fix is in *applying* it, not in the skill being incomplete.

## Code Style

- **Prefer explicit, readable logic over compact-but-opaque expressions.** When a built-in/clever expression (e.g. a `max()`-based one-liner) saves a line or two but a reader has to reverse-engineer *why* it produces the right answer, write it out as plain conditional logic instead.

## Before Writing Any Test Code — Non-Negotiable Checklist

Run through this before creating or editing any file under `test/`:

1. **Helpers first:** Check `test/db_test_helpers.py` for existing factories (`make_db`, `make_device_dict`, `insert_device_from_dict`, `DummyDB`). Use them. If what you need doesn't exist, add it there — never define it locally in the test file.
2. **MAC literals must be lowercase:** Every MAC string in fixtures, parametrize, assertions, docstrings, and comments must be lowercase hex (e.g. `aa:bb:cc:dd:ee:01`). No exceptions.
3. **Test file location:** Place *new* tests under a subdirectory of `test/` that mirrors the source path (e.g. `test/scan/` for `server/scan/`). Don't add new files directly in `test/` root - a handful of existing ones there (e.g. `test_plugin_helper.py`, `test_wol_validation.py`) predate this convention; that's not license to add more, but don't migrate them unprompted either.
4. **No inline imports:** All imports at the top of the file.

## Before Acting on Any PR Comment

1. Load `code-standards` skill — all code changes must comply with it before replying.
2. Load `testing-workflow` skill — any test additions or changes must follow it.
3. Load any domain-specific skill relevant to the files being changed (e.g. `database-patterns` for DB writes, `settings` for config).

## Comment Classification

For each comment, determine:

| Type | Action |
|------|--------|
| Request for code change | Make the change, validate it, then reply with the short commit hash |
| Question about code | Reply with a concise answer (no restatement of the question) |
| Suggestion / feedback | Decide if it is actionable. If yes, act and reply. If not, do not reply. |
| General / praise | Do not reply. |

## Acting on Comments — Step by Step

1. **Identify all actionable comments** before touching any file.
2. **Load relevant skills** to understand conventions that apply.
3. **Prepare a plan** — list each file and the exact change required.
4. **Make changes one comment at a time** — keep commits focused.
5. **Run targeted tests** after each change (`testing-workflow` skill).
6. **Reply** only after the commit is pushed. Include the short SHA.

## Reply Guidelines

- Be concise. Do not summarize or restate the original comment.
- State what was done and (optionally) why.
- Include the short commit hash when relevant.
- Do not thank or compliment the reviewer.

## What to Check After Every Batch of Changes

- **MAC literals lowercase** — grep for uppercase hex in every changed test file: `grep -Pn '[0-9A-F]{2}:[0-9A-F]' test/` must be empty.
- **No local DB helpers** — no `DummyDB`, `make_db`, or inline DDL defined outside `test/db_test_helpers.py`.
- No inline imports — all imports at the top of the file.
- Tests live under a subdirectory of `test/` matching the source path, not in `test/` root.
- Secret scan (`runtime-tools-secret_scanning`) before committing.

## Stacked / Base-Branch Issues

When a PR targets a non-default branch (e.g. `next_release`):
- Do **not** retarget the branch yourself; note it in a reply so the author can do it from the GitHub UI.
- Check CI failures on the **base branch** first before checking your branch.
