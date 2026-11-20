# SYSTEM_WORKFLOW.md

Concrete, step-by-step walkthroughs of how data and events move through the system. Written so
any team member (or judge) can trace a single event from source to dashboard. Consistent with
`ARCHITECTURE.md` and `MASTER_PROJECT.md`.

---

## 1. Normal Telemetry Flow (happy path)

1. Telemetry generator emits a raw event, e.g.:
   `{host: "db-01.internal", cpu_pct: 42.1, ts: "2026-11-20T10:15:03Z", raw_user: "pratham_admin"}`
2. Collector core normalizes field names/units to the shared schema.
3. Allow-list filter checks the event type (`infrastructure_metrics`) against the allowed field
   set: `cpu_pct`, `event_time_utc`, `source_id` pass; `raw_user`, `host` (literal hostname) do
   **not** pass as-is.
4. `host` is replaced with a pseudonymous `source_id` (stable hash, salted per-tenant, not
   reversible from the SaaS side); `raw_user` is dropped entirely (not in the allow-list for this
   event type).
5. Collector writes the raw event (unmodified) to the **local-only** SQLite raw store, and the
   transformed, allow-listed metadata to the **buffer** SQLite queue.
6. Egress Proof Panel reads the buffer queue and displays the exact payload that is about to be
   sent — this is the artifact a judge inspects for Phase 3's "proof that raw data stays local."
7. Buffer drains over TLS to the regional ingest endpoint with the collector's auth credential
   and a unique `payload_id`.
8. FastAPI ingestion validates the payload against the `infrastructure_metrics` schema, checks
   `payload_id` isn't already seen (idempotency), attaches `tenant_id` from the authenticated
   collector's registration, and inserts into PostgreSQL.
9. AIOps engine (polling or triggered) reads new metadata, updates the rolling baseline for
   `(tenant_id, source_id, cpu_pct)`.
10. Dashboard (via REST poll or WebSocket push) renders the updated infra health panel.

**Timestamps captured for the performance target:** `event_time_utc` (step 1) vs. dashboard
render time (step 10) → must be ≤10s at p95.

## 2. CPU Spike → Anomaly → Incident → Recommendation

1. Generator injects a CPU spike (`cpu_pct` jumps from ~40% baseline to 95%).
2. Steps 2–9 above proceed identically — the spike value itself is a legitimate allow-listed
   metric, nothing extra needs redacting.
3. AIOps baseline module computes the z-score of the new value against the rolling
   `(tenant_id, source_id, cpu_pct)` baseline; score exceeds the configured anomaly threshold.
4. Anomaly event is created: `{source_id, metric: "cpu_pct", observed: 95.0, baseline_mean: 41.8,
   baseline_std: 3.2, z_score: 16.6, detected_at_utc: ...}`.
5. Correlation step checks for other anomalies on the same `source_id` within the correlation
   window (e.g. a simultaneous memory spike or a related service's latency anomaly). If found,
   they're grouped into a single incident; if not, the incident has one contributing anomaly.
6. Incident is prioritized: severity scores higher if (a) multiple correlated signals, (b) the
   affected source is tagged critical, (c) z-score magnitude is large.
7. Recommendation engine generates: `"CPU on <source_id> is 16.6 standard deviations above its
   14-day baseline with no corresponding traffic increase — investigate for a runaway process or
   memory leak before it affects dependent services."` — stored with the exact contributing
   signal list attached.
8. Dashboard's incident + recommendation panels render the incident, its contributing anomalies,
   and the explanation — this maps directly to Phase 4's "explainable AIOps recommendations
   (weighted higher)" criterion.

**Timestamp captured for the performance target:** injected spike time (step 1) vs. alert/anomaly
creation time (step 4) → must be ≤15s.

## 3. Repeated Failed Logins (security, local-only raw)

1. Security source emits a burst of failed-login events, each containing a raw username/IP.
2. Collector's local analysis step counts failed attempts per source within a rolling window
   **before** anything is queued for transmission.
3. If the count exceeds a configured threshold, the collector creates a *security summary*
   event: `{source_id, event_category: "auth_failure_burst", count: 12, window_seconds: 60,
   severity: "high", event_time_utc: ...}` — this summary, not the raw login attempts, is what
   enters the buffer queue.
4. The raw login attempts (with real usernames/IPs) stay in the local-only raw SQLite store and
   are never queued, never transmitted.
5. SaaS receives only the summary; AIOps can still raise an incident and recommendation from it
   without the SaaS platform ever seeing a single real username or IP.

This is the live-scenario test in PDF §8 ("Repeated failed logins ... without exporting raw
authentication records") and should be demoed as a side-by-side: raw store (local terminal/log)
next to the SaaS dashboard showing only the summary.

## 4. Collector Loses Connectivity → Buffer → Reconnect

1. Collector's transmission attempt starts failing (simulated by blocking the ingest endpoint).
2. Collector marks itself as "unable to transmit," keeps collecting and locally processing
   telemetry as normal — nothing about local processing changes.
3. New allow-listed payloads continue to be written into the buffer queue (not the raw store),
   each with its own unique `payload_id`.
4. Backend's heartbeat tracker notices no heartbeat for >60s and transitions the collector's
   displayed status to Poor/offline — this is purely a SaaS-side observation of silence, not
   something the collector "tells" it (it can't, by definition, while disconnected).
5. On reconnect, collector retries with exponential backoff; once a connection succeeds, the
   full buffer drains in `event_time_utc` order.
6. Ingestion endpoint's idempotency check (`payload_id` uniqueness) guarantees every payload is
   accepted exactly once, even if the collector retries a payload the server actually did
   receive just before the connection dropped.
7. Dashboard shows the collector flip back to a healthy state once heartbeats resume, and the
   backlogged metrics backfill the relevant charts at their correct `event_time_utc` positions
   (not bunched up at "now").

**Timestamps captured for performance targets:** outage start vs. Poor transition (≤60s);
sent `payload_id` set vs. received `payload_id` set after reconnect (zero loss, zero duplicates).

## 5. Out-of-Order Event Arrival

1. Network hiccup causes event A (timestamp T) to arrive at the backend *after* event B
   (timestamp T+5s), even though A was generated first.
2. Ingestion endpoint stores both using their `event_time_utc`, not arrival order.
3. Any rolling baseline or chart that had already incorporated B is recomputed to correctly
   include A at its proper position — the dashboard trend line is never visibly "corrupted" by
   the late arrival.
4. If A and B happen to share the same `payload_id` (a true duplicate retry rather than two
   distinct events), the idempotency constraint ensures only one row ever exists.

## 6. Four Health States — Worked Example

Given configurable thresholds for `cpu_pct` z-score:

| State | Condition (example) |
|---|---|
| Excellent | Collector heartbeat <30s old; all z-scores within ±2 |
| Good | Heartbeat <30s old; z-scores within ±3, no correlated incident open |
| Fair | z-score 3–5, OR heartbeat 30–60s old (stale, not yet offline) |
| Poor | z-score >5 with an open incident, OR heartbeat >60s old (offline), OR a critical security event |

Every state transition writes a row to a `health_state_history` table: `{entity_id, from_state,
to_state, reason, changed_at_utc}`. Stale/missing data is handled by the "heartbeat 30–60s old →
Fair" / "heartbeat >60s old → Poor" rule above — the UI never just keeps showing the last known
value as if nothing changed.

## 7. Egress Proof Panel — What It Actually Shows

For a selected payload (by `payload_id` or by time range), the panel displays:
- The exact JSON that was queued for transmission (field-for-field)
- A diff view against what the *raw* event originally contained, showing which fields were
  dropped/redacted/pseudonymized
- The transmission timestamp and the collector's audit-log hash for that payload

This is the artifact judges are told to explicitly request in Phases 2–4 ("Can you open the
egress proof panel and show the last payload?").
