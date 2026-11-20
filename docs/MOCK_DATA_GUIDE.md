# MOCK DATA GUIDE

> Status: DRAFT. Field names follow the project brief and are PROVISIONAL until
> reconciled with `docs/SHARED_CONTRACTS.md`. If the two ever disagree,
> SHARED_CONTRACTS.md wins and this file must be fixed.

## 1. Purpose

Every member must be able to build and test without waiting for anyone else.
Mock data is the substitute for the missing neighbours:

| Member | Workspace | Mock data they consume | Mock data they produce |
|---|---|---|---|
| 1 | collector-security | `sample-data/raw/` (fake raw telemetry with fake secrets) | `sample-data/payloads/` |
| 2 | backend-database | `sample-data/payloads/`, `sample-data/heartbeats/` | `sample-data/api-responses/` |
| 3 | aiops-engine | `sample-data/timeseries/` | `sample-data/aiops-output/` |
| 4 | frontend-dashboard | `sample-data/api-responses/`, `sample-data/ws-messages/` | none |

Rule: mock files are the contract in executable form. If code needs a field that
the mock files do not have, the contract must be changed first.

## 2. Directory Layout

```
sample-data/
├── raw/                    # Member 1 only. Never sent to SaaS. Contains FAKE secrets.
│   ├── raw_normal.jsonl
│   ├── raw_with_secrets.jsonl
│   └── raw_auth_failures.jsonl
├── payloads/               # Approved metadata payloads (post-redaction)
│   ├── payload_normal.json
│   ├── payload_cpu_spike.json
│   ├── payload_memory_spike.json
│   ├── payload_latency_spike.json
│   ├── payload_packet_loss.json
│   ├── payload_failed_logins.json
│   ├── payload_duplicate.json
│   └── payload_out_of_order.json
├── heartbeats/
│   ├── heartbeat_online.json
│   └── heartbeat_stale.json
├── timeseries/             # Member 3: 24h of per-minute history per metric
│   ├── ts_baseline_normal.csv
│   ├── ts_cpu_spike.csv
│   ├── ts_latency_packet_loss.csv
│   └── ts_cold_start.csv
├── aiops-output/
│   ├── anomalies.json
│   ├── incidents.json
│   ├── recommendations.json
│   └── health_states.json
├── api-responses/          # Member 4
│   ├── dashboard_infrastructure.json
│   ├── dashboard_network.json
│   ├── dashboard_security.json
│   ├── collectors_fleet.json
│   ├── incidents_list.json
│   ├── recommendations_list.json
│   ├── egress_proof.json
│   └── error_401.json / error_403.json / error_422.json
├── ws-messages/
│   └── ws_*.json
└── scenarios/
    └── scenario_*.json     # Ordered playlists for the demo (section 6)
```

## 3. Generation Rules

1. **Deterministic.** The telemetry generator takes `--seed` (default `42`). Same seed gives the same files.
2. **Fake secrets only.** Fixtures must use obviously fake values, such as
   `AKIAFAKEFAKEFAKE0000`, `password=hunter2-FAKE`, `Bearer FAKE.TOKEN.VALUE`.
   Never paste real credentials, even expired ones.
3. **UTC everywhere.** `*_utc` fields are ISO-8601 with `Z` suffix. Source timezone is
   a separate IANA string (e.g. `Asia/Kolkata`).
4. **Stable identifiers.** Use the fixed IDs in section 4 so tests across workspaces agree.
5. **Raw never crosses the boundary.** Only files in `raw/` may contain unredacted
   values. A CI check (see TESTING_STRATEGY.md) greps every other directory for the
   fake-secret markers and fails if any is found.

## 4. Fixed Identifiers

| Entity | Value |
|---|---|
| Tenant A | `tnt_acme_001` (region `ap-south-1`) |
| Tenant B | `tnt_globex_002` (region `eu-west-1`) |
| Collector A1 | `col_acme_blr_01` |
| Collector A2 | `col_acme_mum_02` |
| Collector B1 | `col_globex_dub_01` |
| Pseudonymous host | `src_7f3a9c21` |
| Schema version | `1.0` |

Tenant B exists mainly so Member 2 and Member 4 can test that tenant A never sees
tenant B data.

## 5. Canonical Examples (provisional)

### 5.1 Raw record (Member 1 only, never leaves the customer environment)

```json
{
  "ts_local": "2026-11-20T14:02:11+05:30",
  "host": "blr-app-01.internal.acme.example",
  "ip": "10.20.30.41",
  "cpu_percent": 91.4,
  "message": "login failed for user rahul.s@acme.example password=hunter2-FAKE from 10.20.30.77",
  "auth_header": "Bearer FAKE.TOKEN.VALUE"
}
```

### 5.2 Approved payload (after allow-listing, redaction, pseudonymisation)

```json
{
  "schema_version": "1.0",
  "payload_id": "3f6d2a10-8c1e-4b6a-9d52-0c5e7a1b2f90",
  "tenant_id": "tnt_acme_001",
  "collector_id": "col_acme_blr_01",
  "source_id": "src_7f3a9c21",
  "region": "ap-south-1",
  "collected_at_utc": "2026-11-20T08:32:11Z",
  "sent_at_utc": "2026-11-20T08:32:12Z",
  "source_timezone": "Asia/Kolkata",
  "sequence_no": 10492,
  "infrastructure": {
    "cpu_percent": 91.4,
    "memory_percent": 62.0,
    "disk_percent": 71.3,
    "services": [{"name": "app-service", "status": "up"}]
  },
  "network": {
    "bandwidth_in_mbps": 41.2,
    "bandwidth_out_mbps": 12.7,
    "latency_ms": 38.0,
    "packet_loss_percent": 0.1,
    "connectivity": "up"
  },
  "security": {
    "failed_login_count": 0,
    "suspicious_activity_count": 0,
    "redaction_summary": {"secrets_removed": 1, "emails_masked": 1, "ips_masked": 2}
  }
}
```

Notes: no hostname, no IP, no username, no message text. `redaction_summary` is counts only.

### 5.3 Heartbeat

```json
{
  "collector_id": "col_acme_blr_01",
  "tenant_id": "tnt_acme_001",
  "sent_at_utc": "2026-11-20T08:32:12Z",
  "collector_version": "0.1.0",
  "status": "online",
  "resource_usage": {"cpu_percent": 3.2, "memory_mb": 88, "queue_depth": 0},
  "config_status": "in_sync",
  "last_successful_delivery_utc": "2026-11-20T08:32:12Z"
}
```

### 5.4 Anomaly

```json
{
  "anomaly_id": "anm_0001",
  "tenant_id": "tnt_acme_001",
  "collector_id": "col_acme_blr_01",
  "metric": "cpu_percent",
  "observed_value": 91.4,
  "baseline_mean": 34.2,
  "baseline_std": 6.1,
  "z_score": 9.38,
  "method": "robust_zscore",
  "detected_at_utc": "2026-11-20T08:32:13Z",
  "window_start_utc": "2026-11-20T08:30:00Z",
  "severity": "high"
}
```

### 5.5 Incident

```json
{
  "incident_id": "inc_0001",
  "tenant_id": "tnt_acme_001",
  "title": "CPU spike with rising latency on col_acme_blr_01",
  "priority": "P2",
  "priority_score": 71,
  "status": "open",
  "opened_at_utc": "2026-11-20T08:32:14Z",
  "anomaly_ids": ["anm_0001", "anm_0002"],
  "likely_cause": "Resource saturation on application host",
  "likely_cause_confidence": 0.72,
  "evidence": ["cpu_percent 9.4 sigma above baseline", "latency_ms 4.1 sigma above baseline", "both within 60s window"]
}
```

### 5.6 Recommendation

```json
{
  "recommendation_id": "rec_0001",
  "incident_id": "inc_0001",
  "tenant_id": "tnt_acme_001",
  "action": "Investigate top CPU consumers and consider scaling the application tier",
  "rationale": "CPU and latency deviated together; memory and disk were normal, so a compute bottleneck is more likely than a leak or storage issue.",
  "evidence_refs": ["anm_0001", "anm_0002"],
  "risk_level": "low",
  "automation_mode": "simulated_only"
}
```

### 5.7 Egress audit / Egress Proof entry

```json
{
  "audit_id": "egr_000981",
  "payload_id": "3f6d2a10-8c1e-4b6a-9d52-0c5e7a1b2f90",
  "collector_id": "col_acme_blr_01",
  "prepared_at_utc": "2026-11-20T08:32:11Z",
  "transmitted_at_utc": "2026-11-20T08:32:12Z",
  "delivery_status": "delivered",
  "payload_sha256": "<hex digest of exact bytes sent>",
  "payload_bytes": 612,
  "fields_removed_count": 5,
  "payload": { "...": "exact JSON that was transmitted" }
}
```

The `payload` here must be byte-identical to what was sent. The hash lets the
frontend prove it.

### 5.8 Error response

```json
{
  "error": {
    "code": "TENANT_MISMATCH",
    "message": "Collector does not belong to this tenant",
    "request_id": "req_a81c...",
    "timestamp_utc": "2026-11-20T08:32:12Z"
  }
}
```

### 5.9 WebSocket message

```json
{
  "type": "incident.created",
  "tenant_id": "tnt_acme_001",
  "sent_at_utc": "2026-11-20T08:32:14Z",
  "data": { "incident_id": "inc_0001", "priority": "P2" }
}
```

Planned `type` values: `metric.updated`, `anomaly.detected`, `incident.created`,
`incident.updated`, `collector.status_changed`, `health.changed`, `egress.recorded`.

## 6. Scenario Playlists

Each `scenario_*.json` is an ordered list of payload files with delays. The
replay script (`scripts/replay_scenario.py`, to be written by Member 1) posts them
to the collector or directly to ingestion.

| # | Demo scenario | Fixture(s) | Expected observable result |
|---|---|---|---|
| 1 | Normal monitoring | `payload_normal` x N, `ts_baseline_normal` | Health Excellent/Good, no incidents |
| 2 | CPU spike | `payload_cpu_spike` | CPU anomaly, health drops |
| 3 | Memory spike | `payload_memory_spike` | Memory anomaly |
| 4 | Latency spike | `payload_latency_spike` | Network anomaly |
| 5 | Packet loss | `payload_packet_loss` | Network anomaly, health drops |
| 6 | Repeated failed logins | `payload_failed_logins`, `raw_auth_failures` | Security event |
| 7 | Event correlation | CPU + latency within 60 s | One correlated incident, not two |
| 8 | Incident generation | any correlated set | Prioritised incident visible |
| 9 | Explainable recommendation | incident 7/8 | Recommendation with evidence refs |
| 10 | Sensitive data redaction | `raw_with_secrets` | Payload contains none of the fake secrets |
| 11 | Egress Proof Panel | any payload | Panel shows exact transmitted JSON and hash |
| 12 | SaaS outage | backend stopped | Collector queues locally |
| 13 | Local buffering | same | Queue depth rises in heartbeat |
| 14 | Retry and recovery | backend restarted | Backoff then backlog drains |
| 15 | Duplicate prevention | `payload_duplicate` (same `payload_id` x2) | Second is acknowledged, not stored twice |
| 16 | Out-of-order events | `payload_out_of_order` | Stored by `collected_at_utc`, charts in order |
| 17 | Collector offline | stop heartbeats | Offline within 60 s of last heartbeat |
| 18 | Four health states | `health_states.json` | Excellent, Good, Fair, Poor all reachable |

Autonomous remediation in any scenario is `simulated_only`.

## 7. Time-Series Fixtures for Member 3

- 1,440 rows (24 h at 1/min) per metric, columns: `timestamp_utc,collector_id,metric,value`.
- `ts_baseline_normal.csv`: sinusoidal daily pattern plus Gaussian noise.
- `ts_cpu_spike.csv`: normal until minute 1,400, then +50 points for 5 minutes.
- `ts_cold_start.csv`: only 10 rows, to test the "insufficient baseline" path.
- Spike positions are recorded in `ts_*.meta.json` so tests can assert detection at
  the right minute.

## 8. Frontend Mock Rules (Member 4)

1. Load JSON from `public/mock/` through a single `api/client.ts` layer. Components
   never import JSON directly.
2. A `VITE_USE_MOCK=true` env flag swaps the client between mock files and real
   endpoints. No component changes are needed at integration.
3. Mock responses must be copies of `sample-data/api-responses/`. Do not hand-edit them
   inside the frontend workspace.

## 9. Suggested Commands (unverified, to be confirmed when scripts exist)

```bash
python scripts/generate_sample_data.py --seed 42 --out sample-data/
python scripts/validate_sample_data.py          # schema + fake-secret leak check
python scripts/replay_scenario.py sample-data/scenarios/scenario_cpu_spike.json
```

Expected: the validator exits 0 with "all fixtures valid" and "no secret markers
outside raw/". Until the scripts are implemented these are targets, not results.

## 10. Ownership

| Item | Owner |
|---|---|
| `raw/`, `payloads/`, generator script | Member 1 |
| `heartbeats/`, `api-responses/`, `ws-messages/` shape | Member 2 |
| `timeseries/`, `aiops-output/` | Member 3 |
| `public/mock/` consumption | Member 4 |
| `scenarios/`, `validate_sample_data.py` | Member 2 (integration lead) |

Changes to any fixture shape need a contract change and a note in the integration
branch.
