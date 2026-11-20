# GIT_WORKFLOW.md

Branching and merge discipline for a 24-hour, four-person hackathon — optimized for "never
blocked, never silently diverged," not for enterprise ceremony.

---

## Branches

```
main
 └── integration
      ├── feature/collector-security     (Member 1)
      ├── feature/backend-database       (Member 2)
      ├── feature/aiops-engine           (Member 3)
      └── feature/frontend-dashboard     (Member 4)
```

- `main` — only ever updated from a tested `integration` branch. Never commit directly to
  `main` during the hackathon.
- `integration` — where all four feature branches come together. Must always be in a state
  that `docker compose up` can run, even if individual features are incomplete.
- `feature/<workspace>` — one per member, matches their workspace directory name exactly. All
  day-to-day work happens here.

## Rules

1. **Never commit to another member's `feature/*` branch.** If you need a contract change,
   open a PR against `SHARED_CONTRACTS.md` on your own branch and flag it in the team channel —
   don't fix it inside someone else's code.
2. **Commit early, commit often.** In a 24h event, an uncommitted hour of work lost to a laptop
   crash is a bigger risk than messy commit history. Squashing can happen before the final
   merge to `integration`, not before.
3. **Merge to `integration` happens at the two checkpoints** defined in
   `PARALLEL_DEVELOPMENT_PLAN.md` (Hour 6 sanity check, Hour 14 real integration) — plus any time
   in between if a member finishes a chunk and wants early feedback. Don't wait until hour 20 to
   merge for the first time.
4. **`integration` → `main`** only happens after the full stack has been run together via
   `docker compose up` and the smoke test (`GET /health` + one dashboard load) passes.
5. Pull `integration` into your `feature/*` branch regularly (at least once per checkpoint) so
   merge conflicts are small and frequent, not one enormous conflict at hour 18.

## Commit message convention

```
<workspace>: <short description>

e.g.
collector: add default-deny allow-list validator with unit tests
backend: add tenant-scoped query helper, enforce tenant_id on every read
aiops: add z-score anomaly detector against rolling baseline
frontend: add Egress Proof Panel raw-vs-sent diff view
docs: update SHARED_CONTRACTS.md with egress_audit fields_redacted field
```

Prefix with the workspace name even for doc changes, so `git log` is skimmable under time
pressure.

## Pull requests (lightweight, for a 24h event)

- PR title = commit convention above.
- PR description: one line on what changed, one line on what it depends on/affects in
  `SHARED_CONTRACTS.md` if anything.
- Reviewer: whoever's nearest/fastest to respond — this isn't a formal review gate, it's a
  "did I break your contract" sanity check. A thumbs-up in the team chat counts if a full PR
  review would stall the merge past a checkpoint.

## Handling a contract change mid-event

1. Edit `SHARED_CONTRACTS.md` on your branch.
2. Post the diff in the team channel immediately — don't wait for the next checkpoint to
   surface it.
3. Any member whose code depends on the changed field updates their own branch before the next
   `integration` merge.
4. If a contract change would break something already merged to `integration`, it goes through
   `integration` directly as a fast-follow commit, tagged `docs: contract-change` in the
   message, so it's easy to find later.

## What NOT to do

- Don't rebase `integration` or `main` — only fast-forward or ordinary merge. Rebasing shared
  branches under time pressure is how someone loses work.
- Don't leave a `feature/*` branch more than ~4 hours stale relative to `integration` without
  pulling — the longer it diverges, the worse the eventual merge.
- Don't merge directly to `main` to "save time" — `integration` is the safety net that keeps
  `main` always demo-able if something goes wrong late in the event.

## End-of-event state

`main` should reflect exactly what's demoed. If a feature didn't make it into a clean
`integration` merge in time, it stays out of `main` and is mentioned honestly in
`FINAL_QUALITY_REPORT.md` (Batch 8) as a limitation — never force-merged in a last-minute panic
that risks breaking what already works.
