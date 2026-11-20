# Smart Observability & AIOps Platform

CICADA 2026 — 24-Hour Hackathon · TechForcz x Atria Institute of Technology

> Local-first data security · Metadata-only SaaS communication · AIOps-driven operations ·
> Global-ready design · Future Autonomous Ops

A secure, two-tier observability platform: a **local collector** processes infrastructure,
application, network and security telemetry entirely inside the customer environment, redacts
and allow-lists it, and sends only approved metadata to a **multi-tenant SaaS platform** that
runs AIOps (anomaly detection, correlation, prioritized incidents, explainable
recommendations) on top of it.

For the full requirements source-of-truth, read **`MASTER_PROJECT.md`** first. This README is
the quick-start.

## Why this architecture

Raw logs, payloads and credentials never leave the customer environment. Only allow-listed
metadata — metric values, timestamps, pseudonymous source IDs, health state, event category,
severity, and concise alert context — crosses the trust boundary. Every payload that leaves is
visible in the **Egress Proof Panel** before and after transmission.

## Repository layout

```
smart-observability/
├── docs/                    # Architecture, contracts, design docs (see docs/ for full list)
├── collector-security/      # Member 1 — local collector, redaction, egress audit
├── backend-database/        # Member 2 — FastAPI + PostgreSQL SaaS backend
├── aiops-engine/            # Member 3 — baselines, anomaly detection, correlation, recs
├── frontend-dashboard/      # Member 4 — React dashboards incl. Egress Proof Panel
├── shared/                  # Shared schemas/types used by all four workspaces
├── sample-data/             # Mock telemetry + mock API responses for parallel dev
├── scripts/                 # Setup / run / seed scripts
├── tests/                   # Cross-cutting integration tests
├── logs/                    # Runtime logs (gitignored contents)
├── deployment/              # Docker / compose / env templates
├── .env.example
├── docker-compose.yml
├── README.md                ← you are here
└── MASTER_PROJECT.md         # Full requirements, architecture, rubric — source of truth
```

## Quick start (once implementation files exist)

```bash
git clone <repo-url>
cd smart-observability
cp .env.example .env
docker compose up --build
```

- Frontend dashboard: `http://localhost:5173`
- Backend API docs: `http://localhost:8000/docs`
- Collector runs locally per-member during dev; see `collector-security/README` (to be
  generated) for standalone run instructions.

> Implementation files have not been generated yet as of this batch (Batch 1 of 9 in
> documentation phase). This section will be filled in with real run commands once
> `backend-database` and `frontend-dashboard` exist.

## The two-tier flow, in one picture

```
Tier 1 (Customer Environment)                 Tier 2 (Central SaaS, multi-tenant)
Telemetry sources
  → Collect → Filter/Redact → Aggregate       Regional ingest endpoint
  → Analyze locally → Apply data policy          → Metadata ingestion (allow-listed only)
  → SQLite buffer + retry                        → Fleet analytics, tenant isolation
  → Egress Proof Panel (audit log)                → AIOps: baseline→anomaly→correlate→recommend
  → TLS + authenticated transmission  ──────→     → Dashboards / Alerts / Recommendations
                                                    → (future) policy-controlled Autonomous Ops
```

## Team

| Member | Owns | Workspace |
|---|---|---|
| 1 | Collector & Security | `collector-security/` |
| 2 | Backend & Database | `backend-database/` |
| 3 | AIOps Engine | `aiops-engine/` |
| 4 | Frontend Dashboard | `frontend-dashboard/` |

Full role breakdown, file ownership, and "do not touch" boundaries: `TEAM_WORK_DISTRIBUTION.md`.

## Performance targets (must be measured live, never claimed)

| Measure | Target |
|---|---|
| Collection → dashboard latency | ≤10s at p95 |
| Threshold breach → alert raised | ≤15s |
| Collector offline detection | ≤60s of last heartbeat |
| Post-outage backlog delivery | zero loss, zero duplicates |

These are the PDF's **suggested** values, pending organizer confirmation on the day.

## Mandatory for every team (per official judging guide)

1. Real-time targets above, measured from timestamps — never claimed without evidence.
2. Built against the same organizer-provided simulated telemetry stream as all other teams.
3. A working **Egress Proof Panel** showing exact payload contents before transmission.

## Known risks (tracked, not hidden)

- Redaction false negatives are the highest-visibility failure mode for judges — default-deny
  allow-listing is used everywhere, never a deny-list.
- Tenant isolation must be enforced at the query layer, not just the API layer.
- Out-of-order + idempotent delivery logic needs dedicated tests, not just "looks right in demo."
- Autonomous Ops (Stage 5 of the roadmap) stays simulated/safe-test only — this is explicit in
  the official rubric, not a corner we're cutting.

## Status

Documentation Batch 1 of 9 complete (`MASTER_PROJECT.md`, `README.md`,
`TEAM_WORK_DISTRIBUTION.md`). No implementation files generated yet. See
`MASTER_PROJECT.md` §12 for the live status tracker.
