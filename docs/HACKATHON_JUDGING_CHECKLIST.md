# HACKATHON_JUDGING_CHECKLIST.md — Judging Checklist

## Important notice about sources

This checklist is built from the **phase structure and mark totals given in the project instructions**:

| Phase | Name | Marks |
|---|---|---|
| 1 | Problem Understanding & Ideation | 10 |
| 2 | Architecture & Technical Design | 25 |
| 3 | Implementation & Working Prototype | 35 |
| 4 | Final Demo, Validation & Presentation | 30 |
| | **Total** | **100** |

The official PDF (`Smart_Observability_Hackathon_Evaluation_Guide_v8.pdf`) was **not available** when this file was generated, so the official sub-criteria and their individual mark splits are **not reproduced here and have not been guessed**. The rows below map the project's required features to each phase. Before submission, add the PDF's exact sub-criterion names and marks in the "Official sub-criterion (from PDF)" column.

Reminder: the four evaluation **phases** are different from the four product **health states** (Excellent, Good, Fair, Poor).

Status values: `Not started` / `In progress` / `Done` / `Verified` (Verified = actually run and evidence recorded).

---

## Phase 1 — Problem Understanding & Ideation (10 marks)

| Official sub-criterion (from PDF) | Project feature | Where it lives | Evidence | Demo step | Status |
|---|---|---|---|---|---|
| *(fill from PDF)* | Clear problem statement: local-first, metadata-only SaaS | `docs/MASTER_PROJECT.md` | Doc reviewed | Slide 2 | |
| *(fill from PDF)* | Two-tier architecture rationale | `docs/ARCHITECTURE.md` | Diagram | Slide 3 | |
| *(fill from PDF)* | Privacy/security motivation | `docs/SECURITY_DESIGN.md` | Doc | Slide 3 | |
| *(fill from PDF)* | AIOps value and Autonomous Ops direction | `docs/AIOPS_DESIGN.md` | Doc | Slide 4 | |
| *(fill from PDF)* | Global-ready thinking | `docs/ARCHITECTURE.md` (regions, residency) | Doc | Slide 5 | |

## Phase 2 — Architecture & Technical Design (25 marks)

| Official sub-criterion (from PDF) | Project feature | Where it lives | Evidence | Demo step | Status |
|---|---|---|---|---|---|
| *(fill from PDF)* | Architecture diagram, data flow | `docs/ARCHITECTURE.md`, `docs/SYSTEM_WORKFLOW.md` | Diagram | Architecture slide | |
| *(fill from PDF)* | Shared schemas and API design | `shared/`, `docs/SHARED_CONTRACTS.md`, `docs/API_DOCUMENTATION.md` | Pydantic models + OpenAPI page | Show `/docs` | |
| *(fill from PDF)* | Database design with tenant isolation, indexes | `docs/DATABASE_SCHEMA.md`, migrations | Schema + migration run | Show tables | |
| *(fill from PDF)* | Data privacy: allow-list, redaction, pseudonymous IDs | `collector-security/` + `docs/SECURITY_DESIGN.md` | Redaction tests | Egress panel | |
| *(fill from PDF)* | Reliability design: buffer, backoff, idempotency | `docs/RELIABILITY_DESIGN.md` | Doc + tests | Outage demo | |
| *(fill from PDF)* | AIOps design: baseline, anomaly, correlation, explainability | `docs/AIOPS_DESIGN.md` | Doc + tests | Incident demo | |
| *(fill from PDF)* | Health classification design (4 states, thresholds, stale handling) | `docs/HEALTH_CLASSIFICATION.md` | Doc + tests | Dashboard | |
| *(fill from PDF)* | Global-ready: UTC, source timezone, regional ingestion, residency, out-of-order | `docs/ARCHITECTURE.md`, payload schema | Sample payloads | Out-of-order demo | |
| *(fill from PDF)* | Logging architecture | `docs/LOGGING_ARCHITECTURE.md`, `logs/` | Sample log lines (no secrets) | Show logs | |

## Phase 3 — Implementation & Working Prototype (35 marks)

### 3.1 Local collector and security

| Requirement | Implementation location | Testing evidence | Demo step | Status |
|---|---|---|---|---|
| Telemetry collection (CPU, memory, disk, services, bandwidth, latency, packet loss, connectivity, auth failures) | `collector-security/` collector + generator | Unit tests, sample output | Normal monitoring | |
| Normalization | collector normalizer | Tests | — | |
| Field allow-listing | allow-list validator | Test: non-listed field dropped | Egress panel | |
| Secret scrubbing and sensitive data redaction | redaction engine | Test: seeded secrets removed | Redaction demo | |
| Pseudonymous source identifiers | collector ID module | Test | Payload view | |
| Local aggregation and retention | collector + SQLite | Test | — | |
| Collector authentication | collector config + backend auth | Test: bad token rejected | Auth failure demo | |
| Encrypted communication | HTTPS/TLS config | Config evidence (or documented demo exception) | — | |
| SQLite queue and retry with exponential backoff | `collector-security/` buffer/sender | Outage test | Outage demo | |
| Egress audit | SQLite audit table | Audit rows match sent payloads | Egress panel | |
| **Egress Proof Panel** | `frontend-dashboard/` panel + audit API | UI test / screenshot | Egress panel | |

### 3.2 Backend and database

| Requirement | Implementation location | Testing evidence | Demo step | Status |
|---|---|---|---|---|
| Multi-tenant support and tenant isolation | `backend-database/` auth + queries | Cross-tenant access test | Tenant switch demo | |
| Collector registration, heartbeat, ingestion APIs | FastAPI routers | API tests | Normal monitoring | |
| Idempotent delivery, unique payload IDs | ingestion service | Duplicate replay test | Duplicate demo | |
| Out-of-order handling, UTC + source timezone | ingestion + schema | Test | Out-of-order demo | |
| Collector offline detection (≤ 60 s target) | heartbeat monitor | Measured time | Offline demo | |
| WebSocket / REST for dashboards | backend | Manual + test | Live dashboard | |

### 3.3 AIOps

| Requirement | Implementation location | Testing evidence | Demo step | Status |
|---|---|---|---|---|
| Baseline calculation | `aiops-engine/` | Unit tests | — | |
| Anomaly detection beyond static thresholds | moving average + z-score (+ optional Isolation Forest) | Tests on synthetic spikes | Spike demos | |
| Event correlation | correlator | Tests | Incident demo | |
| Incident prioritization and likely cause | incident module | Tests | Incident demo | |
| Explainable recommendations | recommendation module | Tests | Recommendation demo | |
| Four health states with thresholds, reasons, stale handling, history | health classifier | Tests | Health demo | |

### 3.4 Frontend

| Requirement | Implementation location | Testing evidence | Demo step | Status |
|---|---|---|---|---|
| Infrastructure, Network, Security dashboards | `frontend-dashboard/` pages | Screenshots | Walkthrough | |
| Collector fleet dashboard | page | Screenshot | Fleet view | |
| Incident and recommendation views | pages | Screenshot | Incident demo | |
| Alerts | alert component | Screenshot | CPU spike demo | |

## Phase 4 — Final Demo, Validation & Presentation (30 marks)

| Official sub-criterion (from PDF) | Project feature | Evidence to prepare | Demo step | Status |
|---|---|---|---|---|
| *(fill from PDF)* | Live end-to-end demo of all 18 scenarios in `DEMO_GUIDE.md` | Rehearsal log | Full demo | |
| *(fill from PDF)* | Performance validation: dashboard latency p95 ≤ 10 s, alert ≤ 15 s, offline ≤ 60 s, backlog zero loss/zero duplicates | **Measured numbers** in `FINAL_QUALITY_REPORT.md` | Metrics slide | |
| *(fill from PDF)* | Validation of privacy claims (what was and was not sent) | Egress audit + DB inspection | Egress panel | |
| *(fill from PDF)* | Reliability validation (outage drill) | Integration checklist section G | Outage demo | |
| *(fill from PDF)* | Presentation quality and clarity | Slides, timed rehearsals | Slide deck | |
| *(fill from PDF)* | Q&A readiness | Prepared answers (see below) | Q&A | |
| *(fill from PDF)* | Honest limitations and future work (Autonomous Ops simulated/safe-test only) | Limitations slide | Closing | |

## Bonus Challenges

The PDF's bonus list was not available. Fill in from the PDF; tick only items genuinely implemented.

| Bonus item (from PDF) | Implemented? | Evidence |
|---|---|---|
| *(fill from PDF)* | | |

Candidates we may map if they match the PDF: Isolation Forest, simulated Autonomous Ops action, multi-region ingestion demo.

## Demo Run Order (suggested, ~10 minutes — adjust to the time given)

1. Problem and architecture (1 min)
2. Normal monitoring across dashboards (1 min)
3. Egress Proof Panel with seeded secrets redacted (2 min)
4. CPU spike → anomaly → correlated incident → explained recommendation (2 min)
5. Failed-login burst → security event (30 s)
6. SaaS outage → local buffering → recovery → zero loss / zero duplicates (2 min)
7. Collector offline detection and four health states (1 min)
8. Measured performance numbers and limitations (30 s)

## Likely Judge Questions — Prepare Answers

- What exactly leaves the customer environment? (Show Egress Proof Panel and audit.)
- How do you guarantee no duplicates after outage? (`payload_id` idempotency.)
- How is tenant isolation enforced? (Tenant-scoped auth and queries; show test.)
- Why is this better than static thresholds? (Baseline + z-score.)
- What is simulated vs real? (State clearly.)
- What did you measure and how? (Timestamps; show numbers.)

## Final Pre-Submission Check

- [ ] Every official sub-criterion from the PDF added to the tables above
- [ ] Every row has evidence or an honest "not implemented" note
- [ ] Performance numbers are real measurements, not targets
- [ ] No secrets in repository, logs, or slides
- [ ] Fresh-clone `docker compose up` verified
