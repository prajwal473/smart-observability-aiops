# ARCHITECTURE.md

Consistent with `MASTER_PROJECT.md`. This document expands the two-tier architecture into
concrete components, network hops, and scalability decisions, as required for Phase 2 judging
("architecture diagram with trust boundary and every network hop labeled").

---

## 1. Component Diagram

```
┌──────────────────────────── TIER 1: CUSTOMER ENVIRONMENT ─────────────────────────────┐
│                                                                                          │
│  ┌───────────────┐    ┌───────────────┐    ┌───────────────┐    ┌───────────────┐      │
│  │  Telemetry     │    │  Infra agents  │    │  Network       │    │  Security      │      │
│  │  generator     │    │  (CPU/mem/disk)│    │  (SNMP/flow)   │    │  (auth logs)   │      │
│  │  (sim/organizer│    │                │    │                │    │                │      │
│  │  stream)       │    │                │    │                │    │                │      │
│  └───────┬────────┘    └───────┬────────┘    └───────┬────────┘    └───────┬────────┘      │
│          └─────────────────────┴─────────────────────┴─────────────────────┘             │
│                                      │ raw telemetry                                      │
│                                      ▼                                                     │
│                        ┌─────────────────────────┐                                        │
│                        │   LOCAL COLLECTOR CORE   │                                        │
│                        │  1. Normalize            │                                        │
│                        │  2. Allow-list filter     │                                        │
│                        │  3. Secret scrub          │                                        │
│                        │  4. Redact sensitive      │                                        │
│                        │  5. Pseudonymize source ID│                                        │
│                        │  6. Aggregate/summarize   │                                        │
│                        │  7. Local analysis        │                                        │
│                        │  8. Apply data policy     │                                        │
│                        └────────────┬─────────────┘                                        │
│                                      │                                                     │
│              ┌───────────────────────┼────────────────────────┐                          │
│              ▼                       ▼                        ▼                           │
│   ┌──────────────────┐   ┌──────────────────────┐   ┌──────────────────────┐             │
│   │  Local SQLite:     │   │  Local SQLite:        │   │  Egress Proof Panel   │             │
│   │  raw retention     │   │  buffer/retry queue   │   │  (reads buffer, shows │             │
│   │  (secrets live     │   │  (approved metadata   │   │  exact payload before │             │
│   │  ONLY here)        │   │  only, pending send)   │   │  transmission)        │             │
│   └──────────────────┘   └──────────┬───────────┘   └──────────────────────┘             │
│                                      │                                                     │
└──────────────────────────────────────┼─────────────────────────────────────────────────────┘
                                        │
                         ══════ TRUST BOUNDARY (TLS 1.2+, mutual auth) ══════
                                        │
                                        ▼
┌──────────────────────────── TIER 2: CENTRAL SaaS (multi-tenant) ───────────────────────┐
│                                                                                          │
│              ┌──────────────────────────┐                                              │
│              │ Regional ingest endpoint  │  (nearest/assigned region per tenant)         │
│              └────────────┬─────────────┘                                              │
│                            ▼                                                            │
│              ┌──────────────────────────┐                                              │
│              │  FastAPI ingestion layer   │  — validates against allow-list schema,       │
│              │  (auth, schema validate,  │     rejects anything not allow-listed,         │
│              │  tenant_id attach, dedup) │     attaches tenant_id, checks payload_id      │
│              └────────────┬─────────────┘     for idempotent dedup                       │
│                            ▼                                                            │
│              ┌──────────────────────────┐                                              │
│              │  PostgreSQL (tenant-      │  tables scoped by tenant_id on every query      │
│              │  isolated at query layer) │                                              │
│              └────────────┬─────────────┘                                              │
│                            ▼                                                            │
│              ┌──────────────────────────┐                                              │
│              │   AIOps Engine            │  baseline → anomaly → correlate → prioritize   │
│              │   (reads metadata, writes │  → explainable recommendation                  │
│              │   back anomalies/incidents)│                                              │
│              └────────────┬─────────────┘                                              │
│                            ▼                                                            │
│              ┌──────────────────────────┐                                              │
│              │  REST + WebSocket API     │──────► Frontend Dashboard (React)              │
│              └──────────────────────────┘        (infra/network/security/fleet/          │
│                                                     incidents/recommendations/            │
│                                                     Egress Proof Panel view)               │
│                                                                                          │
│              (future) Policy engine → human approval → bounded, reversible action         │
│                        with audit log + rollback — Stage 5, simulated only                │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

## 2. Trust Boundary

The **only** network hop that crosses the customer/SaaS boundary is:
`Local Collector → TLS-authenticated POST/WS → Regional ingest endpoint`

Everything to the left of that hop (generator, agents, collector core, raw SQLite, buffer
SQLite, Egress Proof Panel) runs inside the customer environment and never initiates an
outbound connection carrying raw data. Nothing on the SaaS side can read the raw-retention
SQLite store — there is no reverse channel.

## 3. Data Flow (collect → filter/redact → aggregate → analyze locally → apply data policy → transmit)

1. **Collect** — generator/agents produce raw telemetry events (may include secrets, full log
   lines, real source IPs/hostnames).
2. **Filter** — allow-list validator drops every field not explicitly permitted for the given
   event type (default-deny).
3. **Redact** — remaining fields pass through pattern-based secret scrubbing (API keys, tokens,
   passwords, credit-card-like patterns) and sensitive-value redaction (e.g. full user
   identifiers → pseudonymous IDs).
4. **Aggregate** — repeated low-value events (e.g. per-second CPU samples) are summarized into
   windowed metrics before transmission to cut volume and noise.
5. **Analyze locally** — lightweight local checks (e.g. repeated-auth-failure counting) happen
   before anything is queued, so a security *summary* can be sent without ever sending the raw
   auth log.
6. **Apply data policy** — final check against the allow-list + tenant's transmission policy
   (e.g. "security raw payloads: never transmit") before the payload is written to the buffer
   queue.
7. **Transmit** — buffer queue drains over the authenticated TLS channel; each payload carries a
   unique `payload_id` for idempotent delivery; failures leave the payload in the queue for
   retry with exponential backoff.

## 4. Security Controls

- **Collector authentication:** each collector is registered with the backend and holds a
  per-collector credential (API key or mTLS client cert — see `SECURITY_DESIGN.md`) used on
  every request.
- **Encrypted transport:** TLS 1.2+ for all collector↔SaaS traffic; no plaintext hop exists.
- **Field allow-listing:** enforced twice — once at the collector (nothing non-allow-listed is
  even queued) and once at the SaaS ingestion endpoint (defense in depth: anything that
  shouldn't be there is rejected, not silently dropped-and-logged-as-if-fine).
- **Local retention controls:** raw data has a configurable local-only retention window; it is
  never replicated off-box.
- **Auditable transfer records:** every transmitted payload is recorded in the `egress_audit`
  table/local log with its exact field list and a hash, so the Egress Proof Panel can prove it
  later.

## 5. AIOps Approach

- **Baselines:** rolling mean + standard deviation per (tenant, source, metric) over a
  configurable window.
- **Anomaly detection beyond static thresholds:** z-score deviation from the rolling baseline
  (not a fixed "CPU > 90%" rule); stretch goal: Isolation Forest over multivariate feature
  vectors for subtler deviations.
- **Correlation:** alerts within a configurable time/entity window are grouped into one incident
  if they share a source, a dependency edge, or a time-correlated spike pattern.
- **Prioritization:** incident severity = function of (number of correlated alerts, affected
  service criticality, deviation magnitude).
- **Explainability:** every recommendation stores the specific contributing signals
  (metric, deviation, timestamp) and a human-readable reasoning string — never an opaque label.

## 6. Scalability

- **Many collectors:** each collector is independently authenticated and rate-limited; ingestion
  is stateless per request so horizontal scaling of the FastAPI layer is straightforward.
- **Many tenants:** PostgreSQL with `tenant_id` as a mandatory, indexed column on every
  tenant-scoped table; every query is required to filter by it (enforced via a shared query
  helper, not left to each endpoint to remember).
- **Queueing:** local SQLite buffer per collector (Tier 1); for the SaaS side, ingestion writes
  are kept simple (direct insert) for the 24h scope, with a documented future path to a message
  queue (e.g. Kafka/Redis streams) if ingest volume grows — explicitly out of scope to build now.
- **Storage:** PostgreSQL for all persisted metadata; no raw telemetry ever reaches this store.

## 7. Global-Ready Design

- **Regional ingest:** ingestion endpoint is modeled as per-region (even if only one region is
  actually deployed in the 24h build); tenant config records which region it's assigned to.
- **Tenant data residency:** tenant row carries a `region` field; a stretch goal (not required
  for MVP) is enforcing that queries/joins never cross region without explicit policy approval.
- **UTC timestamps:** every event carries `event_time_utc` plus `source_timezone`; all internal
  processing and storage uses UTC; the frontend converts to the viewer's local time for display.
- **Out-of-order handling:** events are ordered and charted by `event_time_utc`, not by
  `received_at` — a late-arriving event is inserted into history at its correct position and
  recomputes any affected rolling baseline window.
- **Idempotent delivery:** every payload carries a unique `payload_id` (UUID); the ingestion
  endpoint uses it as a dedup key (unique constraint) so retried payloads after an outage never
  create duplicate rows.

## 8. Failure Handling

- **SaaS unreachable:** collector detects failed transmission, leaves payload in the SQLite
  buffer, retries with exponential backoff (e.g. 1s, 2s, 4s... capped), keeps collecting new
  data in parallel.
- **Backlog delivery:** on reconnect, buffered payloads drain in `event_time_utc` order; each
  carries its original `payload_id` so the ingestion dedup guarantees zero duplicates.
- **Collector offline detection:** backend tracks `last_heartbeat_at` per collector; a
  background check flags a collector Poor/offline once `now - last_heartbeat_at > 60s`.

## 9. What Is Explicitly Deferred (per PDF scope)

- Real policy-controlled Autonomous Ops execution (Stage 5) — simulated only.
- Cross-region data replication controls beyond the `region` field — documented as a future
  policy-approval gate, not built.
- Production-grade message queue for ingestion — direct insert is sufficient for a 24h demo
  scale; documented as a scaling note, not implemented.
