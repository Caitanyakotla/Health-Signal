---
name: diagnosing-ci-failures
description: Diagnoses failed GitHub Actions runs and applies the fix — reads failure logs, identifies the root cause, reports it in a structured format, edits repo files, then commits and pushes for human approval. Use when handling a failed CI/CD workflow run, pipeline failure, security-scan failure, or any GitHub Actions run that needs diagnosis or repair.
---

# Diagnosing CI Failures

Workflow for turning a failed GitHub Actions run into a reviewed, pushed fix.

Copy this checklist and check items off as you complete them:

```
Fix Progress:
- [ ] Step 1: Investigate the failure
- [ ] Step 2: Report root cause (before changing anything)
- [ ] Step 3: Implement the fix
- [ ] Step 4: Commit and push
```

## Step 1: Investigate

The run summary and failed-step logs are already included in the task
message — start from those. Fetch more only if they are not enough:

```bash
gh run view <run-id> --repo <owner/repo> --log-failed
```

Read the workflow file and any source files needed to understand the failure.
This repo's pipeline (jobs, tools, usual failure classes) is described in
[references/pipeline.md](references/pipeline.md) — read it to map the failed
job to its purpose.

**Short-circuits** — report and stop, make no code changes:

- **Transient / external failure** (runner outage, network flake, rate limit,
  registry hiccup): say so and recommend `gh run rerun <run-id>`.
- **Run actually succeeded**: say so, give a one-paragraph pipeline health
  summary.

## Step 2: Report root cause

Report before changing anything, in exactly this format:

```
## ROOT CAUSE
(2-4 sentences, plain language)

## SUGGESTED FIX
(numbered steps a human could follow)
```

## Step 3: Implement the fix

Edit files in the repo to apply the fix. Prefer the smallest change that
makes the pipeline green — no refactoring or cleanup around the fix.

## Step 4: Commit and push

1. Stage ONLY the files you changed (`git add <file>` — never `git add -A`
   or `git add .`; the checkout may contain unrelated work-in-progress that
   is not yours to commit).
2. Commit with message: `ci-fix: <one-line summary>` — subject line only,
   no trailers.
3. Push to the SAME branch the failed run was on:
   `git push origin <branch>`

The push triggers a human approval prompt automatically — you don't need to
ask first, just run it. If the human denies it, do not retry: leave the fix
as local changes, summarize what you changed so they can review, and stop.
