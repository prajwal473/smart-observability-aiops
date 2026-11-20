# MASTER_PROJECT.md
**Smart Observability & AIOps Platform — CICADA 2026 (TechForcz x Atria Institute of Technology)**
Source of truth document. Every other file in this repo must stay consistent with this one.

---

## 1. Problem Statement (from official PDF)

Organizations need to monitor distributed infrastructure, applications, networks and security
events without exposing sensitive operational data outside their own environments. Traditional
monitoring ships raw logs, payloads and credentials to a central platform, widening the attack
surface and risking compliance breaches.

**Challenge:** Design and build a secure, AIOps-driven observability platform using a **two-tier
architecture**. A local collector processes telemetry inside the customer environment, keeps raw
and sensitive data local, and sends only approved metadata, summaries, health indicators and
alerts to a centralized SaaS platform.

## 2. Core Direction (non-negotiable, from PDF cover page)

- Local-first data security
- Metadata-only SaaS communication
- AIOps-driven operations
- Global-ready design
- Future Autonomous Ops (simulated/safe-test only for this hackathon)

## 3. Two-Tier Architecture

### Tier 1 — Customer Environment / Local Collector
Sources: Applications | Servers | Network devices | Security sources
Pipeline: **Collect → Filter/Redact → Aggregate → Analyze locally → Apply data policy → Transmit**

Must:
- Collect infra, application, network and security telemetry from configured local sources
  (agents, SNMP, syslog, flow data, APIs).
- Keep raw logs, payloads, secrets, detailed sensitive records local **by default**.
- Filter, normalize, redact, aggregate, summarize locally before anything is transmitted.
- Send only **allow-listed** metadata: metric values, timestamps, pseudonymous source
  identifiers, health state, event category, severity, concise alert context.
- Enforce collector authentication, encrypted transport (TLS), local retention controls,
  auditable data-transfer records.
- Provide an **Egress Proof Panel** — a visible log of the exact contents of each payload
  before it leaves the environment. **Mandatory for every team.**
- Buffer data in a local SQLite queue during connectivity failures; retry with backoff after
  recovery; maintain auditable egress records; guarantee idempotent, duplicate-free delivery.

### Tier 2 — Central SaaS Platform (multi-tenant, metadata-only)
Pipeline: **Metadata ingestion → Fleet analytics → AIOps correlation → Dashboards/Alerts/Recommendations**

Must:
- Receive approved metadata only — never raw logs or secrets.
- Support multiple tenants with strict tenant-level data separation (never cross-visible).
- Display infrastructure health, network health, security events, collector fleet health.
- Detect anomalies, correlate related events, generate prioritized incidents, generate
  explainable recommendations.
- Provide dashboards and alerts.
- Support a future policy-controlled, human-approved path to Autonomous Ops.

## 4. Mandatory Functional Requirements

**Local collector & security:** telemetry collection, normalization, field allow-listing, secret
scrubbing, sensitive-data redaction, pseudonymous source identifiers, local aggregation, local
retention, collector authentication, encrypted communication, local SQLite queue, retry
mechanism, egress audit, Egress Proof Panel.

**Observability:** CPU, memory, disk, service availability, bandwidth, network latency, packet
loss, connectivity, repeated authentication failures, suspicious activity.

**Collector health:** online/offline status, last-seen time, collector version, resource usage,
configuration status.

**AIOps:** baseline calculation, anomaly detection beyond static thresholds, event correlation,
incident prioritization, likely-cause identification, explainable recommendations.

**Health classification — four states** (this is a *product* concept, distinct from the judging
phases below):

| State | Meaning | Illustrative condition |
|---|---|---|
| Excellent | Healthy | Collectors reporting; metrics within expected baselines |
| Good | Normal | Minor deviations, no significant service impact |
| Fair | Needs attention | Elevated latency, resource use, packet loss, recurring warnings |
| Poor | Critical | Collector unavailable, severe degradation, or critical security/network event |

Thresholds must be configurable; the reason for each state change must be shown to the operator;
stale/missing data must downgrade state (never silently show the last good value); all
transitions are timestamped in UTC with full history.

**Global-ready design:** regional ingestion, tenant data residency, UTC timestamps + source
timezone on every event, out-of-order events placed by event-time (not arrival time), unique
payload IDs, idempotent delivery.

**Reliability:** local buffering, exponential backoff, retry and resume, duplicate prevention,
zero-loss/zero-duplicate backlog delivery after outage, collector offline detection, SaaS outage
handling.

## 5. Performance Targets (suggested by organizers — must be measured, never claimed)

| Measure | Target | How measured |
|---|---|---|
| Collection → dashboard latency | ≤10s at p95 | event timestamp vs. dashboard render time |
| Threshold breach → alert raised | ≤15s | injected spike time vs. alert creation time |
| Collector offline detection | ≤60s of last heartbeat | outage start vs. status→Poor transition |
| Post-outage backlog delivery | zero loss, zero duplicates | sent IDs vs. received IDs after reconnect |

These numbers come from the official PDF's suggested values and are explicitly subject to
organizer confirmation before the event. All four must be demonstrated with real timestamp
deltas during the demo — no number may be stated without a measurement behind it.

## 6. Four-Phase Judging Framework (100 marks total)

| Phase | Focus | Marks |
|---|---|---|
| 1. Problem Understanding & Ideation | Early checkpoint | 10 |
| 2. Architecture & Technical Design | Design checkpoint | 25 |
| 3. Implementation & Working Prototype | Technical checkpoint (incl. 10 marks specifically for real-time performance & delivery reliability) | 35 |
| 4. Final Demo, Validation & Presentation | Final evaluation, live scenarios | 30 |

**Important distinction preserved from the official PDF:** the four judging *phases* above are
checkpoints across the hackathon timeline. The four health *states* (Excellent/Good/Fair/Poor) in
Section 4 are a feature of the product itself. Never conflate the two in any document or demo
narration.

Mandatory for every team regardless of phase: (1) real-time targets measured from timestamps,
(2) same organizer-provided simulated telemetry stream, (3) the Egress Proof Panel.

## 7. AIOps → Autonomous Ops Roadmap

| Stage | Capability | Expected behavior | In scope for 24h? |
|---|---|---|---|
| 1. Observe | Collect & visualize | Health, metrics, events, collector status | Yes |
| 2. Detect | AIOps detection | Anomalies/unusual patterns from metadata | Yes |
| 3. Correlate | Event intelligence | Group related alerts, likely affected components | Yes |
| 4. Recommend | Assisted operations | Likely causes + remediation steps for review | Yes |
| 5. Act | Autonomous Ops | Approved, policy-bounded, reversible actions, audited, rollback-capable | **Simulated / safe-test only** |

## 8. Bonus Challenges (official)

Privacy-aware metadata pipeline · Local buffering · Explainable AIOps · Alert-noise reduction ·
Safe remediation simulation · Global-ready delivery.

## 9. Team & Workspace Ownership

| Member | Workspace | Branch |
|---|---|---|
| 1 — Collector & Security | `collector-security/` | `feature/collector-security` |
| 2 — Backend & Database | `backend-database/` | `feature/backend-database` |
| 3 — AIOps Engine | `aiops-engine/` | `feature/aiops-engine` |
| 4 — Frontend Dashboard | `frontend-dashboard/` | `feature/frontend-dashboard` |

Full responsibility breakdown: see `TEAM_WORK_DISTRIBUTION.md`.
Full schema contracts: see `SHARED_CONTRACTS.md` (Batch 3).

## 10. Technology Stack (locked)

- **Frontend:** React, TypeScript, Vite, Tailwind CSS, Recharts, Lucide React
- **Backend:** Python, FastAPI, Pydantic, SQLAlchemy
- **Database:** PostgreSQL (central), SQLite (local buffer/audit)
- **AIOps:** Python, NumPy, Pandas, scikit-learn (Isolation Forest — optional/stretch)
- **Infra:** Docker, Docker Compose, Git, Pytest
- **Comms:** REST, WebSockets (where useful), HTTPS/TLS

## 11. Repository Structure

```
smart-observability/
├── docs/
├── collector-security/
├── backend-database/
├── aiops-engine/
├── frontend-dashboard/
├── shared/
├── sample-data/
├── scripts/
├── tests/
├── logs/
├── deployment/
├── .env.example
├── docker-compose.yml
├── README.md
└── MASTER_PROJECT.md
```

## 12. Status Tracker (updated every batch — do not let this drift)

**Documentation batches completed:** 1 of 9 (this batch)
**Implementation files completed:** 0
**Open decisions:** none yet — contracts not yet finalized (due Batch 3)
**Outstanding risks:** see README.md "Risks" section

## 13. Unclear / Flagged Items (per instruction: never guess)

- Exact organizer-provided telemetry stream format is not yet available — the telemetry
  generator (Member 1) is being built to a documented, swappable interface so it can be
  pointed at the real stream once released.
- Final confirmed performance target numbers are pending organizer confirmation; current
  numbers are the PDF's "suggested" values and are labeled as such everywhere they appear.
