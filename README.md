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

```text
smart-observability/
├── docs/                    # Architecture, contracts, design docs
├── collector-security/       # Member 1 — local collector, redaction, egress audit
├── backend-database/         # Member 2 — backend and database
├── aiops-engine/             # Member 3 — baselines, anomaly detection, correlation, recommendations
├── frontend-dashboard/       # Member 4 — React dashboards incl. Egress Proof Panel
├── shared/                   # Shared schemas/types used by all workspaces
├── sample-data/               # Mock telemetry and API responses
├── scripts/                   # Setup / run / seed scripts
├── tests/                     # Cross-cutting integration tests
├── logs/                      # Runtime logs (gitignored contents)
├── deployment/                 # Docker / compose / env templates
├── .env.example
├── docker-compose.yml
├── README.md
└── MASTER_PROJECT.md           # Full requirements, architecture and rubric
```

## Quick start

```bash
git clone <repo-url>
cd smart-observability
cp .env.example .env
docker compose up --build
```

- Frontend dashboard: `http://localhost:5173`
- Backend API docs: `http://localhost:8000/docs`
- Collector runs locally per-member during development. Refer to the collector workspace README for instructions.

## The two-tier flow

```text
Tier 1 (Customer Environment)                 Tier 2 (Central SaaS, multi-tenant)

Telemetry sources
  → Collect → Filter/Redact → Aggregate       Regional ingest endpoint
  → Analyze locally → Apply data policy          → Metadata ingestion (allow-listed only)
  → SQLite buffer + retry                        → Fleet analytics, tenant isolation
  → Egress Proof Panel (audit log)                → AIOps: baseline → anomaly → correlate → recommend
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

Full role breakdown, file ownership and boundaries: `TEAM_WORK_DISTRIBUTION.md`.

## Performance targets

| Measure | Target |
|---|---|
| Collection → dashboard latency | ≤10s at p95 |
| Threshold breach → alert raised | ≤15s |
| Collector offline detection | ≤60s of last heartbeat |
| Post-outage backlog delivery | Zero loss, zero duplicates |

These are suggested targets pending organizer confirmation and live measurement.

## Mandatory judging requirements

1. Real-time performance targets must be measured, never claimed without evidence.
2. The platform must use the organizer-provided simulated telemetry stream.
3. A working **Egress Proof Panel** must show exact payload contents before transmission.

## Known risks

- Redaction false negatives are the highest-visibility failure mode. Default-deny allow-listing is used instead of deny-listing.
- Tenant isolation must be enforced at the query layer, not only at the API layer.
- Out-of-order and idempotent delivery logic require dedicated tests.
- Autonomous Ops stays simulated and safe-test only, in accordance with the official rubric.

## Project status

The platform is being developed collaboratively across four workspaces.

Each member is responsible for their designated workspace, and integration is managed through Git branches and pull requests.

Refer to `MASTER_PROJECT.md` and `TEAM_WORK_DISTRIBUTION.md` for architecture, requirements, implementation details and responsibilities.