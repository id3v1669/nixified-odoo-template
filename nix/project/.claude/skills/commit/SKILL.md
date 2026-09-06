---
name: commit
description: Use when committing Odoo addon changes or preparing commit messages during the development pipeline.
argument-hint: "[optional commit message override]"
---

# Commit Odoo changes

Read `.claude/project-context.md` for the module and ticket prefixes.
Use Conventional Commits for every generated project, including Odoo addons.

```text
fix(acme_stock): prevent duplicate reservations

Duplicate reservations could allocate the same stock twice.

ACME-412
```

The subject is `type(scope): description` or `type: description`. Use the
technical module name as the scope when it helps identify the change.
Choose `fix` for bugs, `feat` for features, `refactor` for restructuring,
`perf` for performance, `docs` for documentation, `test` for tests, and
`chore` for maintenance or dependency updates. Use `revert` for a revert.
Do not use Odoo's bracketed tags such as `[FIX]`, `[IMP]`, or `[ADD]`.

Use an imperative description: "prevent duplicate reservations", "add a
warehouse filter", or "remove the obsolete view". Keep the subject under
72 characters. Put ticket references in the body. For a nontrivial change,
explain the problem and why the change solves it; include technical decisions
that help the reviewer. Separate the body from the subject with a blank line.

Before committing:

1. Review the full staged diff and confirm it contains only the intended work.
2. Run the checks appropriate to the change and read their results.
3. Follow the project and user requirements for review, authorship, and signing.
4. Write the commit using the format above. An old draft, pipeline example, or
   review comment using a bracketed tag must be rewritten into this format.

Follow the user's authorization for publishing. Permission to commit alone does
not authorize a push.

If formatting reflows an existing file, separate the pure formatting change
into `chore(module): format file` before the functional change. Review both
diffs. Run `ruff format --check` on changed Python files, including edits made
through shell commands, because those edits may not trigger the editor hook.
Avoid mixing changes to unrelated modules in one commit.
