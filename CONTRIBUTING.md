# CONTRIBUTING.md — Contribution Guide

Project: Smart Observability and AIOps Platform (CICADA 2026)
Team size: 4 members, 4 workspaces. These rules keep four people working in parallel without breaking each other.

---

## 1. Ground Rules

1. **The shared contracts are law.** Field names, enums, ID formats and timestamp formats come from `docs/SHARED_CONTRACTS.md` and `shared/`. Do not invent or rename fields. Need a change? Message all members, bump the contract version, update the examples.
2. **Stay inside your workspace.** Edit only files you own (see `TEAM_WORK_DISTRIBUTION.md`). If you need a change elsewhere, ask the owner or open a note in the team chat.
3. **Never commit secrets.** No real passwords, tokens, API keys or customer data. Use `.env` (ignored by Git) and `.env.example` (placeholders only). Demo "secrets" must be obviously fake.
4. **Never log raw telemetry or credentials in SaaS-side code.** Collector-side raw data stays local.
5. **Do not claim what you did not run.** Do not write "tested" or "passes" in docs or commit messages unless you ran it.
6. **Prefer a working end-to-end prototype over perfection.** No over-engineering.

## 2. Workspace Ownership

| Workspace | Owner | Others may not edit |
|---|---|---|
| `collector-security/` | Member 1 | Members 2, 3, 4 |
| `backend-database/` | Member 2 | Members 1, 3, 4 |
| `aiops-engine/` | Member 3 | Members 1, 2, 4 |
| `frontend-dashboard/` | Member 4 | Members 1, 2, 3 |
| `shared/`, `docs/`, `sample-data/` | Everyone, via agreed changes | — |
| `docker-compose.yml`, `deployment/`, `.env.example` | Member 2 (coordinator) | Ask before editing |

Member 2 coordinates integration but does not implement other members' modules.

## 3. Branching

```
main                         stable, demo-ready only
integration                  where feature branches are combined and tested
feature/collector-security   Member 1
feature/backend-database     Member 2
feature/aiops-engine         Member 3
feature/frontend-dashboard   Member 4
```

- Work on your own feature branch.
- Never push directly to `main`.
- Only Member 2 merges feature branches into `integration`.
- `integration` goes to `main` only after the integration checklist gate passes, and with the whole team agreeing.
- Pull from `integration` regularly to catch conflicts early.

## 4. Commit Rules

- Small, frequent commits; push at least hourly.
- Message format: `<area>: <short imperative summary>`

  Examples:
  - `collector: add secret scrubber for bearer tokens`
  - `backend: reject duplicate payload_id`
  - `aiops: add z-score detector with tests`
  - `frontend: add egress proof panel`
  - `docs: update contract example for heartbeat`

- One logical change per commit. Do not mix formatting with behaviour changes.

## 5. Pull Request / Merge Checklist

Before asking for a merge into `integration`:

- [ ] Module unit tests pass locally (state the command you ran)
- [ ] Uses contract field names exactly
- [ ] No files outside your workspace changed (unless agreed)
- [ ] No secrets, no large generated files, no `node_modules`, no `.venv`, no local `.db` files
- [ ] README / run instructions for your module still correct
- [ ] New environment variables added to `.env.example`
- [ ] Logs contain no credentials or raw sensitive telemetry

Reviewer (Member 2, plus the owner of any touched contract) checks the same list and runs the module command.

## 6. Code Standards

### Python (collector, backend, AIOps)
- Python 3.11+, type hints on public functions.
- Pydantic models for every payload crossing a module boundary.
- Format and lint with the team-agreed tool (for example `ruff` or `black`); run before committing.
- Tests with `pytest`, located in each module's `tests/` folder.
- Use structured (JSON) logging via the shared logging helper; never `print` in module code.
- Timestamps: UTC, ISO-8601 with `Z`, always timezone-aware. Keep the source timezone as a separate field.

### TypeScript / React (frontend)
- Strict TypeScript; types mirror the contracts (keep them in one `types` file).
- Components small and focused; Tailwind for styling; Recharts for charts; Lucide for icons.
- Every page must handle loading, empty, error and stale-data states.
- API access only through the API client module so mock and real backends can be swapped with one flag.

### General
- Constants and thresholds in configuration, not hard-coded.
- Handle failures explicitly (no silent `except: pass`).
- Comments explain *why*, not *what*.

## 7. Testing Expectations

| Module | Minimum tests |
|---|---|
| Collector | Redaction removes seeded secrets; allow-list drops unknown fields; buffer stores and drains; backoff grows; no duplicate `payload_id` on resend |
| Backend | Auth rejects bad token; tenant isolation; idempotent ingest; heartbeat updates last-seen; offline detection |
| AIOps | Baseline on known series; z-score flags a spike and not noise; correlation groups related events; health state boundaries; recommendation includes explanation |
| Frontend | Renders with mock data; handles empty/error states; Egress Proof Panel shows payload |

## 8. Handling Contract Changes

1. Propose in the team chat: what, why, which modules break.
2. All four members agree (a thumbs-up from each is enough).
3. Update `docs/SHARED_CONTRACTS.md`, the `shared/` models and the sample JSON in the same commit.
4. Bump the version note at the top of the contracts document.
5. Each member updates their module before the next integration merge.

## 9. Communication

- Blocked for more than 20 minutes: post file name, command, and error text.
- Breaking changes: announce before merging.
- Defects found during integration go in the Defect Log in `INTEGRATION_CHECKLIST.md`.

## 10. Do and Don't

| Do | Don't |
|---|---|
| Pull before you push | Force-push shared branches |
| Use mock data until APIs exist | Wait idle for another member |
| Write the test with the feature | Leave tests for the last hour |
| Keep PRs small | Rewrite another member's module |
| Record real measurements | Quote targets as achievements |
