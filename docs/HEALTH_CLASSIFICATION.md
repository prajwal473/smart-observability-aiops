# HEALTH_CLASSIFICATION.md — Four Health States

Project: Smart Observability and AIOps Platform (CICADA 2026)
Owner: Member 3 (rules and tests). Persistence and API: Member 2. Display: Member 4.

> Status: DRAFT. Every number is a starting proposal in a config file, not a tuned or measured value.
> Field names and enum spellings follow `SHARED_CONTRACTS.md` §6 and §10. If the two files disagree, the contracts win and this file must be fixed.
> The four **health states** (Excellent, Good, Fair, Poor) are different from the four **evaluation phases** in the judging checklist.

---

## 1. What Is Classified

| `entity_type` | `entity_id` | Meaning |
|---|---|---|
| `source` | `src_7f3a9c` | One pseudonymous monitored source |
| `collector` | `coll_bengaluru_01` | One collector agent (heartbeat, resources, delivery) |
| `tenant_fleet` | tenant ID | Roll-up of all collectors in one tenant |

The output is exactly the Health State object in `SHARED_CONTRACTS.md` §10:

```json
{
  "entity_id": "src_7f3a9c",
  "entity_type": "source",
  "tenant_id": "tenant_acme",
  "state": "Fair",
  "reason": "cpu_pct z-score 4.1 is above the Good limit of 3.5",
  "changed_at_utc": "2026-11-20T10:15:09Z",
  "stale": false
}
```

`state` is one of `Excellent`, `Good`, `Fair`, `Poor` (capitalised, as in the contracts).

## 2. Principle: Worst Signal Wins, With a Reason

The classifier turns the latest data into a list of **signals**. Each signal proposes a state and a reason. The final state is the **worst** proposed state. The reason shown is the reason of the signal that decided it, plus up to two more in `reason_details` for the UI. Nothing is hidden in a score, so a judge can ask "why is this Fair?" and get one sentence.

Order from best to worst: `Excellent` < `Good` < `Fair` < `Poor`.

## 3. Signals and Default Rules

### 3.1 Signals for a source

| ID | Signal | Excellent | Good | Fair | Poor |
|---|---|---|---|---|---|
| S1 | Metric deviation, worst \|z\| over `cpu_pct`, `memory_pct`, `disk_pct`, `latency_ms`, `packet_loss_pct`, `bandwidth_mbps` | < 2.0 | 2.0 to < 3.5 | 3.5 to 5.0 | > 5.0 **and** an open incident exists |
| S2 | Static safety limits (always on, independent of baseline) | below Fair limit | below Fair limit | at or above Fair limit | at or above Poor limit |
| S3 | Open incidents for this source | none | none | any open incident with severity `low`, `medium` or `high` | open incident with severity `critical` |
| S4 | Security events in the last window | none | `low` only | `medium` or `high` | `critical` |
| S5 | Connectivity (`connectivity_status`) | `up` | `up` | `degraded` | `down` |
| S6 | Service (`service_available`) | `true` | `true` | n/a | `false` |
| S7 | Data freshness (age of last telemetry for this source) | ≤ telemetry stale limit | ≤ telemetry stale limit | older than telemetry stale limit, `stale = true` | n/a (see collector offline) |
| S8 | Baseline maturity | enough samples | enough samples | n/a | n/a |

Rule for S8: if the baseline has fewer than `min_baseline_samples` samples, the source cannot be `Excellent`. Its best possible state is `Good`, with reason "baseline still learning (n of 30 samples)". This is the honest cold-start behaviour and matches `AIOPS_DESIGN.md` §4.

Default static limits (proposals):

| Metric | Fair at or above | Poor at or above |
|---|---|---|
| `cpu_pct` | 85 | 95 |
| `memory_pct` | 85 | 95 |
| `disk_pct` | 85 | 95 |
| `latency_ms` | 200 | 500 |
| `packet_loss_pct` | 2 | 5 |

### 3.2 Signals for a collector

| ID | Signal | Excellent | Good | Fair | Poor |
|---|---|---|---|---|---|
| C1 | Heartbeat age | ≤ 15 s | ≤ 15 s | > 15 s to ≤ 45 s (**stale**) | > 45 s (**offline**) |
| C2 | `config_status` | `valid` | `valid` | `pending_update` | `invalid` |
| C3 | Collector resource use (`resource_cpu_pct`, `resource_memory_mb`) | normal | normal | CPU ≥ 50 or memory ≥ 512 MB | n/a |
| C4 | Delivery backlog (queue depth, if reported) | 0 | small | growing for more than 2 minutes | n/a |

Heartbeat limits are deliberately tighter than the 60 s target in the brief: the offline check runs on an interval, so detection can lag the threshold by one check. With a 5 s heartbeat, a 5 s check and a 45 s offline limit, the worst expected detection is about 50 s after the last heartbeat. That is a design expectation, to be **measured**, not claimed.

### 3.3 Fleet roll-up

`tenant_fleet` state = worst state among the tenant's collectors. The reason names the count: "1 of 3 collectors Poor (coll_mumbai_02 offline)". A tenant with no collectors is `Poor` with reason "no collectors reporting".

## 4. Stale and Missing Data

Stale data must never look healthy.

| Situation | Result |
|---|---|
| Heartbeat 15 to 45 s old | Collector `Fair`, `stale: true`, reason "heartbeat 23 s old" |
| Heartbeat over 45 s old | Collector `Poor`, offline, reason "no heartbeat for 52 s" |
| Telemetry older than 30 s but heartbeat alive | Source `Fair`, `stale: true`, reason "no telemetry for 41 s" |
| Source never reported | No state is invented; the UI shows "no data" |
| Collector offline | Its sources are marked `stale: true` and capped at `Fair`; they are not rewritten to `Poor` by the collector rule alone |

The UI must show the `stale` flag and the age, never just the last known value.

## 5. Flapping Control (Hysteresis)

- **Getting worse is immediate.** A worse state is applied on the first evaluation that proposes it.
- **Getting better is delayed.** An improvement is applied only after `improve_after_consecutive` (default 2) consecutive evaluations propose the better state.
- A `Poor` collector that resumes heartbeats goes to the state its signals propose after that delay.

## 6. History

Every **change** of state writes one row to `health_state_history` (`DATABASE_SCHEMA.md`):

```
tenant_id, entity_id, entity_type, from_state, to_state, reason, changed_at_utc
```

- The first evaluation of an entity writes a row with `from_state = NULL`.
- No row is written when the state is unchanged.
- `changed_at_utc` is the **event time of the data that caused the change**, in UTC, not the processing time. For a backlog burst after an outage this keeps history in the right order.
- Retrieval: `GET /v1/health-states` and `GET /v1/health-states/{entity_id}/history` (see `API_DOCUMENTATION.md`).
- A `health_state_change` WebSocket message is sent on each change (`SHARED_CONTRACTS.md` §13).

## 6a. Evaluation Triggers

| Trigger | Entities evaluated |
|---|---|
| New telemetry payload accepted | The source, its collector |
| New heartbeat | The collector |
| Periodic offline check (every `OFFLINE_CHECK_INTERVAL_SECONDS`) | Every collector in every tenant, so silence is noticed |
| Incident opened, merged or resolved | The affected source and collector |

The periodic check is what makes "no data" turn into `Poor`; without it a silent collector would keep its last good state.

## 7. Configuration

File: `aiops-engine/config/health.yaml`. Loaded at start, no code constants. Environment variable `HEALTH_CONFIG_PATH` points to it.

```yaml
health:
  heartbeat:
    stale_after_seconds: 15
    offline_after_seconds: 45
  telemetry:
    stale_after_seconds: 30
  z_bands:
    excellent_below: 2.0
    good_below: 3.5
    fair_up_to: 5.0
  static_limits:
    cpu_pct:         {fair: 85,  poor: 95}
    memory_pct:      {fair: 85,  poor: 95}
    disk_pct:        {fair: 85,  poor: 95}
    latency_ms:      {fair: 200, poor: 500}
    packet_loss_pct: {fair: 2,   poor: 5}
  baseline:
    min_samples: 30
  hysteresis:
    improve_after_consecutive: 2
  security:
    window_seconds: 300
  collector_resources:
    cpu_pct_fair: 50
    memory_mb_fair: 512
```

`.env.example` keys `STALE_DATA_SECONDS`, `OFFLINE_THRESHOLD_SECONDS` and `AIOPS_MIN_BASELINE_SAMPLES` must agree with this file (see section 11).

## 8. Interface (proposed, for Member 3)

```python
def classify_source(tenant_id, source_id, now_utc, snapshot, cfg) -> HealthResult
def classify_collector(tenant_id, collector_id, now_utc, snapshot, cfg) -> HealthResult
def classify_fleet(tenant_id, collector_results) -> HealthResult

class HealthResult:
    state: str          # Excellent | Good | Fair | Poor
    reason: str         # the deciding signal, one sentence
    reason_details: list[str]
    stale: bool
    signals: list[Signal]   # every signal and what it proposed (for tests and the UI)
    evaluated_at_utc: datetime
```

A pure function of its inputs: no database access, no clock reads (time is passed in), so tests are deterministic.

## 9. Worked Examples

| Case | Inputs | State | Reason |
|---|---|---|---|
| Healthy | z all < 2, heartbeat 4 s, no incidents, 500 samples | Excellent | "all signals normal" |
| Cold start | z all < 2, only 12 samples | Good | "baseline still learning (12 of 30 samples)" |
| Mild drift | cpu_pct z = 2.7 | Good | "cpu_pct z-score 2.7 within Good band" |
| Sustained spike | cpu_pct z = 4.1, anomaly raised | Fair | "cpu_pct z-score 4.1 is above the Good limit of 3.5" |
| Spike plus incident | cpu_pct z = 9.4, open incident `inc_0001` | Poor | "cpu_pct z-score 9.4 with open incident inc_0001" |
| Static limit | cpu_pct 96, z low (baseline drifted) | Poor | "cpu_pct 96 at or above Poor limit 95" |
| Stale heartbeat | last heartbeat 23 s ago | Fair, `stale: true` | "heartbeat 23 s old" |
| Offline | last heartbeat 52 s ago | Poor | "no heartbeat for 52 s (offline)" |
| Critical security | `security_events` severity `critical` | Poor | "critical security event auth_failure_burst" |

## 10. Demo Support (scenario 18, "Four health states")

To show all four states on demand, prepare four sources or collectors with the generator:

| Target state | How to produce it |
|---|---|
| Excellent | Normal mode after the baseline has at least `min_samples` samples |
| Good | A collector still learning, or mild noise |
| Fair | `latency_spike` or a stopped heartbeat for 20 to 40 s |
| Poor | `cpu_spike` with an open incident, or a collector stopped for over 45 s |

Show the reason text, the `stale` flag, the configured thresholds and the history list.

## 11. Dependencies and Required Alignment

| File | Needs |
|---|---|
| `.env.example` | `OFFLINE_THRESHOLD_SECONDS=45`, `STALE_DATA_SECONDS=15`, `HEALTH_CONFIG_PATH`; the three `HEALTH_*_MAX_SCORE` score variables are not used by this design |
| `SYSTEM_WORKFLOW.md` §6 | Its table uses 30 s and 60 s as **examples**; the defaults here are 15 s and 45 s, for the reason in section 3.2 |
| `AIOPS_DESIGN.md` §11 | Its sample health JSON uses lower-case `fair` and `collector_id`; the contract uses `Fair`, `entity_id`, `entity_type` |
| `API_DOCUMENTATION.md` | Health endpoints already exist; add `reason_details` and `signals` as optional fields only after a contract change |

## 12. Tests (pytest, Member 3)

| Test | Expected |
|---|---|
| Each row of the worked examples in section 9 | Expected state and reason text contains the key value |
| Worst signal wins | One Poor signal among many Excellent gives Poor |
| Cold start cap | Fewer than 30 samples never gives Excellent |
| Stale never Excellent | Heartbeat of 20 s gives Fair and `stale: true` |
| Offline boundary | 45 s gives Fair or Poor exactly as configured; boundaries are inclusive/exclusive as documented |
| Hysteresis | Worsening is immediate; improving needs 2 consecutive evaluations |
| History | State change writes one row; unchanged state writes none; first evaluation has `from_state = None` |
| Backlog ordering | Replaying old payloads produces history ordered by event time |
| Config change | Editing the YAML thresholds changes results without code changes |
| Fleet roll-up | Worst collector decides; zero collectors gives Poor |
| Tenant isolation | Tenant A inputs never influence tenant B results |
| Reason present | Every result has a non-empty `reason` |

None of these tests exist yet and none have been run.

## 13. Known Limitations (say so in the demo)

- Thresholds are proposals, not tuned.
- "Worst signal wins" can be pessimistic when one metric is noisy.
- Collector-offline detection speed depends on the check interval and must be measured.
- Health is a classification aid, not a guarantee of system health.
