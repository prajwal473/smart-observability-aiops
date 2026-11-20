# INTEGRATION_CHECKLIST.md — Integration Checklist

Use during hours 14–21. Mark each item `[x]` only after it has actually been run and observed. Record the date/time and tester initials in the "Evidence" column. Do not tick an item based on assumption.

Legend: **P0** = must work for demo, **P1** = important, **P2** = nice to have.

---

## A. Pre-Integration Gate (each member confirms before merging into `integration`)

| # | Item | Owner | Pri | Done | Evidence |
|---|---|---|---|---|---|
| A1 | Module unit tests pass locally | Each | P0 | [ ] | |
| A2 | Module uses field names exactly from `SHARED_CONTRACTS.md` | Each | P0 | [ ] | |
| A3 | No secrets or real credentials committed | Each | P0 | [ ] | |
| A4 | Only files in own workspace modified | Each | P0 | [ ] | |
| A5 | `README` run command for the module works on a fresh clone | Each | P1 | [ ] | |
| A6 | Branch rebased/merged with latest `main` | Each | P1 | [ ] | |

## B. Contract Compatibility

| # | Item | Owner | Pri | Done | Evidence |
|---|---|---|---|---|---|
| B1 | Collector payload validates against backend Pydantic model | COL + BE | P0 | [ ] | |
| B2 | Heartbeat payload accepted by `/heartbeat` | COL + BE | P0 | [ ] | |
| B3 | `payload_id` unique per payload and used for idempotency | COL + BE | P0 | [ ] | |
| B4 | Timestamps are UTC ISO-8601 with source timezone field present | COL + BE | P0 | [ ] | |
| B5 | AI engine input shape matches what backend passes | BE + AI | P0 | [ ] | |
| B6 | AI outputs (anomaly, incident, recommendation, health) match contract | AI + BE | P0 | [ ] | |
| B7 | REST responses match frontend TypeScript types | BE + FE | P0 | [ ] | |
| B8 | WebSocket message types match frontend handlers | BE + FE | P1 | [ ] | |
| B9 | Error responses follow the shared error schema | BE + FE | P1 | [ ] | |

## C. Collector → Backend

| # | Item | Pri | Done | Evidence |
|---|---|---|---|---|
| C1 | Collector registers / authenticates with its token | P0 | [ ] | |
| C2 | Invalid token rejected (401/403) and logged | P0 | [ ] | |
| C3 | Encrypted transport configured (HTTPS/TLS, or documented local-demo exception) | P0 | [ ] | |
| C4 | Only allow-listed fields reach backend (inspect stored row) | P0 | [ ] | |
| C5 | Seeded secrets (password, token, API key, email, IP) absent from backend DB and logs | P0 | [ ] | |
| C6 | Pseudonymous source ID is stable per source and not reversible from payload | P1 | [ ] | |
| C7 | Egress audit entry written for every sent payload | P0 | [ ] | |
| C8 | Payload content in audit equals what backend received | P0 | [ ] | |

## D. Backend Behaviour

| # | Item | Pri | Done | Evidence |
|---|---|---|---|---|
| D1 | Tenant A token cannot read tenant B data (REST) | P0 | [ ] | |
| D2 | Tenant A cannot subscribe to tenant B WebSocket events | P0 | [ ] | |
| D3 | Duplicate `payload_id` returns success without creating a second row | P0 | [ ] | |
| D4 | Out-of-order event stored and ordered by event time | P1 | [ ] | |
| D5 | Offline detection flags collector within 60 s of last heartbeat (measured) | P0 | [ ] | |
| D6 | Collector returns to online after new heartbeat | P1 | [ ] | |
| D7 | Authentication audit rows written | P1 | [ ] | |
| D8 | Backend logs contain no raw telemetry or credentials | P0 | [ ] | |
| D9 | Migrations apply on empty database | P0 | [ ] | |

## E. AIOps Pipeline

| # | Item | Pri | Done | Evidence |
|---|---|---|---|---|
| E1 | Baseline computed per tenant/collector/metric | P0 | [ ] | |
| E2 | CPU spike produces anomaly with reason text | P0 | [ ] | |
| E3 | Memory spike produces anomaly | P0 | [ ] | |
| E4 | Latency spike produces anomaly | P0 | [ ] | |
| E5 | Packet loss produces anomaly | P0 | [ ] | |
| E6 | Repeated failed logins produce security anomaly | P0 | [ ] | |
| E7 | Related anomalies correlated into one incident | P0 | [ ] | |
| E8 | Incident has priority and likely cause | P0 | [ ] | |
| E9 | Recommendation includes explanation (why) and evidence | P0 | [ ] | |
| E10 | Health state is one of Excellent/Good/Fair/Poor with reasons | P0 | [ ] | |
| E11 | Stale data yields documented stale handling, not a false "Excellent" | P1 | [ ] | |
| E12 | Threshold breach → alert time measured (target 15 s) | P0 | [ ] | |

## F. Frontend

| # | Item | Pri | Done | Evidence |
|---|---|---|---|---|
| F1 | Infrastructure dashboard shows live CPU/memory/disk/service data | P0 | [ ] | |
| F2 | Network dashboard shows bandwidth/latency/packet loss | P0 | [ ] | |
| F3 | Security dashboard shows failed-login events | P0 | [ ] | |
| F4 | Fleet dashboard shows online/offline, last seen, version, resources, config status | P0 | [ ] | |
| F5 | Incident and Recommendation pages show real incidents with explanations | P0 | [ ] | |
| F6 | Egress Proof Panel shows exact payload before transmission and after-redaction content | P0 | [ ] | |
| F7 | Health state and reason visible on dashboard | P0 | [ ] | |
| F8 | UI handles empty, loading, error and stale states | P1 | [ ] | |
| F9 | Collection-to-dashboard latency measured (target 10 s p95) | P0 | [ ] | |
| F10 | `USE_MOCK` fallback works if backend is down | P1 | [ ] | |

## G. Reliability / Outage Drill

Run in this order and record outcomes:

| # | Step | Expected | Done | Evidence |
|---|---|---|---|---|
| G1 | Stop backend | Collector keeps collecting; records queue in SQLite | [ ] | |
| G2 | Wait through ≥3 retry attempts | Backoff intervals grow; retry events logged | [ ] | |
| G3 | Count queued records | Count recorded (N) | [ ] | |
| G4 | Restart backend | Backlog delivered automatically | [ ] | |
| G5 | Compare delivered vs generated | Zero lost | [ ] | |
| G6 | Check for duplicate `payload_id` in DB | Zero duplicates | [ ] | |
| G7 | Dashboard shows backlog data with correct timestamps | Correct order | [ ] | |
| G8 | Kill collector process | Offline flag ≤ 60 s | [ ] | |
| G9 | Restart collector | Resumes without data loss | [ ] | |

## H. Deployment

| # | Item | Pri | Done | Evidence |
|---|---|---|---|---|
| H1 | `docker compose up` from fresh clone starts all services | P0 | [ ] | |
| H2 | `.env.example` covers all variables; no real secrets inside | P0 | [ ] | |
| H3 | Seed/demo script creates tenants, collectors, tokens | P1 | [ ] | |
| H4 | Non-Docker fallback run steps verified | P1 | [ ] | |
| H5 | Clean-machine run performed by someone other than the author | P1 | [ ] | |

## I. Defect Log

| ID | Date/time | Found by | Module | Description | Severity | Owner | Status |
|---|---|---|---|---|---|---|---|
| | | | | | | | |

## J. Sign-off

| Gate | Condition | Signed by | Time |
|---|---|---|---|
| G1 | All A items done | | |
| G2 | B, C, D1–D3, E2, E7–E9, F1, F5 done | | |
| G3 | All P0 items done or documented as known limitation | | |
