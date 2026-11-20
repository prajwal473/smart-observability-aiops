# DATABASE_SCHEMA.md

PostgreSQL schema for the central SaaS platform (owned by Member 2). SQLite schemas for the
local collector's raw store / buffer / egress audit are documented separately in
`collector-security/` once implementation files are generated (Batch "implementation
inventory"), since they're intentionally simpler and local-only.

Every tenant-scoped table below carries `tenant_id` as a mandatory, indexed, non-null column,
per `SECURITY_DESIGN.md` §7. All timestamp columns are `TIMESTAMPTZ`, stored in UTC.

---

## `tenants`

| Column | Type | Notes |
|---|---|---|
| `tenant_id` | `TEXT PRIMARY KEY` | e.g. `tenant_acme` |
| `name` | `TEXT NOT NULL` | display name |
| `region` | `TEXT NOT NULL` | data-residency region, e.g. `ap-south-1` |
| `created_at_utc` | `TIMESTAMPTZ NOT NULL DEFAULT now()` | |

## `collectors`

| Column | Type | Notes |
|---|---|---|
| `collector_id` | `TEXT PRIMARY KEY` | |
| `tenant_id` | `TEXT NOT NULL REFERENCES tenants(tenant_id)` | indexed |
| `api_key_hash` | `TEXT NOT NULL` | never store the raw key |
| `collector_version` | `TEXT` | last-reported version |
| `last_seen_utc` | `TIMESTAMPTZ` | updated on every heartbeat |
| `config_status` | `TEXT` | `valid` / `pending_update` / `invalid` |
| `resource_cpu_pct` | `NUMERIC` | last-reported |
| `resource_memory_mb` | `NUMERIC` | last-reported |
| `created_at_utc` | `TIMESTAMPTZ NOT NULL DEFAULT now()` | |

Index: `(tenant_id)`.

## `telemetry_metadata`

Generic envelope table — one row per ingested payload, regardless of `event_type`. The
type-specific fields live in `data` as `JSONB` (still only ever allow-listed content).

| Column | Type | Notes |
|---|---|---|
| `payload_id` | `UUID PRIMARY KEY` | idempotency key — unique constraint does the dedup work |
| `tenant_id` | `TEXT NOT NULL REFERENCES tenants(tenant_id)` | indexed |
| `collector_id` | `TEXT NOT NULL REFERENCES collectors(collector_id)` | |
| `source_id` | `TEXT NOT NULL` | pseudonymous, indexed |
| `event_type` | `TEXT NOT NULL` | `infrastructure_metrics` / `network_metrics` / `security_events` / `collector_heartbeat` |
| `event_time_utc` | `TIMESTAMPTZ NOT NULL` | indexed — this is what charts/ordering use, never `received_at_utc` |
| `source_timezone` | `TEXT` | IANA string |
| `received_at_utc` | `TIMESTAMPTZ NOT NULL DEFAULT now()` | |
| `data` | `JSONB NOT NULL` | type-specific allow-listed fields |

Indexes: `(tenant_id, event_time_utc)`, `(tenant_id, source_id, event_type, event_time_utc)`.
Unique constraint: `(payload_id)` — this is the idempotent-delivery guarantee at the DB level.

> Rationale for a single generic table over four separate ones: for a 24h build this avoids
> four near-identical tables and four near-identical ingestion code paths, while `JSONB` still
> lets AIOps and dashboard queries filter on specific metric fields efficiently with a GIN index
> if needed. Documented as a deliberate simplification, not an oversight.

## `infrastructure_metrics` (materialized convenience view, optional)

A view over `telemetry_metadata WHERE event_type = 'infrastructure_metrics'` exposing
`data->>'cpu_pct'` etc. as real columns, to keep AIOps baseline queries simple. Not a separate
table — avoids data duplication/drift.

## `anomaly_events`

| Column | Type | Notes |
|---|---|---|
| `anomaly_id` | `TEXT PRIMARY KEY` | |
| `tenant_id` | `TEXT NOT NULL REFERENCES tenants(tenant_id)` | indexed |
| `source_id` | `TEXT NOT NULL` | |
| `metric` | `TEXT NOT NULL` | |
| `observed_value` | `NUMERIC NOT NULL` | |
| `baseline_mean` | `NUMERIC NOT NULL` | |
| `baseline_std` | `NUMERIC NOT NULL` | |
| `z_score` | `NUMERIC NOT NULL` | |
| `event_time_utc` | `TIMESTAMPTZ NOT NULL` | |
| `detected_at_utc` | `TIMESTAMPTZ NOT NULL DEFAULT now()` | used for the ≤15s alert-latency target |

Index: `(tenant_id, source_id, detected_at_utc)`.

## `incidents`

| Column | Type | Notes |
|---|---|---|
| `incident_id` | `TEXT PRIMARY KEY` | |
| `tenant_id` | `TEXT NOT NULL REFERENCES tenants(tenant_id)` | indexed |
| `title` | `TEXT NOT NULL` | |
| `severity` | `TEXT NOT NULL` | `low`/`medium`/`high`/`critical` |
| `status` | `TEXT NOT NULL DEFAULT 'open'` | `open`/`acknowledged`/`resolved` |
| `affected_source_ids` | `TEXT[]` | |
| `opened_at_utc` | `TIMESTAMPTZ NOT NULL DEFAULT now()` | |
| `updated_at_utc` | `TIMESTAMPTZ NOT NULL DEFAULT now()` | |

## `incident_anomalies` (join table)

| Column | Type | Notes |
|---|---|---|
| `incident_id` | `TEXT NOT NULL REFERENCES incidents(incident_id)` | |
| `anomaly_id` | `TEXT NOT NULL REFERENCES anomaly_events(anomaly_id)` | |

Primary key: `(incident_id, anomaly_id)`. This is how correlation ("several alerts relate to
one incident") is represented — many anomalies can map to one incident.

## `recommendations`

| Column | Type | Notes |
|---|---|---|
| `recommendation_id` | `TEXT PRIMARY KEY` | |
| `tenant_id` | `TEXT NOT NULL REFERENCES tenants(tenant_id)` | indexed |
| `incident_id` | `TEXT NOT NULL REFERENCES incidents(incident_id)` | |
| `text` | `TEXT NOT NULL` | |
| `confidence` | `NUMERIC` | 0.0–1.0 |
| `contributing_signals` | `JSONB NOT NULL` | array of `{anomaly_id, metric, z_score}` |
| `generated_at_utc` | `TIMESTAMPTZ NOT NULL DEFAULT now()` | |

## `egress_audit`

Mirrors the collector-local egress audit, replicated to SaaS **only as metadata about the
transfer itself** (field lists, hashes — never payload content beyond what's already in
`telemetry_metadata`), so the Egress Proof Panel can be served from a single API without the
frontend needing to reach into the collector directly.

| Column | Type | Notes |
|---|---|---|
| `audit_id` | `TEXT PRIMARY KEY` | |
| `collector_id` | `TEXT NOT NULL REFERENCES collectors(collector_id)` | indexed |
| `payload_id` | `UUID NOT NULL REFERENCES telemetry_metadata(payload_id)` | |
| `fields_sent` | `TEXT[] NOT NULL` | |
| `fields_redacted` | `TEXT[]` | |
| `content_hash` | `TEXT NOT NULL` | |
| `queued_at_utc` | `TIMESTAMPTZ NOT NULL` | |
| `sent_at_utc` | `TIMESTAMPTZ NOT NULL` | |

## `authentication_audit`

| Column | Type | Notes |
|---|---|---|
| `attempt_id` | `BIGSERIAL PRIMARY KEY` | |
| `collector_id` | `TEXT` | nullable — may fail before identity is known |
| `result` | `TEXT NOT NULL` | `success`/`failure` |
| `attempted_at_utc` | `TIMESTAMPTZ NOT NULL DEFAULT now()` | |

Never stores the credential value itself, per `SECURITY_DESIGN.md` §1.

## `collector_heartbeats`

| Column | Type | Notes |
|---|---|---|
| `heartbeat_id` | `BIGSERIAL PRIMARY KEY` | |
| `collector_id` | `TEXT NOT NULL REFERENCES collectors(collector_id)` | indexed |
| `received_at_utc` | `TIMESTAMPTZ NOT NULL DEFAULT now()` | used for the ≤60s offline-detection target |
| `resource_cpu_pct` | `NUMERIC` | |
| `resource_memory_mb` | `NUMERIC` | |

## `delivery_records`

Tracks every `payload_id` the ingestion endpoint has seen, independent of `telemetry_metadata`,
specifically to answer "sent IDs vs. received IDs" for the zero-loss/zero-duplicate performance
target without needing to scan the main table.

| Column | Type | Notes |
|---|---|---|
| `payload_id` | `UUID PRIMARY KEY` | |
| `tenant_id` | `TEXT NOT NULL` | |
| `first_received_at_utc` | `TIMESTAMPTZ NOT NULL DEFAULT now()` | |
| `duplicate_attempts` | `INTEGER NOT NULL DEFAULT 0` | incremented, never creates a new row |

## `health_state_history`

| Column | Type | Notes |
|---|---|---|
| `history_id` | `BIGSERIAL PRIMARY KEY` | |
| `tenant_id` | `TEXT NOT NULL` | indexed |
| `entity_id` | `TEXT NOT NULL` | source_id, collector_id, or `tenant_fleet` |
| `entity_type` | `TEXT NOT NULL` | `source`/`collector`/`tenant_fleet` |
| `from_state` | `TEXT` | nullable for the first-ever record |
| `to_state` | `TEXT NOT NULL` | `Excellent`/`Good`/`Fair`/`Poor` |
| `reason` | `TEXT NOT NULL` | human-readable, shown in UI |
| `changed_at_utc` | `TIMESTAMPTZ NOT NULL DEFAULT now()` | |

Index: `(tenant_id, entity_id, changed_at_utc)` — powers the "state history" view.

---

## Relationships Summary

```
tenants 1───* collectors 1───* telemetry_metadata
                    │                    │
                    │                    └──* anomaly_events ──* incident_anomalies *── incidents 1──* recommendations
                    │
                    ├──* collector_heartbeats
                    └──* egress_audit ──1 telemetry_metadata (payload_id)
```

## Constraints Enforced at the DB Level (not just app code)

- `telemetry_metadata.payload_id` UNIQUE → idempotent delivery guarantee survives even a buggy
  app-layer check.
- All `tenant_id` foreign keys → referential integrity prevents orphaned rows pointing at a
  nonexistent tenant.
- `incidents.status` and `health_state_history.to_state` should be `CHECK` constraints or an
  enum type, not free text, to prevent an invalid state from ever being stored.

## Migrations

Managed via Alembic (SQLAlchemy). First migration creates all tables above in dependency order
(`tenants` → `collectors` → everything else). No destructive migrations during the hackathon —
only additive changes, to avoid losing demo data mid-event.
