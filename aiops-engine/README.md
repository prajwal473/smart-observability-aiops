# Smart Observability – AIOps Engine

## Overview

The AIOps Engine analyzes telemetry events and produces actionable observability results for the Smart Observability platform.

Its main capabilities include:

- Telemetry processing
- Anomaly detection
- Baseline analysis
- Incident correlation
- Recommendation generation
- Source health classification
- Fleet health classification

The engine accepts telemetry envelopes and produces results compatible with the shared contract. Backend connectivity, authentication, and authorization belong to the service or API integration layer.

## Technology

- Python 3.10+
- NumPy
- PyYAML
- Pytest (development and testing)

## Project Structure

- `engine.py` – Main AIOps engine entry point.
- `state_store.py` – StateStore interface and in-memory implementation.
- `serialization.py` – JSON-compatible result serialization.
- `contract_adapter.py` – Shared-contract result adapter.
- `anomaly_detection/` – Anomaly detection components.
- `baseline/` – Baseline calculation and management.
- `correlation/` – Event and incident correlation.
- `health/` – Health classification.
- `incidents/` – Incident management.
- `recommendations/` – Recommendation generation.
- `src/aiops/` – Legacy AIOps pipeline retained for compatibility.
- `config/health.yaml` – Health classification configuration.
- `tests/` – Automated tests.

## Installation

Create and activate a virtual environment:

```bash
python -m venv .venv
```

On Windows:

```cmd
.venv\Scripts\activate
```

Install the project:

```bash
python -m pip install -e .
```

Install development dependencies:

```bash
python -m pip install -e ".[dev]"
```

## Main Integration Interface

The recommended integration entry point is the root-level `AIOpsEngine` class.

```python
from engine import AIOpsEngine

engine = AIOpsEngine()

result = engine.process_payload(payload)
```

For multiple telemetry events:

```python
result = engine.process_batch(payloads)
```

The engine accepts telemetry envelopes using the shared contract and returns an `AIOpsResult` for serialization or adaptation by the integration layer.

Supported event types:

- `infrastructure_metrics`
- `network_metrics`
- `security_events`
- `collector_heartbeat`

### Telemetry validation

Each envelope must contain `payload_id`, `tenant_id`, `collector_id`, `source_id`, `event_type`, `event_time_utc`, `source_timezone`, `received_at_utc`, and `data`. Identifier fields must be non-empty strings. `source_timezone` is also checked as a non-empty string; its timezone name or offset is not otherwise validated. `data` must be a dictionary. Both timestamps must be ISO-8601 UTC strings ending in `Z`.

`process_batch()` rejects an empty batch, batches containing multiple tenants, and envelopes whose event or receipt timestamp is later than the supplied processing time. Repeated `(tenant_id, payload_id)` pairs are ignored after their first processing by that engine instance.

Numeric anomaly processing is limited to `cpu_pct`, `memory_pct`, and `disk_pct` in `infrastructure_metrics`, and `bandwidth_mbps`, `latency_ms`, and `packet_loss_pct` in `network_metrics`. Other event data is not treated as numeric anomaly input; security events are retained for health evaluation, and heartbeats update collector state.

The returned `AIOpsResult` contains:

- `anomalies`
- `incidents`
- `recommendations`
- `health`
- `source_health`

The result object is an engine output, not a backend connection. Use `serialize_result()` for JSON-compatible output or `serialize_contract_result()` for the shared-contract result shape.

## Baselines, Anomalies, Correlation, and Recommendations

Baselines are maintained independently for each `(tenant_id, source_id, metric)`. They use a rolling sample window and remain in warm-up until 30 normal samples are available. The anomaly detector compares a value with the baseline median using robust sigma (`1.4826 × median absolute deviation`); it detects a deviation at or above 3.5 robust standard deviations. At detector level, a zero-variability baseline treats any different value as an anomaly. The root engine omits that result because it cannot produce the finite z-score required for its anomaly output.

Metric events more than 600 seconds old at processing time are skipped for baseline and anomaly processing. StateStore recording still follows the event-specific snapshot and ordering rules. Older out-of-order events do not update the baseline.

The correlator groups anomalies by tenant and source and retains evidence in a rolling 120-second window. It evaluates correlation rules against the recent evidence and updates an open incident for that tenant/source when applicable.

Recommendations are generated from a correlated incident, its contributing anomalies, and fired rule details. They are evidence- and rule-based suggestions; the engine does not execute the recommended actions. At most one recommendation is generated for an incident by the engine's current flow.

## Serialization

Use `serialize_result()` to convert an `AIOpsResult` into a JSON-compatible dictionary.

```python
from serialization import serialize_result

output = serialize_result(result)
```

The serializer (`serialization.py`) recursively converts dataclasses, dictionaries, lists, and timezone-aware datetimes (formatted as ISO-8601 UTC strings ending in `Z`):

- **Naive datetimes:** Naive datetimes without timezone information are strictly rejected (`ValueError`).
- **Float sanitization:** Non-finite float values (`NaN`, positive `Infinity`, negative `Infinity`) are rejected with `ValueError` to guarantee strict JSON standard compliance.
- **Key collisions:** If string key conversion creates collisions (e.g. integer `1` and string `"1"` in the same dictionary), a `ValueError` is raised to prevent silent data loss.

Use `serialize_contract_result()` to produce the shared-contract result structure:

```python
from contract_adapter import serialize_contract_result

output = serialize_contract_result(
    result,
    engine.health_manager,
    tenant_id="your-tenant-id",
)
```

The contract adapter (`contract_adapter.py`) formats output according to `docs/SHARED_CONTRACTS.md`:

- Formats `anomalies`, `incidents`, `recommendations`, `health` (fleet health), and `source_health`.
- Determines `changed_at_utc` for health entities from transition history. If no transition exists for an active health state, it raises a `ValueError` rather than fabricating timestamps.
- Individual collector health is not included in `AIOpsResult` yet.

## State Management

The engine accepts an injectable state store:

```python
from engine import AIOpsEngine
from state_store import InMemoryStateStore

store = InMemoryStateStore()
engine = AIOpsEngine(state_store=store)
```

The `StateStore` interface defines the following tenant-scoped operations:

- `record_telemetry(payload)` – Stores a validated telemetry envelope and updates entity snapshots.
- `get_source_snapshot(tenant_id, source_id)` – Retrieves the current snapshot for a source.
- `get_collector_snapshot(tenant_id, collector_id)` – Retrieves the current snapshot for a collector.
- `add_anomalies(tenant_id, source_id, anomalies)` – Stores detected anomalies for a source.
- `get_anomalies(tenant_id, source_id)` – Retrieves anomalies belonging to a source.
- `set_source_incidents(tenant_id, source_id, incidents)` – Updates incidents associated with a source.
- `add_recommendation(tenant_id, recommendation)` – Stores a recommendation.
- `get_recommendations(tenant_id, incident_id)` – Retrieves recommendations for an incident.

The in-memory store scopes source snapshots, collector snapshots, anomalies, incidents, and recommendations by tenant. Heartbeats update collector state only: they do not create or modify source records or source-to-collector associations. For infrastructure, network, and security telemetry, the source association changes only when the event timestamp is strictly newer than the source's last telemetry timestamp. Stale and equal-time events cannot regress or replace that association.

`InMemoryStateStore` is intended for development and testing. Its data is lost when the process stops.

**Persistence limitation:** Injecting a persistent `StateStore` does not automatically persist every engine component. Baseline state (maintained by `BaselineRegistry`), incident lifecycle and correlation state (maintained by `IncidentPipeline` and `IncidentManager`), health history transitions (tracked by `HealthManager` / `HealthHysteresis`), and payload deduplication sets (`_seen_payload_ids`) also maintain in-memory state and require appropriate persistence integration for complete multi-process or fault-tolerant resilience.

The backend team can implement the `StateStore` interface (e.g., using PostgreSQL) without changing the engine's processing flow. The store interface alone does not provide API authentication or tenant authorization.

## Incident Lifecycle and Update Conflict Resolution

The `IncidentManager` governs incident creation, state transitions, updates, and audit history.

### Lifecycle Statuses

- `open`
- `acknowledged`
- `resolved` (terminal state; resolved incidents cannot be updated or acknowledged)

### Conflict Handling & Stale Updates

Incident timestamps must include a timezone. Comparisons normalize both timestamps to UTC, so differently formatted timestamps representing the same instant compare equally.

- **Newer updates (`incoming_timestamp > stored_timestamp`):** Title and non-null recommendation metadata may update; severity is accepted when its rank is greater than or equal to the stored rank. Source and anomaly ID lists are merged without duplicates, and `updated_at_utc` advances in normalized UTC form.
- **Stale updates (`incoming_timestamp < stored_timestamp`):** They cannot overwrite title, recommendation, or severity, and cannot move `updated_at_utc` backward. New source and anomaly IDs may still be merged. A history entry is written only when the stored incident changes.
- **Equal timestamps (`incoming_timestamp == stored_timestamp`):** Metadata updates are accepted; severity follows the same greater-than-or-equal rank rule. Lists may merge, while `updated_at_utc` does not advance.

### Health Hysteresis & Stale Evaluation Protection

The health hysteresis layer (`health/health_hysteresis.py`) tracks the latest evaluation timestamp per `(tenant_id, entity_type, entity_id)`:

- **Stale Evaluations (`now_utc < last_evaluated_at_utc`):** Evaluations with timestamps older than previously accepted evaluations return the current effective state without modifying active states, incrementing improvement counters, or appending regressed history events.
- **Equal & Newer Evaluations (`now_utc >= last_evaluated_at_utc`):** Evaluations with equal or advancing timestamps proceed normally, allowing worsening transitions immediately and progressing consecutive improvement counters.

### Incident History Event Format

History is tracked per incident ID. Each history entry contains:
```json
{
  "event": "created" | "updated" | "acknowledged" | "resolved",
  "previous_status": "open" | "acknowledged" | null,
  "new_status": "open" | "acknowledged" | "resolved",
  "actor_id": "system" | "admin_user_id" | "system:auto-resolver",
  "timestamp_utc": "2026-11-20T10:15:00Z",
  "changes": {
    "title": {"previous": "Old Title", "new": "New Title"},
    "severity": {"previous": "high", "new": "critical"},
    "affected_source_ids": {"added": ["src_02"]},
    "contributing_anomaly_ids": {"added": ["anom_02"]},
    "recommendation_id": {"previous": null, "new": "rec_01"}
  }
}
```

**No-op updates** (where no fields change and no IDs are added) produce **no duplicate history entries**.

## Tenant Authorization Responsibility

- **Component Scope:** `IncidentManager` and `AIOpsEngine` operate as standalone computational and analytical domain components. They enforce tenant validation (e.g., validating non-empty tenant strings and rejecting cross-tenant updates/batches), but **do not independently authenticate callers or verify caller identity against tenant boundaries**.
- **Service/API Responsibility:** Tenant authorization must be strictly enforced at the API, service, or gateway layer *prior* to invoking engine and incident lifecycle operations. An authenticated caller's identity must be verified to have access to the target incident's `tenant_id` before calling lifecycle methods such as `acknowledge()`, `resolve()`, `update_incident()`, or `get_history()`.

## Integration Blockers & Backend Alignment

Full end-to-end integration with the backend service requires coordinating the following items with the backend and Member 2:

1. **Telemetry GET Authentication & Tenant Authorization:**
   - The telemetry GET endpoint must enforce HTTP Bearer authentication and tenant authorization. The previously audited backend implementation does not yet enforce these requirements; remediation belongs to the backend team.
   - Tenant isolation must prevent cross-tenant telemetry access. A shared token without verified identity-to-tenant authorization is insufficient. The AIOps engine does not provide API authentication or authorization.
2. **Event Type Naming Alignment:**
   - The canonical shared contract (`docs/SHARED_CONTRACTS.md`) specifies:
     - `infrastructure_metrics`
     - `network_metrics`
     - `security_events`
     - `collector_heartbeat`
   - The backend service currently uses shorthand identifiers: `infrastructure`, `network`, `security`, `heartbeat`.
   - The engine maintains canonical naming and will not alter canonical contract definitions without cross-team agreement.
3. **Telemetry Response Envelope & Format Alignment:**
   - The engine expects canonical telemetry envelopes containing metadata (`payload_id`, `tenant_id`, `collector_id`, `source_id`, `event_type`, `event_time_utc`, `source_timezone`, `received_at_utc`, `data`).
   - Telemetry query endpoints and response packaging must be formally aligned and agreed upon before connecting live pipelines.
4. **Security Event Metric Correlation:**
   - Canonical security events provide `event_category`, `severity`, `count`, `window_seconds`, and `context`.
   - Correlation rule R4 in the correlator currently matches on metric `failed_login_count` and `cpu_pct`.
   - Security events are retained for health evaluation, but are not converted into numeric anomaly metrics by the current engine flow. Correlation rule R4 expects `failed_login_count` alongside `cpu_pct`; mapping canonical security event `count` (where `event_category == "auth_failure_burst"`) into anomaly evidence remains an integration limitation requiring team agreement.

## Health Configuration

The default health configuration is:

```text
config/health.yaml
```

The engine also supports the `HEALTH_CONFIG_PATH` environment variable to specify a different configuration file.

Only set this variable when you have a real configuration file at the specified path.

Windows CMD example (replace the example path with your actual file):

```cmd
set "HEALTH_CONFIG_PATH=C:\actual\path\health.yaml"
```

To clear the variable in the current CMD session:

```cmd
set "HEALTH_CONFIG_PATH="
```

The default `config/health.yaml` currently sets heartbeat stale/offline thresholds to 15/45 seconds and source telemetry staleness to 30 seconds. Source health also considers metric deviation, configured static limits, open incidents, recent security events, connectivity and service availability, collector availability, and baseline maturity (30 samples). Collector health uses heartbeat freshness, collector status, and resource signals. For a processed batch, fleet health is the worst-state roll-up of its distinct collectors; a batch with no collectors is classified as Poor. Health improvements require two consecutive qualifying evaluations by default, while worsening transitions apply immediately. These thresholds can be changed through the health configuration.

## Legacy Pipeline

The existing `src/aiops/` implementation is retained for backward compatibility.

The root-level `engine.py` implementation is the recommended processing interface for new integrations. It accepts canonical telemetry envelopes and returns results; the surrounding service/API is responsible for connecting backend input and output, including authentication and authorization.

## Running Tests

Run the complete unittest suite:

```bash
python -m unittest discover -s tests -v
```

Run the pytest suite:

```bash
python -m pytest -q
```

Latest reported test execution results (2026-11-21): 353 tests passed with unittest; 394 tests and 45 subtests passed with pytest. These are execution results, not coverage percentages.

## Backend Integration

The backend integration runner is:

```text
run_backend_pipeline.py
```

This runner uses the legacy `src/aiops` pipeline. It is separate from the recommended root-level `engine.py` interface and does not demonstrate an HTTP integration of that engine.

Backend authentication and the final integration flow must be configured using the backend team's agreed API contract and credentials.

Never hardcode API tokens or other credentials in source files.

## Shared Contract

The shared contract documentation is maintained at:

```text
../docs/SHARED_CONTRACTS.md
```

Event names, field names, identifiers, and enumerated values must remain compatible with that document.

Any proposed contract changes must be reviewed by the team before implementation.
