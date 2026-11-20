# RELIABILITY_DESIGN.md — Buffering, Retry, Idempotency and Offline Detection

Project: Smart Observability and AIOps Platform (CICADA 2026)
Owners: Member 1 (collector side), Member 2 (backend side).

> Status: DRAFT. This is a design, not evidence. No guarantee below has been tested yet.
> "Zero lost, zero duplicates" and the timing targets are **goals to measure**. Record real numbers in `FINAL_QUALITY_REPORT.md`.
> Field names follow `SHARED_CONTRACTS.md`. If they disagree, the contracts win.

---

## 1. Goals (from the project brief)

| Requirement | Target | Mechanism in this design |
|---|---|---|
| Local buffering | Collection continues during an outage | SQLite queue on the collector |
| Exponential backoff | Retries slow down, do not hammer | Backoff with cap and jitter |
| Retry and resume | Delivery continues after restart or recovery | Durable queue, `next_attempt_at` |
| Duplicate prevention | Retries never create second rows | Stable `payload_id`, unique constraint |
| Backlog delivery | Zero lost, zero duplicates after outage | Ack-then-delete, idempotent ingest |
| Collector offline detection | Within 60 s of last heartbeat | Heartbeat timestamps plus periodic check |
| SaaS outage handling | Collector keeps working | Local-first design |
| Out-of-order events | Charts stay correct | Ordering by `event_time_utc` |
| Collection to dashboard | p95 within 10 s | Measured with timestamps |
| Threshold breach to alert | within 15 s | Measured with timestamps |

## 2. Delivery Guarantee in One Sentence

The collector delivers **at least once** (it retries until it gets an acknowledgement), and the backend stores **at most once per `payload_id`**. Together this gives **effectively exactly-once storage**, provided the queue does not overflow (section 7).

## 3. Collector Side (Member 1)

### 3.1 Data path

```
collect -> normalize -> allow-list -> redact -> pseudonymise -> assign payload_id
   -> write egress audit row -> INSERT into queue (SQLite) -> sender loop -> HTTPS POST /v1/ingest
```

The payload is written to the queue **before** any send is attempted. A crash at any later point cannot lose it.

### 3.2 Payload ID rules

- `payload_id` is a UUID generated **once, when the payload is enqueued**.
- It never changes across retries, restarts or replays. A retry re-sends the same bytes with the same ID.
- The egress audit row stores the same `payload_id` and a `content_hash`, so the Egress Proof Panel can show that what was sent equals what was audited.

### 3.3 Local SQLite schema (proposal)

File: `COLLECTOR_SQLITE_PATH`. SQLite opened with `journal_mode=WAL` and `synchronous=NORMAL` (or `FULL` if the demo can afford it).

```sql
CREATE TABLE IF NOT EXISTS outbound_queue (
  payload_id        TEXT PRIMARY KEY,
  event_type        TEXT NOT NULL,
  event_time_utc    TEXT NOT NULL,
  body_json         TEXT NOT NULL,          -- exact bytes to send
  content_hash      TEXT NOT NULL,
  status            TEXT NOT NULL DEFAULT 'pending',  -- pending | in_flight | delivered
  attempts          INTEGER NOT NULL DEFAULT 0,
  next_attempt_utc  TEXT NOT NULL,
  last_error        TEXT,
  queued_at_utc     TEXT NOT NULL,
  delivered_at_utc  TEXT
);
CREATE INDEX IF NOT EXISTS ix_queue_pending
  ON outbound_queue (status, event_time_utc);

CREATE TABLE IF NOT EXISTS egress_audit (
  audit_id          TEXT PRIMARY KEY,
  payload_id        TEXT NOT NULL,
  fields_sent       TEXT NOT NULL,          -- JSON array
  fields_redacted   TEXT NOT NULL,          -- JSON array
  content_hash      TEXT NOT NULL,
  queued_at_utc     TEXT NOT NULL,
  sent_at_utc       TEXT
);
```

These tables, and the raw store, stay on the customer side and are never uploaded.

### 3.4 Sender loop

1. Select up to `batch_size` rows where `status = 'pending'` and `next_attempt_utc <= now`, ordered by `event_time_utc` ascending.
2. Mark them `in_flight`, increment `attempts`.
3. POST each (or a batch) over HTTPS with the collector token.
4. On **2xx** (including the "duplicate, already stored" 200 response): mark `delivered`, set `delivered_at_utc`, update the audit row `sent_at_utc`. Delivered rows are pruned after the local retention period.
5. On **network error, timeout, 5xx or 429**: set `status = 'pending'`, store `last_error`, compute the next delay (section 3.5), set `next_attempt_utc`.
6. On **400/422 (schema rejected)**: do **not** retry forever. Mark `status = 'rejected'` (add to the allowed values), log `ingest.rejected`, keep for inspection. A permanently bad payload must not block the queue.
7. On **401/403**: pause sending, log `auth.failed`, retry with a long delay. Do not discard payloads.
8. On startup, rows left `in_flight` after a crash are reset to `pending`. This is safe because of idempotent ingest.

### 3.5 Backoff

```
delay = min(RETRY_MAX_DELAY_SECONDS, RETRY_INITIAL_DELAY_SECONDS * RETRY_BACKOFF_FACTOR ** (consecutive_failures - 1))
delay = delay + uniform(0, RETRY_JITTER_SECONDS)
```

Defaults from `.env.example`: initial 1 s, factor 2, max 60 s, jitter 0.5 s. Sequence: about 1, 2, 4, 8, 16, 32, 60, 60 seconds. `consecutive_failures` is tracked for the connection as a whole and resets to zero after any success, so recovery is not slowed by old failures. After recovery the sender drains the backlog at full speed (bounded by `batch_size`), not at backoff speed.

### 3.6 Collection during an outage

Collection, redaction and local analysis do not depend on the network. The queue simply grows. The collector reports `queue_depth` locally (CLI `status`) and in the heartbeat when it can send one.

### 3.7 Heartbeats are not backlogged

A heartbeat describes "now". The collector sends heartbeats on their own timer and does **not** queue old ones for replay: delivering 5 minutes of stale heartbeats after recovery would hide the outage. After recovery the first new heartbeat reports `last_successful_send_utc`, and the queue backlog is data only.

### 3.8 Draining order

Oldest `event_time_utc` first. This keeps history close to chronological and lets the backend's baseline see data in order. The backend must still handle out-of-order data (section 5.3).

## 4. Transport

- HTTPS/TLS between collector and SaaS. For a local demo over plain HTTP set `SAAS_VERIFY_TLS=false` and say so openly; do not present that as encrypted communication.
- Per-request timeout (proposal: connect 3 s, read 10 s) so a hung connection does not stall the loop.
- Bearer collector token in the `Authorization` header; never logged (see `LOGGING_ARCHITECTURE.md`).

## 5. Backend Side (Member 2)

### 5.1 Idempotent ingest

1. Authenticate the collector token, resolve the tenant from the token (never from the body).
2. Validate the payload against the contract; reject unknown fields with `SCHEMA_VALIDATION_FAILED`.
3. In **one database transaction**: insert into `telemetry_metadata` with `payload_id` as `PRIMARY KEY`/`UNIQUE`.
   - If the insert succeeds: store metrics, write a `delivery_records` row, return `200` with `status: ok`.
   - If the insert violates the unique constraint: increment `duplicate_attempts`, return `200` with the documented duplicate response (`DUPLICATE_PAYLOAD_ID` as a no-op, per `API_DOCUMENTATION.md`). Do **not** return an error, so the collector marks it delivered and stops retrying.
4. The database constraint is the guarantee. An application-level "already seen" check is only an optimisation.

A payload the server stored but whose acknowledgement was lost is the classic case: the collector retries, the backend answers "duplicate, ok", and the collector marks it delivered. No loss, no second row.

### 5.2 Run AIOps after commit

The AIOps call happens after the ingest transaction commits. If AIOps fails, the telemetry is still stored, an `error.unhandled` is logged, and a reprocess job can pick it up. AIOps failure must never cause a collector retry.

### 5.3 Out-of-order handling

- Rows are keyed and queried by `event_time_utc`, not arrival time.
- Charts and baselines are built from `event_time_utc` order.
- Late data (older than the newest stored point) is flagged `late_arrival` for the AIOps engine and may trigger a baseline recompute for the affected window (`AIOPS_DESIGN.md` §8).
- Alerts older than the freshness limit are stored but not pushed as live alerts.
- Accepted lateness is bounded by `OUT_OF_ORDER_TOLERANCE_SECONDS`; older data is still stored but marked as backfill.

### 5.4 Offline detection

- Each heartbeat updates `last_heartbeat_at` for the collector (`collector_heartbeats`, and a current-status row).
- A background task runs every `OFFLINE_CHECK_INTERVAL_SECONDS` (5 s) and computes `now - last_heartbeat_at` for every collector.
- Over `stale_after` (15 s): collector marked stale (health `Fair`). Over `offline_after` (45 s): marked offline (health `Poor`), `collector.offline_detected` logged, `collector_status_change` pushed over WebSocket.
- Worst-case detection time = offline limit + check interval = about 50 s, which sits inside the 60 s target with a margin of about 10 s. **To be measured.**
- When a new heartbeat arrives, the collector returns to `online` and the transition is recorded.
- Use the server's own clock for `last_heartbeat_at` (receipt time), not the collector's clock, so a skewed collector clock cannot fake being online.

### 5.5 SaaS-side failure behaviour

| Failure | Behaviour |
|---|---|
| Database down | Ingest returns 503; collectors back off and keep buffering |
| Backend restarting | Same as above; collectors resume automatically |
| Overload | 429 or 503 with retry; collectors back off with jitter |
| Single bad payload | 4xx for that payload only; others unaffected |

Return 5xx (retryable) for infrastructure faults and 4xx only for permanent problems with the payload itself. Mixing them up either loses data or causes endless retries.

## 6. Timing Budget (what must be measured)

| Segment | Measured how |
|---|---|
| Collect to enqueue | `telemetry.collected` to `egress.payload_recorded` log times |
| Enqueue to send | `queued_at_utc` to `sent_at_utc` |
| Send to stored | `sent_at_utc` to `ingest.accepted` |
| Stored to dashboard | `ingest.accepted` to frontend render timestamp |
| Breach to alert | `telemetry.collected` to `anomaly.detected` to alert shown |

Collection-to-dashboard p95 target is 10 s. With a 5 s collect interval and 5 s send interval, **the interval settings alone can use the whole budget**. Options: send immediately on enqueue instead of on a fixed timer, or shorten intervals. Decide by measurement. Intervals are configurable in `.env.example` for this reason.

Clock note: all timestamps are UTC, but collector and backend clocks can drift. On one demo laptop this is not an issue; across machines, note the clock source in the report.

## 7. Queue Limits and Honest Limits of "Zero Loss"

- Zero loss holds **only while the queue has room and the disk survives**.
- Cap: `COLLECTOR_QUEUE_MAX_ROWS` or `COLLECTOR_QUEUE_MAX_MB` (proposal: 100 MB, roughly hours of data at demo rates; to be calculated from payload size).
- If the cap is reached: drop the **oldest low-priority metric payloads first**, never audit rows, and log `buffer.overflow_dropped` with the count; the next heartbeat reports `dropped_count`. This must be visible, never silent.
- Security events are higher priority than routine metrics when dropping.
- Delivered rows are pruned after `COLLECTOR_LOCAL_RETENTION_HOURS`.
- A lost collector disk loses the queue. State this as a known limit.

## 8. Edge Cases

| Case | Handling |
|---|---|
| Collector crashes after send, before marking delivered | Restart resets `in_flight` to `pending`; backend returns duplicate ok; no second row |
| Server stored it, ack lost | Same as above |
| Two collector processes using one queue | Not supported; single writer lock on the SQLite file |
| Collector clock jumps back | `event_time_utc` can be older than the previous one; handled as out-of-order |
| Very old backlog (hours) | Stored with historical timestamps; incidents get historical `opened_at_utc`; no live alerts for stale events |
| Replay by operator (`replay --last 20`) | Same `payload_id`s, so the backend reports duplicates and stores nothing new |
| Token revoked during outage | Sending pauses on 401/403; queue is kept; resumes after a new token is configured |

## 9. Outage Drill (to run in hours 18 to 21)

Matches `INTEGRATION_CHECKLIST.md` section G and `scripts/outage_drill.sh`.

1. Record count in the collector `outbound_queue` (delivered) and the backend row count for the collector.
2. Stop the backend for a fixed time (60 to 120 s).
3. Confirm the collector keeps collecting, retry intervals grow, queue depth rises (record N).
4. Start the backend. Confirm the queue drains without operator action.
5. Compare: generated payloads (collector `delivered` plus any `pending`) against stored rows (backend). Record lost = generated minus stored.
6. Query duplicate `payload_id` values in the backend. Record the count.
7. Kill the collector; time how long until it shows offline. Record the real number.
8. Put every number in `FINAL_QUALITY_REPORT.md`, whatever it is.

## 10. Configuration Summary

| Variable | Default | Used by |
|---|---|---|
| `HEARTBEAT_INTERVAL_SECONDS` | 5 | Collector |
| `OFFLINE_THRESHOLD_SECONDS` | 45 | Backend offline task |
| `OFFLINE_CHECK_INTERVAL_SECONDS` | 5 | Backend offline task |
| `STALE_DATA_SECONDS` | 15 | Backend / AIOps |
| `OUT_OF_ORDER_TOLERANCE_SECONDS` | 300 | Backend |
| `RETRY_INITIAL_DELAY_SECONDS` | 1 | Collector |
| `RETRY_MAX_DELAY_SECONDS` | 60 | Collector |
| `RETRY_BACKOFF_FACTOR` | 2 | Collector |
| `RETRY_JITTER_SECONDS` | 0.5 | Collector |
| `COLLECTOR_COLLECT_INTERVAL_SECONDS` | 5 | Collector |
| `COLLECTOR_SEND_INTERVAL_SECONDS` | 5 | Collector |
| `COLLECTOR_LOCAL_RETENTION_HOURS` | 24 | Collector |
| `COLLECTOR_QUEUE_MAX_MB` | 100 (new, add to `.env.example`) | Collector |
| `COLLECTOR_SEND_BATCH_SIZE` | 50 (new, add to `.env.example`) | Collector |

## 11. Regional Ingestion and Residency (design note)

Each tenant has a home `region` (tenant record, `DATABASE_SCHEMA.md`). A collector is configured with its region's ingest URL. The backend instance serves one `REGION_ID` and refuses payloads for tenants homed elsewhere (`TENANT_MISMATCH`). For the hackathon a single region runs; the design and the `region` field are documented, and cross-region replication is deferred (`ARCHITECTURE.md` §9).

## 12. Tests

| Owner | Test | Expected |
|---|---|---|
| Member 1 | Payload written to queue before send | Crash injected before send leaves row `pending` |
| Member 1 | Backoff sequence | 1, 2, 4, 8 ... capped at 60, jitter within bounds, resets after success |
| Member 1 | Ack then mark | Row `delivered` only after 2xx |
| Member 1 | Restart with `in_flight` rows | Reset to `pending` and re-sent |
| Member 1 | Permanent 422 | Marked `rejected`, queue not blocked |
| Member 1 | Same `payload_id` on retry | Identical across attempts |
| Member 1 | Queue overflow | Oldest low-priority dropped, drop logged and counted |
| Member 2 | Duplicate `payload_id` | One row; second call returns 200 duplicate response; `duplicate_attempts` increments |
| Member 2 | Concurrent duplicates | Exactly one row |
| Member 2 | Out-of-order arrival | Stored and returned in `event_time_utc` order |
| Member 2 | Offline detection | Stopped heartbeats flip the collector to offline in expected time (use a fake clock) |
| Member 2 | 5xx vs 4xx | Infra fault returns 5xx; schema fault returns 4xx |
| Member 2 | Tenant from token | Body `tenant_id` mismatch is rejected |
| Integration | Outage drill | Section 9 results recorded |

None of these exist yet and none have been run.

## 13. Known Limitations

- At-least-once plus dedup is not distributed exactly-once; it depends on the unique constraint and a bounded queue.
- SQLite is a single-process queue; no multi-writer support.
- Timing depends on interval settings and has not been measured.
- Single region in the demo.
- No message broker; direct insert is enough at demo scale (`ARCHITECTURE.md` §9).
