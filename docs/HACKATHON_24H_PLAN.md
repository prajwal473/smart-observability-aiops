# HACKATHON_24H_PLAN.md — 24-Hour Execution Plan

Project: Smart Observability and AIOps Platform (CICADA 2026)
Team: 4 members, 4 independent workspaces
Branches: `main`, `integration`, `feature/collector-security`, `feature/backend-database`, `feature/aiops-engine`, `feature/frontend-dashboard`

> Hour 0 = official start of the hackathon. Replace clock times in the "Wall clock" column once the start time is known.
> Performance targets (10 s dashboard latency p95, 15 s alert, 60 s offline detection, zero loss / zero duplicates) are **targets to be measured**, never claimed as achieved until measured.

---

## 1. Roles

| Member | Workspace | Short name |
|---|---|---|
| Member 1 | `collector-security` | COL |
| Member 2 | `backend-database` | BE (also integration coordinator) |
| Member 3 | `aiops-engine` | AI |
| Member 4 | `frontend-dashboard` | FE |

---

## 2. Phase Timeline

### Hours 0–2 — Architecture, Requirements, Contracts, Allocation

| Member | Tasks | Exit criteria |
|---|---|---|
| All | Read the official PDF together; list mandatory vs optional vs bonus items | Requirements list agreed |
| All | Freeze `SHARED_CONTRACTS.md` v1.0 (field names, IDs, UTC timestamps, enums) | Contracts committed to `main` |
| BE | Create repo skeleton, branches, `.env.example`, `docker-compose.yml` | Repo cloned by all four |
| COL | Confirm allow-list fields and redaction rule list | Rule list in `shared/` |
| AI | Confirm input/output shapes for anomaly, incident, recommendation, health | Shapes in contracts |
| FE | Create mock JSON from contract examples in `sample-data/` | Mock files committed |

**Gate G0 (hour 2):** contracts frozen. After this point any contract change needs a message to all four members and a version bump.

### Hours 2–6 — Independent Module Foundations

| Member | Tasks | Exit criteria |
|---|---|---|
| COL | Telemetry generator (CPU, memory, disk, bandwidth, latency, packet loss, failed logins); config loader; SQLite schema (queue, audit) | Generator emits valid contract JSON |
| BE | FastAPI app, Pydantic models from contracts, SQLAlchemy models, Alembic migration, PostgreSQL in Compose, `/health` | `docker compose up` starts API + DB |
| AI | Baseline calculator (moving average, rolling mean/std), z-score detector with unit tests on synthetic series | `pytest aiops-engine` green for detectors |
| FE | Vite + React + TS + Tailwind scaffold, layout, routing, typed API client reading mock JSON | App renders shell with mock data |

### Hours 6–10 — Core Features

| Member | Tasks | Exit criteria |
|---|---|---|
| COL | Normalizer, allow-list validator, secret scrubber, redaction engine, pseudonymous source IDs | Redaction unit tests pass on sample secrets |
| BE | Tenant + collector registration, collector token auth, `POST /ingest`, `POST /heartbeat`, idempotency on `payload_id` | Ingest accepts valid payload, rejects duplicate |
| AI | Event correlation (time window + shared collector/tenant), incident priority scoring | Correlation tests pass |
| FE | Infrastructure and Network dashboards with Recharts (mock data) | Both pages show charts |

### Hours 10–14 — Redaction, Ingestion, Anomaly Detection, Dashboards

| Member | Tasks | Exit criteria |
|---|---|---|
| COL | SQLite buffer, sender with HTTPS, exponential backoff + jitter, egress audit log, local aggregation | Collector sends to a stub endpoint, buffers when it is down |
| BE | Persist metrics/heartbeats, tenant-scoped REST read APIs, offline detector (heartbeat age), WebSocket broadcast | REST + WS return tenant data only |
| AI | Health classifier (Excellent/Good/Fair/Poor, configurable thresholds, reasons, stale-data handling), recommendation engine with explanations, root-cause hints | Health + recommendation tests pass |
| FE | Security, Collector Fleet, Incident, Recommendation dashboards; **Egress Proof Panel** (payload viewer, redaction diff, audit list) | All pages render with mock data |

**Gate G1 (hour 14):** each module passes its own unit tests and runs standalone against mocks/stubs. Merge each feature branch into `integration` (BE performs merges).

### Hours 14–18 — Integration

| Step | Owner | Action |
|---|---|---|
| 1 | BE | Wire AI engine into ingestion pipeline (call after ingest, store anomalies/incidents/recommendations) |
| 2 | COL + BE | Point collector at real backend; verify auth, tenant, idempotency |
| 3 | FE + BE | Replace mock client with real REST/WS; keep a `USE_MOCK` flag as demo fallback |
| 4 | All | Run end-to-end scenarios 1–9 from `DEMO_GUIDE.md`; log defects in `INTEGRATION_CHECKLIST.md` |

**Gate G2 (hour 18):** normal flow + CPU spike → anomaly → incident → recommendation visible in the dashboard from real collector data.

### Hours 18–21 — Testing, Reliability, Performance

| Member | Tasks |
|---|---|
| COL | Outage test: stop backend, generate data, restart, confirm backlog delivered with zero loss / zero duplicates; out-of-order timestamps |
| BE | Offline detection test (stop collector, expect flag within 60 s of last heartbeat); duplicate replay test; tenant isolation test (tenant A token cannot read tenant B) |
| AI | Tune thresholds against recorded demo data; verify explanations are readable |
| FE | Latency timestamps in UI (collect → ingest → render); polish; empty/error/stale states |
| All | Measure the four performance targets with timestamps; record **actual** numbers in `FINAL_QUALITY_REPORT.md` |

**Gate G3 (hour 21):** feature freeze. Only bug fixes after this point.

### Hours 21–24 — Bug Fixes, Demo, Presentation

| Time | Activity |
|---|---|
| 21:00–22:00 | Fix P0/P1 defects from checklist; rebuild clean from `docker compose up` on a fresh clone |
| 22:00–23:00 | Full demo rehearsal #1 (timed); prepare fallback recording/screenshots |
| 23:00–23:40 | Slides/presentation final; rehearsal #2 |
| 23:40–24:00 | Tag release on `main`, laptop/charging/network check, submission |

---

## 3. Checkpoints and Escalation

| Checkpoint | Hour | Question | If late |
|---|---|---|---|
| Contracts frozen | 2 | All four have the same JSON? | Stop work, fix contracts first |
| Standalone modules | 14 | Unit tests green per module? | Cut optional features for that module |
| First end-to-end | 18 | Real collector → dashboard? | All hands on integration, pause polish |
| Feature freeze | 21 | Everything mandatory demoable? | Use mock/simulated fallback, document honestly |

## 4. Scope Control (Cut List, in order)

If time runs short, cut in this order (cut from the top first):
1. Isolation Forest (keep z-score + moving average)
2. Autonomous Ops simulation UI
3. WebSocket (fall back to 5 s polling)
4. Extra dashboard polish
5. Multi-region ingestion beyond a documented design + region field

**Never cut:** redaction, allow-list, Egress Proof Panel, SQLite buffer + retry, idempotency, tenant isolation, four health states, offline detection.

## 5. Daily Rhythm

- 15-minute sync at hours 2, 6, 10, 14, 18, 21.
- Commit small and often; push to your feature branch at least every hour.
- Only Member 2 merges into `integration`; only the team together merges `integration` into `main`.
- Blocked for more than 20 minutes: post in the team chat with file name and error.

## 6. Risks to the Schedule

| Risk | Mitigation |
|---|---|
| Contract drift | Contracts frozen at G0; changes need version bump |
| Integration surprises | Stubs/mocks per module; early integration at hour 14 |
| Docker/network issues at venue | Test Compose on all laptops by hour 6; keep a non-Docker run path in `SETUP_SCRIPTS.md` |
| Performance not measured | Timestamp fields in payloads from the start; measure at hours 18–21 |
| Demo failure | Recorded fallback video + seeded demo data script |
| Fatigue | Rotate breaks; no new features after hour 21 |
