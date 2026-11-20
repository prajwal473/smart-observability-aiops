# API_DOCUMENTATION.md

Owned by Member 2 (backend-database), consumed by Member 1 (collector, for ingestion/heartbeat)
and Member 4 (frontend, for everything else). All shapes referenced here are defined in full in
`SHARED_CONTRACTS.md` — this file only adds HTTP method, path, auth requirement, and
request/response wiring.

Base URL (local dev): `http://localhost:8000`
All endpoints except `/health` require the `Authorization: Bearer <token>` header.

---

## Collector-Facing Endpoints

### `POST /v1/collectors/register`
Registers a new collector for a tenant. Admin-auth only (not the collector's own token — this
is a one-time bootstrap call).

Request:
```json
{ "tenant_id": "tenant_acme", "collector_label": "coll_bengaluru_01" }
```
Response (`200`):
```json
{ "status": "ok", "data": { "collector_id": "coll_bengaluru_01", "api_key": "sk_live_..." } }
```
The `api_key` is shown exactly once; only its hash is stored server-side.

### `POST /v1/ingest`
Primary ingestion endpoint. Collector-auth required. Accepts one Telemetry Metadata envelope
(Section 1 of `SHARED_CONTRACTS.md`).

Request: a single envelope object (see contracts §1–5).
Response (`200`, new payload):
```json
{ "status": "ok", "data": { "payload_id": "a1b2c3d4-0001-4000-8000-000000000001", "accepted": true } }
```
Response (`200`, duplicate `payload_id` — idempotent no-op):
```json
{ "status": "ok", "data": { "payload_id": "a1b2c3d4-0001-4000-8000-000000000001", "accepted": false, "reason": "duplicate" } }
```
Response (`422`, schema violation — Error Response shape, `SCHEMA_VALIDATION_FAILED`).

### `POST /v1/ingest/batch`
Same as above but accepts an array of envelopes, for backlog delivery after a reconnect. Each
element is validated and deduped independently; response is an array of the same per-item
result shape as `/v1/ingest`.

### `POST /v1/collectors/{collector_id}/heartbeat`
Collector-auth required; `collector_id` must match the authenticated collector.

Request: Collector Heartbeat `data` object (contracts §5).
Response (`200`):
```json
{ "status": "ok", "data": { "received_at_utc": "2026-11-20T10:15:05Z" } }
```

---

## Dashboard-Facing Endpoints (Member 4 consumes these)

### `GET /v1/collectors`
Tenant-scoped (from auth token). Returns Collector Status objects (contracts §6), one per
collector.

### `GET /v1/metrics/infrastructure?source_id=&from=&to=`
Returns a time-ordered array of Infrastructure Metrics (contracts §2) with their envelope
fields, filtered by `event_time_utc` range.

### `GET /v1/metrics/network?source_id=&from=&to=`
Same shape pattern, Network Metrics (contracts §3).

### `GET /v1/security/events?source_id=&from=&to=`
Same shape pattern, Security Events (contracts §4).

### `GET /v1/incidents?status=&from=&to=`
Returns Incident objects (contracts §7). `status` filter optional (`open`/`acknowledged`/`resolved`).

### `GET /v1/incidents/{incident_id}`
Returns one Incident plus its nested Anomalies (contracts §8) and Recommendation (contracts §9)
fully expanded, for the incident detail view.

### `GET /v1/recommendations?incident_id=`
Returns Recommendation objects (contracts §9).

### `GET /v1/health-states?entity_type=&entity_id=`
Returns the current Health State (contracts §10) plus `GET
/v1/health-states/{entity_id}/history` for the timestamped transition history used by the "why
did this change" view.

### `GET /v1/egress-audit?collector_id=&from=&to=`
Returns Egress Audit records (contracts §11) — this backs the Egress Proof Panel UI directly.

### `GET /v1/egress-audit/{payload_id}`
Returns one Egress Audit record plus the matching stored metadata payload, for the
side-by-side raw-vs-sent view.

---

## WebSocket

### `WS /v1/stream?token=<auth>`
On connect, server pushes messages matching contracts §13 (`metric_update`,
`health_state_change`, `incident_update`, `recommendation_update`, `collector_status_change`) as
they occur, scoped to the authenticated tenant only. Used by the frontend to avoid polling for
the ≤10s dashboard-latency target.

---

## Health Check

### `GET /health`
No auth required. Returns `{ "status": "ok" }` — used by Docker Compose healthchecks and the
24h-plan's integration checkpoint smoke test.

---

## Auth Summary

| Caller | Header | Scope |
|---|---|---|
| Collector | `Authorization: Bearer <collector api_key>` | Its own `collector_id`/`tenant_id` only |
| Dashboard user | `Authorization: Bearer <session token>` | Their own `tenant_id` only |
| Admin bootstrap | `Authorization: Bearer <admin token>` | Registration only |

Every handler resolves `tenant_id` from the token server-side; it is never read from a query
param or request body, per `SECURITY_DESIGN.md` §7.

## Error Codes Reference

See `SHARED_CONTRACTS.md` §14 for the Error Response shape. Used across all endpoints above:
`SCHEMA_VALIDATION_FAILED` (422), `UNAUTHORIZED` (401), `TENANT_MISMATCH` (403),
`DUPLICATE_PAYLOAD_ID` (200, not an error — see `/v1/ingest` idempotent-no-op case above),
`NOT_FOUND` (404).
