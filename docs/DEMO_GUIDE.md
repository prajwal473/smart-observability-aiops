# DEMO_GUIDE.md — Demo Guide

Project: Smart Observability and AIOps Platform (CICADA 2026)
Purpose: step-by-step script for the final demonstration, covering all 18 required scenarios, with fallbacks.

> Nothing in this guide claims a result. Every "Expected" line is what should be observed; record what you actually observe in `FINAL_QUALITY_REPORT.md`.
> Autonomous remediation is **simulated / safe-test-only**. Say so on stage.

---

## 1. Roles During the Demo

| Role | Member | Job |
|---|---|---|
| Presenter | Member 4 (or whoever speaks best) | Talks, drives the dashboard |
| Operator | Member 1 | Runs collector commands, triggers scenarios, stops/starts services |
| Backend watcher | Member 2 | Watches logs/DB, answers backend questions |
| AIOps explainer | Member 3 | Explains anomaly / incident / recommendation reasoning |

## 2. Pre-Demo Setup (do 60 minutes before)

1. Fresh clone on the demo laptop; `cp .env.example .env`.
2. `docker compose up -d` (or the non-Docker path from `SETUP_SCRIPTS.md`).
3. Run the seed script: creates two tenants (**Tenant A**, **Tenant B**), at least two collectors for Tenant A and one for Tenant B, with tokens.
4. Start the telemetry generator for each collector in "normal" mode.
5. Wait about 10 minutes so baselines exist before triggering any spike.
6. Open browser tabs: dashboard (Tenant A), dashboard (Tenant B, separate profile/incognito), API docs page, log tail terminal, Egress Proof Panel.
7. Prepare **seeded sensitive values** in the generator's "sensitive" mode (fake only): a fake password, fake API key, fake bearer token, fake email, fake private IP / hostname. Never use real credentials.
8. Record a fallback screen recording of a full successful run.
9. Check: laptop charging, screen mirroring, internet not required for the local demo.

### Scenario trigger commands

Exact command names live in `collector-security/README` and `SETUP_SCRIPTS.md`. This guide uses placeholders; fill the real commands in the table once the collector CLI is final.

| Scenario flag | Placeholder command |
|---|---|
| normal | `<collector-cli> generate --mode normal` |
| cpu_spike | `<collector-cli> generate --mode cpu_spike --duration 60` |
| memory_spike | `<collector-cli> generate --mode memory_spike` |
| latency_spike | `<collector-cli> generate --mode latency_spike` |
| packet_loss | `<collector-cli> generate --mode packet_loss` |
| failed_logins | `<collector-cli> generate --mode failed_logins` |
| sensitive | `<collector-cli> generate --mode sensitive` |
| out_of_order | `<collector-cli> generate --mode out_of_order` |
| replay_duplicate | `<collector-cli> replay --last 20` |

## 3. Demo Script (target ~10–12 minutes, adjust to the allotted time)

For each scenario: **Do** → **Show** → **Expected** → **Say**.

### Scenario 1 — Normal infrastructure monitoring (1 min)
- **Do:** nothing; generator running in normal mode.
- **Show:** Infrastructure dashboard: CPU, memory, disk, services; Network dashboard: bandwidth, latency, packet loss, connectivity.
- **Expected:** values update continuously; health state is Excellent or Good with a reason shown.
- **Say:** "Local collectors gather telemetry; only approved metadata reaches the SaaS tier."

### Scenario 10 + 11 — Sensitive data redaction and Egress Proof Panel (2 min) — *demo this early; it is the headline feature*
- **Do:** switch collector to sensitive mode for one cycle.
- **Show:** Egress Proof Panel: the exact payload before transmission, fields removed by the allow-list, values redacted, pseudonymous source ID, payload ID, timestamp, delivery status.
- **Expected:** none of the seeded fake secrets appear in the transmitted payload; the panel matches what backend stored.
- **Show (proof):** query the backend DB / tail backend logs and show the secrets are absent.
- **Say:** "Raw logs stay local. This is the exact bytes that left the building."

### Scenario 2 — CPU spike (1 min)
- **Do:** trigger cpu_spike.
- **Show:** CPU chart rising; alert appears.
- **Expected:** anomaly flagged beyond the learned baseline; alert visible (target ≤ 15 s after breach — measure it, do not assert it).

### Scenarios 3–5 — Memory spike, latency spike, packet loss (1 min)
- **Do:** trigger each in turn (or one combined run if time is short).
- **Expected:** each yields an anomaly with a reason string.

### Scenario 6 — Repeated failed logins (30 s)
- **Do:** trigger failed_logins.
- **Show:** Security dashboard event with count and window; pseudonymous source ID rather than a raw IP.

### Scenarios 7, 8, 9 — Correlation, incident, explainable recommendation (2 min)
- **Do:** trigger cpu_spike + latency_spike together on one collector.
- **Show:** Incident page: one incident grouping related anomalies, priority, likely cause, evidence list; Recommendation page: suggested action with "why" explanation.
- **Say:** "Not one alert per metric — correlated into one prioritized incident, with reasoning."
- **Autonomy note:** if showing a remediation action, label it simulated / safe-test-only.

### Scenario 18 — Four health states (30 s)
- **Show:** fleet view with collectors in different states (Excellent, Good, Fair, Poor) and reasons; show the configurable thresholds and timestamped history.
- **Tip:** prepare one collector per state in advance with the generator so you are not waiting live.

### Scenarios 12–15 — SaaS outage, local buffering, retry and recovery, duplicate prevention (2.5 min)
- **Do:** stop the backend container.
- **Show:** collector logs: failed sends, exponential backoff intervals; Egress panel / local status shows queued payloads (record the queue count N).
- **Do:** restart backend.
- **Show:** backlog drains automatically; dashboard fills in the gap.
- **Do:** run `replay_duplicate`.
- **Expected:** backend reports duplicates ignored (idempotent on `payload_id`); row count unchanged.
- **Validation:** compare generated count with stored count; count duplicate `payload_id` values (expected zero). Report real numbers.

### Scenario 16 — Out-of-order events (30 s)
- **Do:** trigger out_of_order.
- **Expected:** late events stored with correct UTC event time and shown in time order; source timezone retained.

### Scenario 17 — Collector offline detection (1 min)
- **Do:** kill one collector process.
- **Show:** Fleet dashboard flips the collector to offline with last-seen time (target ≤ 60 s after last heartbeat — measure it).
- **Do:** restart the collector; it returns to online.

### Tenant isolation (bonus 30 s, strongly recommended)
- **Show:** Tenant B tab sees none of Tenant A's collectors; an API call with Tenant B's token for a Tenant A resource is rejected.

## 4. Performance Numbers to Show

Show only numbers you measured with timestamps, from `FINAL_QUALITY_REPORT.md`:

| Metric | Target | Measured (fill) |
|---|---|---|
| Collection-to-dashboard latency (p95) | ≤ 10 s | |
| Threshold breach-to-alert | ≤ 15 s | |
| Collector offline detection | ≤ 60 s of last heartbeat | |
| Post-outage backlog | zero lost, zero duplicates | |

If a number misses its target, show it anyway and explain why. Honest results score better than claims that do not hold up.

## 5. Failure Playbook

| Problem | Response |
|---|---|
| Backend will not start | `docker compose logs backend`; if not fixed in 2 minutes switch to the recorded run |
| Dashboard blank | Enable `USE_MOCK=true`; say it is mock data |
| Spike not detected | Baseline too short; use pre-seeded data tenant or the recording |
| Network at venue blocked | Everything is local; confirm no external calls are required |
| Judge asks something unplanned | Answer from `HACKATHON_JUDGING_CHECKLIST.md` Q&A section; say "not implemented" when true |

## 6. Rehearsal Checklist

- [ ] Rehearse the full script twice, timed
- [ ] Every scenario command tested on the demo laptop
- [ ] Seed data and fake secrets prepared
- [ ] Fallback recording saved locally
- [ ] Each member knows their role and their Q&A topics
- [ ] Browser zoom and font size readable from the back of the room

## 7. Closing Statement (30 s)

Summarise: local-first privacy with provable egress, reliable delivery without loss or duplicates, explainable AIOps incidents, tenant isolation, and the path to policy-controlled Autonomous Ops (currently simulated). Then state limitations honestly and invite questions.
