# TEAM_WORK_DISTRIBUTION.md

Four independent workspaces, one shared contract layer (`shared/`, defined in full in
`SHARED_CONTRACTS.md`, Batch 3). No member may implement another member's workspace. Everyone
can start immediately using mock data from `sample-data/` while contracts are finalized.

---

## Member 1 — Collector & Security

**Workspace:** `collector-security/`
**Branch:** `feature/collector-security`

### Responsibilities
- Telemetry generator (simulates CPU/memory/disk/network/security sources; swappable later for
  the organizer-provided stream)
- Local collector core loop: Collect → Filter → Redact → Aggregate → Analyze locally → Apply
  data policy → Transmit
- Field allow-list validator (default-deny: nothing leaves unless explicitly allow-listed)
- Secret scrubbing engine
- Sensitive-data redaction
- Pseudonymous source identifier generation (stable per source, not reversible from SaaS side)
- Local aggregation/summarization logic
- SQLite local buffer + retry queue (exponential backoff)
- Egress audit log (every payload, pre-transmission, timestamped)
- Collector authentication (credentials/cert used to talk to backend)
- Collector configuration file + config status reporting
- Structured collector logs (never containing secrets or raw sensitive content)

### Files owned
`collector-security/**` (generator, collector core, redaction engine, allow-list validator,
buffer, egress audit module, config, logs, its own tests)

### Files NOT to modify
Anything under `backend-database/`, `aiops-engine/`, `frontend-dashboard/`. Schema changes go
through `shared/` + a PR that all members review.

### Dependencies
- Consumes: nothing from other members to *start* (works standalone against its own generator)
- Produces for Member 2: metadata payloads matching the `telemetry_metadata` / `infrastructure_metrics`
  / `network_metrics` / `security_events` / `collector_heartbeat` / `egress_audit` schemas
  (defined in `SHARED_CONTRACTS.md`)

### Mock data
Can self-generate telemetry; does not need mocks from anyone else to begin.

### Commands (placeholder — finalized once implementation exists)
```bash
cd collector-security
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python generator.py        # starts telemetry simulation
python collector.py        # starts collector loop against generator output
```

### Expected results
Raw telemetry with secrets visible only in local logs/SQLite; redacted, allow-listed metadata
queued for transmission; egress audit entries matching exactly what gets sent.

### Unit tests
Allow-list validator (deny-by-default proven with adversarial field names), secret scrubber
(known secret patterns never pass through), buffer/retry (no data loss across simulated outage).

### Integration requirement
Payload shape must validate against the shared Pydantic/JSON schema before Member 2's ingestion
endpoint will accept it.

---

## Member 2 — Backend & Database

**Workspace:** `backend-database/`
**Branch:** `feature/backend-database`

### Responsibilities
- FastAPI application (REST + WebSocket)
- PostgreSQL schema via SQLAlchemy models + migrations
- Collector authentication/registration endpoints
- Telemetry ingestion API (validates against allow-list schema; rejects anything not allow-listed)
- Heartbeat API (collector online/offline, last-seen, version, resource usage, config status)
- Tenant isolation enforced at the query layer (every query scoped by tenant_id, not just the
  API boundary)
- WebSocket channel for live dashboard updates
- Backend structured logging (ingestion, auth, tenant access, errors — never raw sensitive data)
- Coordinates cross-team integration points, but does **not** implement collector, AIOps, or
  frontend logic

### Files owned
`backend-database/**` (FastAPI app, models, migrations, auth, ingestion/heartbeat routers,
WebSocket handlers, its own tests)

### Files NOT to modify
`collector-security/**`, `aiops-engine/**`, `frontend-dashboard/**`

### Dependencies
- Consumes: payload schemas from `shared/` (owned jointly, changes require team review);
  Member 1's payload shape; Member 3's anomaly/incident/recommendation output shape to persist
  and expose via API
- Produces for Member 3: raw ingested metadata, queryable by time range/tenant
- Produces for Member 4: REST + WebSocket APIs for every dashboard (infra, network, security,
  fleet, incidents, recommendations)

### Mock data
Until Member 1's collector is ready, seed PostgreSQL from `sample-data/` fixtures matching the
shared schemas exactly.

### Commands (placeholder)
```bash
cd backend-database
docker compose up db -d
alembic upgrade head
uvicorn app.main:app --reload
```

### Expected results
`/docs` (FastAPI auto-docs) reachable; ingestion endpoint accepts valid allow-listed payloads
and rejects anything with disallowed fields; tenant A's query never returns tenant B's rows.

### Unit tests
Tenant isolation (cross-tenant query attempt returns empty, not an error leaking existence),
idempotent ingestion (duplicate payload ID is a no-op, not a duplicate row), heartbeat →
offline-after-60s state transition.

### Integration requirement
Must expose stable REST/WS contracts early (even backed by mock data) so Member 4 is never
blocked.

---

## Member 3 — AIOps Engine

**Workspace:** `aiops-engine/`
**Branch:** `feature/aiops-engine`

### Responsibilities
- Baseline calculation (moving average / rolling statistics per metric per source)
- Z-score (or equivalent) anomaly detection beyond static thresholds
- Optional stretch: Isolation Forest for multivariate anomaly detection
- Event correlation (grouping related alerts into one incident, identifying likely affected
  components)
- Incident prioritization
- Root-cause hints / likely-cause identification
- Health classification logic (Excellent/Good/Fair/Poor) — configurable thresholds, visible
  reasoning per state change, stale-data downgrade logic, UTC-timestamped history
- Explainable recommendation generation (must surface which signals contributed and why)
- AIOps-specific tests

### Files owned
`aiops-engine/**` (baseline module, anomaly detector, correlation engine, incident/recommendation
generator, health classifier, its own tests)

### Files NOT to modify
`collector-security/**`, `backend-database/**`, `frontend-dashboard/**`

### Dependencies
- Consumes: ingested metadata from Member 2 (or `sample-data/` mocks until that's ready)
- Produces for Member 2 (to persist) and Member 4 (to display): anomaly events, incidents
  (with contributing signals), recommendations (with explanation + confidence), health-state
  records

### Mock data
Use `sample-data/` synthetic time series (normal + injected CPU spike + injected network
latency spike + injected failed-login burst) to develop and test independently of live ingestion.

### Commands (placeholder)
```bash
cd aiops-engine
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
pytest tests/
python run_pipeline.py --input ../sample-data/synthetic_stream.json
```

### Expected results
Given the synthetic stream with an injected CPU spike, the pipeline flags an anomaly with a
confidence score, contributing-signal list, and a human-readable explanation — not just a
threshold breach.

### Unit tests
Baseline correctness on known distributions, anomaly detector sensitivity/false-positive rate
on synthetic normal data, correlation engine merging known-related synthetic alerts into one
incident, health-state transitions matching documented thresholds exactly.

### Integration requirement
Recommendation output must include the specific metadata fields that led to it, traceable back
to Member 2's stored records — this directly maps to the Phase 4 "explainable AIOps, weighted
higher" judging criterion.

---

## Member 4 — Frontend Dashboard

**Workspace:** `frontend-dashboard/`
**Branch:** `feature/frontend-dashboard`

### Responsibilities
- React + TypeScript + Vite + Tailwind application
- Infrastructure dashboard, network dashboard, security dashboard, collector fleet dashboard
- Incident dashboard, recommendation dashboard
- **Egress Proof Panel** UI — the single highest judge-visibility component; must clearly show
  exact payload contents pre-transmission
- Four health-state visual treatment (Excellent/Good/Fair/Poor) with visible reasoning and
  stale-data indication
- Must use mock JSON data (`sample-data/`) until Member 2's real APIs are ready, then swap the
  data layer only — no component rewrites

### Files owned
`frontend-dashboard/**` (all React components, pages, hooks, its own tests)

### Files NOT to modify
`collector-security/**`, `backend-database/**`, `aiops-engine/**`

### Dependencies
- Consumes: Member 2's REST/WS API (or mocks matching the exact same shape in the meantime);
  Member 3's anomaly/incident/recommendation shapes for the relevant dashboards
- Produces: nothing consumed by other members (frontend is a leaf in the dependency graph)

### Mock data
`sample-data/` must contain one fixture file per dashboard, matching the shared schemas
field-for-field, so swapping to live APIs later is a one-line data-source change.

### Commands (placeholder)
```bash
cd frontend-dashboard
npm install
npm run dev
```

### Expected results
All six dashboards render correctly against mock data from minute one; Egress Proof Panel shows
a side-by-side raw-vs-sent comparison for a sample payload.

### Unit tests
Component rendering for each of the four health states; Egress Proof Panel correctly displays a
fixture payload's exact field list.

### Integration requirement
Must not assume any backend field name not present in `SHARED_CONTRACTS.md` — if a dashboard
needs a field that doesn't exist yet, that's raised as a contract-change request, not invented
locally.

---

## Cross-cutting rules for all four members

1. No member edits another member's workspace directory. Cross-cutting schema changes go
   through `shared/` with team review.
2. Every member develops against `sample-data/` mocks first so no one is blocked waiting on
   another's implementation.
3. Git flow: `main` ← `integration` ← `feature/<workspace>`. Merges to `integration` happen at
   the hour-14 integration checkpoint (see `HACKATHON_24H_PLAN.md`, Batch 7); `main` is only
   updated from a tested `integration` branch.
4. Any field, enum, or payload shape not already in `SHARED_CONTRACTS.md` must be added there
   first — never invented silently inside one workspace.
