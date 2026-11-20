# MEMBER_EXECUTION_GUIDES.md

A concrete, checkable task list per member, aligned to the hour blocks in
`HACKATHON_24H_PLAN.md` (Batch 7) and the responsibilities in `TEAM_WORK_DISTRIBUTION.md`. Each
task references the exact contract/doc it must match.

---

## Member 1 — Collector & Security

**0–2h:** Read `MASTER_PROJECT.md`, `ARCHITECTURE.md`, `SECURITY_DESIGN.md`,
`SHARED_CONTRACTS.md` §1–5. Confirm allow-list field sets with the team.

**2–6h:**
- [ ] Build telemetry generator producing raw events for all four event types (with
  intentionally "dirty" fields — secrets, real hostnames — so redaction has something real to
  remove)
- [ ] Build the allow-list validator as a standalone, independently testable module
  (default-deny — unknown fields fail closed)
- [ ] Write unit tests proving known secret patterns are always scrubbed

**6–10h:**
- [ ] Build collector core loop: Collect → Filter → Redact → Aggregate → Analyze locally →
  Apply data policy
- [ ] Implement pseudonymous source ID generation (`HMAC(tenant_salt, real_identifier)`)
- [ ] Implement local SQLite raw store + buffer queue (two separate tables/files, per
  `ARCHITECTURE.md` §1)

**10–14h:**
- [ ] Implement local analysis for repeated-auth-failure counting → security summary event
  (contracts §4)
- [ ] Implement Egress Audit writer (contracts §11)
- [ ] Build retry/backoff transmission logic against M2's `/v1/ingest`

**14–18h (Checkpoint B — integration):**
- [ ] Point collector at M2's real `/v1/ingest` instead of a stub
- [ ] Run the "secret stays local" live test: raw store shows a secret, transmitted payload
  doesn't

**18–21h:**
- [ ] Forced-outage test: block network, confirm buffering, unblock, confirm zero-loss/
  zero-duplicate backlog delivery (measure actual `payload_id` sets sent vs. accepted)
- [ ] Measure collector-side timestamps for the performance targets table

**21–24h:**
- [ ] Prepare the live demo moment: terminal showing raw secret + Egress Proof Panel showing the
  same payload redacted, side by side

---

## Member 2 — Backend & Database

**0–2h:** Read `ARCHITECTURE.md`, `API_DOCUMENTATION.md`, `DATABASE_SCHEMA.md`,
`SECURITY_DESIGN.md` §7.

**2–6h:**
- [ ] Scaffold FastAPI app, PostgreSQL via Docker Compose, Alembic migration for all tables in
  `DATABASE_SCHEMA.md`
- [ ] Build the shared tenant-scoped query helper (every call requires `tenant_id`, no
  exceptions)
- [ ] Implement `/v1/collectors/register` and `/health`

**6–10h:**
- [ ] Implement `/v1/ingest` + `/v1/ingest/batch` with schema validation (reject
  non-allow-listed fields) and `payload_id` idempotent dedup (DB unique constraint backs this)
- [ ] Implement `/v1/collectors/{id}/heartbeat` and the offline-after-60s status computation

**10–14h:**
- [ ] Implement all dashboard-facing `GET` endpoints from `API_DOCUMENTATION.md`
- [ ] Implement `/v1/stream` WebSocket pushing the message types in contracts §13
- [ ] Seed database from `sample-data/` fixtures so M4 can integrate before M1's collector is
  wired in

**14–18h (Checkpoint B):**
- [ ] Accept real traffic from M1
- [ ] Persist M3's anomalies/incidents/recommendations as they're produced
- [ ] Serve M4's live REST/WS calls instead of fixture-seeded data

**18–21h:**
- [ ] Tenant-isolation test: confirm tenant A can never read tenant B's rows via any endpoint
- [ ] Run the forced-outage/reconnect test from M1's side and verify `delivery_records` shows
  zero duplicates

**21–24h:**
- [ ] Freeze API — no breaking changes this close to demo
- [ ] Prepare `/docs` (FastAPI auto-docs) as a backup artifact if asked about API design

---

## Member 3 — AIOps Engine

**0–2h:** Read `ARCHITECTURE.md` §5, `SYSTEM_WORKFLOW.md` §2 (CPU spike walkthrough),
`SHARED_CONTRACTS.md` §8–10.

**2–6h:**
- [ ] Build baseline module (rolling mean/std per tenant+source+metric) against
  `sample-data/infra_metrics_normal.json`
- [ ] Build z-score anomaly detector, tunable threshold, tested against
  `sample-data/infra_metrics_cpu_spike.json`

**6–10h:**
- [ ] Build correlation engine: group anomalies within a configurable time/entity window into
  one incident
- [ ] Build incident prioritization scoring (correlated-signal count × criticality × magnitude)

**10–14h:**
- [ ] Build recommendation generator — every output must include `contributing_signals`
  (contracts §9), never a bare text string with no traceable signal
- [ ] Build health-state classifier (Excellent/Good/Fair/Poor) with configurable thresholds and
  a `reason` string on every transition (contracts §10)

**14–18h (Checkpoint B):**
- [ ] Point the pipeline at M2's live Postgres instead of fixtures
- [ ] Confirm anomaly `detected_at_utc` minus injected-spike time is within the ≤15s target

**18–21h:**
- [ ] False-positive check: run the pipeline against an hour of "normal" synthetic data and
  confirm no anomalies fire — this is the evidence for Phase 4's "few false alarms" criterion
- [ ] Stretch goal if time allows: Isolation Forest pass on a multivariate feature vector,
  compared against the z-score baseline

**21–24h:**
- [ ] Prepare the explainability demo: pull up one incident and narrate exactly which signals
  triggered it and why the recommendation follows from them, without reading from a script

---

## Member 4 — Frontend Dashboard

**0–2h:** Read `API_DOCUMENTATION.md`, `SHARED_CONTRACTS.md` (all sections — frontend touches
every schema), `PARALLEL_DEVELOPMENT_PLAN.md` mock-data table.

**2–6h:**
- [ ] Scaffold React + TS + Vite + Tailwind project
- [ ] Build the data-access layer as a single swappable module (fixtures now, real API later —
  per `PARALLEL_DEVELOPMENT_PLAN.md`)
- [ ] Build infrastructure + network dashboards against fixtures

**6–10h:**
- [ ] Build security dashboard + collector fleet dashboard
- [ ] Build the four-health-state visual treatment with visible `reason` text, not just a color

**10–14h:**
- [ ] Build incident dashboard + recommendation dashboard (must surface `contributing_signals`
  visibly, not just the text — this maps to Phase 4's weighted explainability criterion)
- [ ] Build the **Egress Proof Panel** — the single highest-visibility component; show exact
  `fields_sent` / `fields_redacted` from contracts §11, ideally as a raw-vs-sent diff view

**14–18h (Checkpoint B):**
- [ ] Swap the data-access module from fixtures to M2's live REST/WS
- [ ] Confirm the WebSocket-driven updates land within the ≤10s dashboard-latency target visibly

**18–21h:**
- [ ] Stale-data handling: verify a source with no recent heartbeat visibly downgrades state
  (never silently shows a frozen "last good value")
- [ ] Polish pass only after functional correctness — a judge-facing demo values correctness
  over visual polish per the PDF's own "strong vs. weak" guidance

**21–24h:**
- [ ] Rehearse the live-scenario click-through: trigger a scenario, show the dashboard react,
  open the Egress Proof Panel, open an incident's explanation — in one continuous flow

---

## Cross-cutting checklist (all members, every checkpoint)

- [ ] Does every field I produce/consume exist in `SHARED_CONTRACTS.md`? If not, propose the
  addition there first.
- [ ] Have I measured anything I'm about to claim meets a performance target, or am I about to
  claim it from memory/assumption? (Never do the latter.)
- [ ] Does my workspace's test suite run green in isolation, without any other member's service
  running?
