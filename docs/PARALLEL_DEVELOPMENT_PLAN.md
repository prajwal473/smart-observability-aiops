# PARALLEL_DEVELOPMENT_PLAN.md

How all four members start working **immediately and simultaneously** without waiting on each
other, and how their work reconverges at defined integration points. Consistent with
`TEAM_WORK_DISTRIBUTION.md` (roles) and `SHARED_CONTRACTS.md` (schemas — already locked as of
Batch 3, which is what makes this possible).

---

## The core enabling fact

Because `SHARED_CONTRACTS.md` and `API_DOCUMENTATION.md` are finalized *before* any
implementation code is written, every member can build against a **mock** of whatever they
don't own yet, using the exact same field names and shapes their real dependency will one day
produce. Swapping a mock for the real thing later is a data-source change, never a rewrite.

## Dependency graph

```
Member 1 (collector)  ──produces──▶  telemetry payloads (contracts §1-5)
Member 2 (backend)    ──consumes──▶  those payloads, OR sample-data mocks until M1 is ready
Member 2 (backend)    ──produces──▶  REST/WS APIs (API_DOCUMENTATION.md)
Member 3 (AIOps)      ──consumes──▶  ingested metadata from M2, OR sample-data mocks
Member 3 (AIOps)      ──produces──▶  anomalies/incidents/recommendations (contracts §7-9)
Member 2 (backend)    ──persists──▶  M3's output, exposes via API
Member 4 (frontend)   ──consumes──▶  M2's REST/WS APIs, OR sample-data mocks for everything
```

**Key property:** Member 4 never blocks on anyone, and Members 1/2/3 only block on each other at
the two integration checkpoints below — not continuously.

## Mock data contract

All four members treat `sample-data/` as a first-class dependency, not a throwaway. Required
fixtures (to be generated as part of the implementation file inventory, not this batch):

| Fixture file | Matches contract | Used by |
|---|---|---|
| `sample-data/infra_metrics_normal.json` | §2 | M2, M3, M4 |
| `sample-data/infra_metrics_cpu_spike.json` | §2 | M3, M4 (anomaly scenario) |
| `sample-data/network_metrics_latency_spike.json` | §3 | M3, M4 |
| `sample-data/security_auth_failure_burst.json` | §4 | M1, M3, M4 |
| `sample-data/collector_heartbeat_sequence.json` | §5 | M2, M4 |
| `sample-data/incidents_sample.json` | §7 | M4 |
| `sample-data/recommendations_sample.json` | §9 | M4 |
| `sample-data/egress_audit_sample.json` | §11 | M4 (Egress Proof Panel) |

Every fixture is hand-written to match `SHARED_CONTRACTS.md` exactly — field-for-field — so that
when a real producer comes online, the consumer's code doesn't change, only its data source.

## Integration checkpoints

### Checkpoint A — Hour 6 (contract sanity check)
Each member demos, in isolation, that their workspace can read/write the shared schemas
correctly using mocks:
- M1: shows a redacted payload matching contracts §1-5 in the Egress Proof Panel's own log
- M2: shows `/v1/ingest` accepting a contract-shaped mock payload and rejecting a
  non-allow-listed one
- M3: shows an anomaly object (contracts §8) produced from the CPU-spike fixture
- M4: shows all six dashboards rendering against the fixtures, including the Egress Proof Panel

No cross-member integration yet — this checkpoint catches contract drift early, cheaply.

### Checkpoint B — Hour 14 (real integration, per `HACKATHON_24H_PLAN.md`)
- M1's real collector output is pointed at M2's real `/v1/ingest`.
- M3's pipeline is pointed at M2's real database instead of fixtures.
- M4's data layer is switched from fixtures to M2's real REST/WS endpoints.
- Everyone merges `feature/*` → `integration` (see `GIT_WORKFLOW.md`) and the full stack is run
  together via `docker compose up` for the first time.

If something doesn't line up at Checkpoint B, the fix is almost always "a field doesn't match
`SHARED_CONTRACTS.md`" — not a logic bug — because logic was already tested against fixtures
built directly from that file.

## What each member does differently once their real dependency exists

| Member | Before checkpoint B | After checkpoint B |
|---|---|---|
| M2 | Seeds Postgres from fixtures matching contracts | Accepts real payloads from M1 |
| M3 | Runs pipeline against fixture files | Reads from M2's live Postgres |
| M4 | Fetches from local JSON files | Fetches from M2's live REST/WS |

Component code inside each workspace should not need to change at this swap — only the
data-access entry point (one function/module per workspace), which is why this plan insists on
`SHARED_CONTRACTS.md` discipline from the start.

## Commands every member should be able to run independently, from hour 0

```bash
# Member 1
cd collector-security && pytest tests/

# Member 2
cd backend-database && docker compose up db -d && pytest tests/

# Member 3
cd aiops-engine && pytest tests/ --fixtures=../sample-data/

# Member 4
cd frontend-dashboard && npm run dev   # against sample-data/ mocks
```

None of these require another member's service to be running.

## Risk this plan specifically protects against

The PDF's own "weak" signal for Phase 3: *"Polished screens backed by hard-coded data, no proof
of what leaves the collector."* Using real fixture files that match the exact production schema
— rather than frontend-only ad-hoc mock objects — means the swap to live data at Checkpoint B is
mechanical, so the team is never tempted to leave the frontend permanently on fake data because
wiring it up "would take too long" on demo day.
