# AIOPS DESIGN

> Status: DRAFT. All numeric defaults are starting proposals, not tuned values.
> They must be validated against the sample time series before the demo.
> Field names are provisional until reconciled with SHARED_CONTRACTS.md.

## 1. Scope and Boundaries

The engine lives in `aiops-engine/` (Member 3). It is a pure Python library with a
thin service wrapper. It:

- reads approved metadata only (never raw telemetry),
- is tenant-scoped on every call,
- returns plain data structures matching the shared contracts,
- does not write to PostgreSQL directly. Member 2's backend persists what the
  engine returns.

```
backend ingest -> aiops.process(batch) -> {anomalies, incidents, recommendations, health}
                                              -> backend persists + pushes WebSocket
```

## 2. Public Interface (proposed)

```python
class AIOpsEngine:
    def process_payload(self, payload: dict) -> AIOpsResult: ...
    def process_batch(self, payloads: list[dict]) -> AIOpsResult: ...
    def classify_health(self, tenant_id: str, collector_id: str, now_utc) -> HealthResult: ...
    def check_stale(self, collector_id: str, now_utc) -> StaleResult: ...

class AIOpsResult:
    anomalies: list[Anomaly]
    incidents: list[Incident]          # new or updated
    recommendations: list[Recommendation]
    health: HealthResult
```

Rules:
- Input order must not matter. The engine sorts by `collected_at_utc` and
  tolerates late arrivals (section 8).
- State (baselines, open incidents) is held behind a `StateStore` interface with an
  in-memory implementation for tests and a backend-supplied implementation for the
  integrated system.

## 3. Metrics Analysed

| Group | Metrics |
|---|---|
| Infrastructure | `cpu_percent`, `memory_percent`, `disk_percent`, service availability |
| Network | `bandwidth_in_mbps`, `bandwidth_out_mbps`, `latency_ms`, `packet_loss_percent`, connectivity |
| Security | `failed_login_count`, `suspicious_activity_count` |

A baseline is kept **per tenant, per collector, per metric**.

## 4. Baseline Calculation

Goal: learn what "normal" is for this collector, so detection goes beyond a fixed
threshold.

**Method (default):** exponentially weighted moving average (EWMA) for the centre, plus
rolling median and median absolute deviation (MAD) for spread.

```
ewma_t   = alpha * x_t + (1 - alpha) * ewma_{t-1}          alpha = 0.1 (proposal)
window   = last N samples (N = 120, proposal)
median   = median(window)
mad      = median(|x_i - median|)
sigma_r  = 1.4826 * mad            # robust std-dev estimate
```

- **Why robust:** a few spikes should not drag the baseline upward and hide the
  next spike.
- **Anomalies are excluded from the baseline update**, so a prolonged anomaly does
  not become the new normal too quickly.
- **Minimum samples:** `MIN_BASELINE_SAMPLES = 30` (proposal). Below that the engine
  emits `baseline.insufficient_data`, falls back to static thresholds, and marks any
  resulting anomaly `confidence: "low"`.
- **Optional hour-of-day seasonality:** keep 24 buckets of median/MAD per metric and
  use the bucket when it has at least 10 samples. Off by default to keep the
  prototype simple.
- **Floor on sigma:** `sigma_r = max(sigma_r, sigma_floor[metric])` to avoid
  divide-by-near-zero on very flat metrics (e.g. packet loss at 0.0).

## 5. Anomaly Detection

### 5.1 Primary: robust z-score

```
z = (x - median) / sigma_r
anomaly if |z| >= Z_THRESHOLD       # 3.5 proposal
severity: 3.5-5 medium, 5-8 high, >8 critical   (proposal)
```

Direction matters per metric: CPU, memory, latency, packet loss, and failed logins
alert on **high** deviations only. Bandwidth alerts on either direction (a sudden
drop can mean an outage).

### 5.2 Persistence rule

To suppress single-sample noise: a metric is anomalous if `|z| >= Z_THRESHOLD` for
`K` of the last `M` samples (proposal: 2 of 3), except `critical` severity, which
fires immediately. This keeps breach-to-alert inside the 15 s target while limiting
false alarms. Needs measurement before the claim is made.

### 5.3 Static safety net

Hard limits from health thresholds (e.g. CPU at or above 95%) always raise an
anomaly even when the baseline has drifted. This answers "beyond static thresholds"
by *adding* baseline logic, not by removing safety limits.

### 5.4 Optional: Isolation Forest (bonus)

- scikit-learn `IsolationForest`, trained per collector on a multivariate window of
  `[cpu, memory, latency, packet_loss, bandwidth_in]`.
- Retrained every N minutes in a background step, never in the request path.
- Used as a **second opinion**: it can raise `method: "isolation_forest"` anomalies
  that z-score misses (unusual combinations), and it can raise confidence on a
  z-score anomaly.
- Disabled by default (`ENABLE_ISOLATION_FOREST=false`). The prototype must work
  fully without it.

### 5.5 Security-specific rule

Repeated authentication failures use a count-in-window rule: `failed_login_count`
summed over a 5-minute window at or above 10 (proposal) raises a `security`
anomaly regardless of baseline.

### 5.6 Service availability and connectivity

State changes (`up` to `down`, `connectivity: up` to `down`) are discrete anomalies
with severity `high`. No statistics needed.

## 6. Event Correlation

Goal: turn several related anomalies into one incident.

**Rule-based, explainable correlation (no black box):**

1. **Group key:** same `tenant_id` and same `collector_id` (or same `source_id`).
2. **Time window:** anomalies whose `detected_at_utc` fall within
   `CORRELATION_WINDOW = 120 s` (proposal) of each other join the same candidate group.
3. **Relationship rules** add strength to the link:

| Rule | Pattern | Link reason |
|---|---|---|
| R1 | CPU high + latency high | "Compute saturation likely affecting responsiveness" |
| R2 | latency high + packet loss high | "Network path degradation" |
| R3 | memory high + service down | "Possible memory exhaustion causing service failure" |
| R4 | failed logins high + CPU high | "Possible brute-force load" |
| R5 | disk high + service down | "Possible disk exhaustion" |
| R6 | bandwidth spike + latency high | "Traffic saturation" |
| R7 | multiple collectors in one tenant degrade within window | "Shared dependency or site-wide issue" |

4. Anomalies with no rule match but within the window still group, with
   `link_strength: weak`.
5. If an **open incident** exists for the same group key, new anomalies **merge**
   into it (and may raise priority) instead of creating a new incident.
6. An incident auto-resolves after `RESOLVE_AFTER = 5 min` with no new anomalies and
   metrics back within baseline (proposal).

Each incident stores which rules fired, so the dashboard can show *why* anomalies were
grouped.

## 7. Incident Prioritisation

Score 0 to 100, mapped to P1 to P4:

```
score = 0.35 * severity_score
      + 0.20 * breadth_score        # number of distinct metrics / collectors involved
      + 0.20 * duration_score       # how long it has persisted
      + 0.15 * criticality_score    # service down, security event, connectivity down
      + 0.10 * confidence_score
```

| Score | Priority |
|---|---|
| 80 to 100 | P1 |
| 60 to 79 | P2 |
| 40 to 59 | P3 |
| 0 to 39 | P4 |

Each sub-score is 0 to 100 and documented in the incident `evidence` list, so the
number is explainable. Weights are proposals; tune on fixtures.

## 8. Late, Duplicate, and Stale Data

| Situation | Handling |
|---|---|
| Out-of-order payload | Sorted by `collected_at_utc`. Baseline update uses the sample's own timestamp position. Detection on late data is flagged `late_arrival: true`. Alerts older than the alert-freshness limit (proposal 10 min) are recorded but not pushed as live alerts. |
| Duplicate `payload_id` | Ignored by the backend before reaching the engine. The engine also keeps a small seen-ID set as defence in depth. |
| Backlog burst after outage | Processed in timestamp order. Incidents are created with historical `opened_at_utc` equal to the first anomaly's time, not the processing time. |
| No data from collector | `check_stale` marks data stale after `STALE_AFTER` (proposal 3x expected interval) and the health classification reports reason "stale data". Stale data is never reported as Excellent. |

## 9. Likely-Cause Identification

Deterministic, rule-driven, and evidence-backed:

1. Take the rules that fired in correlation (R1 to R7).
2. Choose the highest-priority rule as `likely_cause`.
3. Confidence = base confidence of the rule (0.5 to 0.8) adjusted by:
   - +0.1 if 3 or more metrics agree,
   - +0.1 if the baseline had at least 100 samples,
   - -0.2 if the baseline was insufficient,
   - -0.1 if any contributing anomaly is `late_arrival`.
4. Also list **ruled-out** hints (e.g. "memory and disk normal") because they make the
   explanation convincing and honest.

The engine says "likely" and shows confidence. It never states certainty.

## 10. Recommendation Engine

Template-based, rule-keyed, and bound to evidence.

```python
Recommendation(
  incident_id, action, rationale, evidence_refs, risk_level, automation_mode
)
```

| Likely cause | Example action | Risk | Automation mode |
|---|---|---|---|
| Compute saturation | Inspect top CPU processes; consider scaling or throttling | low | `simulated_only` |
| Network path degradation | Check upstream link and ISP; run path test | low | `manual` |
| Memory exhaustion | Review memory growth; restart affected service in a safe window | medium | `simulated_only` |
| Brute-force load | Review source of failures; consider temporary rate limiting | medium | `simulated_only` |
| Disk exhaustion | Clean temp and log files; extend volume | medium | `manual` |
| Service down | Verify service status; review recent changes | medium | `simulated_only` |

Requirements:
- Every recommendation cites `evidence_refs` (anomaly IDs) and contains a plain-English
  `rationale` that references actual observed vs baseline values.
- `automation_mode` is only `manual` or `simulated_only` in this prototype. Nothing
  executes against a real system.
- A simulated action writes a record (`action_simulated`, with timestamp) so the demo
  can show the Autonomous Ops direction without risk. A policy gate placeholder
  (`policy_allows_automation(tenant_id, action)`) returns false by default.

## 11. Health Classification Hook

The four product states (Excellent, Good, Fair, Poor) are defined in
`HEALTH_CLASSIFICATION.md`. The engine only supplies inputs and a reason list:

```json
{
  "collector_id": "col_acme_blr_01",
  "state": "fair",
  "reasons": ["cpu_percent 91.4 above fair threshold 85", "open incident inc_0001 (P2)"],
  "stale": false,
  "evaluated_at_utc": "2026-11-20T08:32:14Z"
}
```

Thresholds are configurable (config file, not code constants). Every state change is
stored with a timestamp, giving the history the brief requires. Final threshold values
are defined in Batch 6. Do not hard-code them here.

## 12. Configuration

`aiops-engine/config/aiops.yaml` (proposed keys):

```yaml
baseline:
  alpha: 0.1
  window_size: 120
  min_samples: 30
  seasonality: false
anomaly:
  z_threshold: 3.5
  persistence: {k: 2, m: 3}
  isolation_forest: false
correlation:
  window_seconds: 120
  resolve_after_seconds: 300
priority:
  weights: {severity: 0.35, breadth: 0.20, duration: 0.20, criticality: 0.15, confidence: 0.10}
stale:
  multiplier: 3
```

## 13. Performance Notes

- Per-payload work is O(window) for MAD. With N=120 this is trivial for prototype scale.
- Keep rolling windows in memory per (collector, metric). Persist baselines
  periodically through the `StateStore`.
- Isolation Forest training stays out of the request path.
- Log `anomaly.detected` with `collected_at_utc` so breach-to-alert can be measured
  from log timestamps. The 15-second target is a goal to measure, not a result.

## 14. Test Plan (pytest, owned by Member 3)

| Test | Fixture | Expected |
|---|---|---|
| Baseline converges on normal data | `ts_baseline_normal` | median near generator mean, no anomalies |
| CPU spike detected at the right minute | `ts_cpu_spike` | anomaly within spike window, severity at least high |
| Single-sample noise suppressed | normal + 1 outlier | no anomaly (persistence rule) |
| Critical spike fires immediately | extreme outlier | anomaly on first sample |
| Cold start fallback | `ts_cold_start` | `baseline.insufficient_data`, low-confidence, static threshold only |
| Baseline not poisoned by anomaly | long spike then recovery | baseline median stays near normal |
| Correlation R1 | CPU + latency within 60 s | one incident, rule R1 listed |
| Correlation window respected | anomalies 10 min apart | separate incidents |
| Merge into open incident | extra anomaly joins | same incident, priority may rise |
| Tenant isolation | two tenants same metric spike | no cross-tenant correlation |
| Out-of-order input | shuffled payloads | same anomalies as sorted input |
| Backlog burst | 100 old payloads | incident `opened_at_utc` is historical |
| Stale detection | no data for 3x interval | stale true, never Excellent |
| Recommendation cites evidence | any incident | non-empty `evidence_refs`, rationale contains observed values |
| Automation safety | any recommendation | `automation_mode` in {manual, simulated_only} |
| Priority score explainable | any incident | evidence list includes each sub-score |

None of these tests exist yet, and none have been run.

## 15. Known Limitations (state honestly in the demo)

- Baselines need data. The first tens of minutes of a new collector use static
  thresholds.
- Correlation is rule-based and covers only the listed patterns.
- Likely cause is a ranked hint, not a verified diagnosis.
- Thresholds, weights, and windows are untuned proposals.
- No real remediation is executed. Autonomous Ops is shown as policy-gated simulation.

## 16. Ownership

| Item | Owner |
|---|---|
| Engine library, config, tests | Member 3 |
| Persistence of results, WebSocket push | Member 2 |
| Rendering anomalies, incidents, recommendations, health | Member 4 |
| Fixtures `timeseries/`, `aiops-output/` | Member 3 |
