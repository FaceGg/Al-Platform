---
name: project-audit
description: Audit repository AGENTS.md, project plans, SKILL.md files, and CI workflows for conflicts, duplication, stale facts, unsafe autonomy rules, and weak verification. Use when the user asks to review or optimize agent instructions or development workflows. Do not edit files unless the user explicitly asks for implementation after the audit.
---

# Project Instruction Audit

## Workflow

1. Read applicable `AGENTS.md`, the current project plan, relevant skills, and workflow
   files. Exclude `.git`, `.worktrees`, virtual environments, and dependencies unless
   they are the subject of the audit.
2. Record each rule's source, scope, priority, and currentness.
3. Check autonomy, clarification, approval, completion, verification, context loading,
   and tool-call rules for conflicts and duplication.
4. Separate current project facts from historical evidence and stale paths, dates,
   branches, or commit IDs.
5. Report findings first, ordered by severity, with exact file and line references.
6. Give concrete edits and an implementation order. Preserve historical records.

## Boundaries

- An audit-only request is read-only.
- Do not infer that a repository skill exists from files inside dependencies or
  worktrees.
- Do not recommend full-suite verification for documentation-only work unless the
  repository contract explicitly requires it.
