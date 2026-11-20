# TESTING_STRATEGY.md — Testing Strategy

Project: Smart Observability and AIOps Platform (CICADA 2026)

> Status: DRAFT. Nothing described here has been run. Tick results only after running them, and record the command and date.
> Goal: prove the mandatory requirements with the least effort in 24 hours. Prefer a few meaningful tests per module over broad coverage.

---

## 1. Principles

1. **Test the promises first.** Privacy (no secrets leave), reliability (no loss, no duplicates), tenant isolation, explainable AIOps, the four health states. These are what judges probe.
2. **Each member can test alone.** Every module has fixtures and stubs so no one waits for another member.
3. **Contracts are tested, not trusted.** Sample data is validated against the shared schemas in CI.
4. **Deterministic.** Fixed seeds (`GENERATOR_SEED=42`), fake clocks, no sleeping in unit tests.
5. **Honest reporting.** Results go to `FINAL_QUALITY_REPORT.md` as run. "Not tested" is a valid entry.

## 2. Test Levels

| Level | What | Who | When | Tool |
|---|---|---|---|---|
| Unit | Functions and classes in one module | Owner | Continuously | `pytest`, frontend test runner |
| Contract | Sample JSON and API payloads against schemas | Members 1, 2, 4 | From hour 2 | `pytest`, schema validation |
| Component | One module with real internals, stubbed neighbours | Owner | Hours 6 to 14 | `pytest`, stub server, mock JSON |
| Integration | Two or more modules together | Member 2 leads | Hours 14 to 18 | `docker compose`, scripts |
| End-to-end | The 18 demo scenarios on the full stack | All | Hours 18 to 21 | Generator CLI, dashboard |
| Non-functional | Latency, alert time, offline time, backlog | All | Hours 18 to 21 | `scripts/measure_latency.py`, drills |
| Security | Secret leakage, tenant isolation, auth | Members 1 and 2 | Hours 14 to 21 | `scripts/grep_secrets.sh`, API tests |

## 3. Test Pyramid Target (rough, for time planning)

About 70 percent unit and contract tests, 20 percent component and integration, 10 percent end-to-end and drills. Do not hand-test what a 10-line unit test can cover.

## 4. Per-Module Test Plans

### 4.1 Collector and security (Member 1) — `collector-security/tests/`

| Area | Tests |
|---|---|
| Generator | Same seed gives same output; every mode (`normal`, `cpu_spike`, `memory_spike`, `latency_spike`, `packet_loss`, `failed_logins`, `sensitive`, `out_of_order`) emits valid contract JSON |
| Normalizer | Units and field names match the contract |
| Allow-list | Unknown field dropped; every allow-listed field kept; per-`event_type` allow-list enforced |
| Secret scrubbing | Fake secrets removed: `AKIAFAKEFAKEFAKE0000`, `password=hunter2-FAKE`, `Bearer FAKE.TOKEN.VALUE`, fake email, fake private IP |
| Redaction | Raw hostname, IP, username, message text never appear in the output payload |
| Pseudonymous ID | Same source gives same `source_id`; different salt gives different ID; ID cannot be turned back into the hostname |
| Aggregation | Window summaries correct for known input |
| Queue and retry | See `RELIABILITY_DESIGN.md` §12 (payload before send, backoff, ack-then-mark, restart, 422, overflow) |
| Egress audit | One audit row per payload; `content_hash` matches the sent bytes; `fields_redacted` lists what was removed |
| Auth | Request carries the collector token; 401 pauses sending without discarding data |
| Logging | Collector logs contain counts, not values |

### 4.2 Backend and database (Member 2) — `backend-database/tests/`

| Area | Tests |
|---|---|
| Schema | Migrations apply on an empty database; constraints present (`payload_id` unique, enum checks) |
| Auth | Missing, invalid, revoked token gives 401; valid token resolves the tenant |
| Tenant isolation | Tenant A token cannot read, list or subscribe to tenant B data on **every** endpoint and WebSocket; body `tenant_id` mismatch rejected |
| Ingest | Valid payload stored; unknown field rejected with `SCHEMA_VALIDATION_FAILED`; oversize body rejected |
| Idempotency | Duplicate gives one row and a no-op 200; concurrent duplicates give one row |
| Out-of-order | Late event returned in event-time order |
| Heartbeat and offline | Heartbeat updates status; silence flips to offline using a fake clock; returns to online on new heartbeat |
| Health history | State change writes one `health_state_history` row; unchanged writes none |
| REST | Response envelope matches `SHARED_CONTRACTS.md` §12; errors match §14 |
| WebSocket | Message `type` values match §13; messages only for the subscriber's tenant |
| Logging | Ingest logs contain no field values from the payload; `request_id` present |

### 4.3 AIOps (Member 3) — `aiops-engine/tests/`

The full table is in `AIOPS_DESIGN.md` §14 and `HEALTH_CLASSIFICATION.md` §12. Core set:

| Area | Tests |
|---|---|
| Baseline | Converges on `ts_baseline_normal`; not poisoned by a long spike |
| Detection | Spike found at the right minute; single outlier suppressed; extreme outlier fires at once; cold start falls back with low confidence |
| Security rule | Failed-login count over the window raises a security anomaly |
| Correlation | CPU plus latency within the window gives one incident; far-apart anomalies give two; tenants never correlate with each other |
| Priority and cause | Score and likely cause present, with evidence list |
| Recommendation | Non-empty `contributing_signals`, text contains observed values, no automation beyond `manual`/`simulated_only` |
| Ordering | Shuffled input gives the same anomalies as sorted input; backlog burst gives historical `opened_at_utc` |
| Health | Every state reachable; worst signal wins; stale never Excellent; hysteresis; config-driven thresholds |

### 4.4 Frontend (Member 4) — `frontend-dashboard/src/**/*.test.tsx`

| Area | Tests |
|---|---|
| Mock mode | `VITE_USE_MOCK=true` renders every page from mock JSON with no backend |
| Pages | Infrastructure, Network, Security, Fleet, Incidents, Recommendations each render with data, empty, loading and error states |
| Egress Proof Panel | Shows the exact payload JSON, the removed-field list, the `content_hash`, delivery status; diff view highlights removed fields |
| Health display | All four states render with reason text and the stale flag |
| Times | UTC values converted for display; late data sorted by `event_time_utc` |
| Types | TypeScript types compile against the sample API responses (type check step) |
| Manual | One screenshot per page for the report |

## 5. Contract Tests

| Check | How |
|---|---|
| Every JSON in `sample-data/` validates against the Pydantic models in `shared/` | `pytest tests/test_contracts.py` at the repository root |
| Frontend types match the same JSON | `npm run typecheck` over `sample-data/api-responses/` |
| Field naming rules (`_utc` suffix, `_pct`, ID prefixes `tenant_`, `coll_`, `src_`, `inc_`, `anom_`, `rec_`, `egress_`, `req_`) | Small script over all sample files |
| Enums (`event_type`, `connectivity_status`, `severity`, `status`, `state`, WebSocket `type`) | Validation against the contract enums |

**Known conflict to resolve before relying on these tests.** `MOCK_DATA_GUIDE.md` and `AIOPS_DESIGN.md` use names such as `tnt_acme_001`, `col_acme_blr_01`, `cpu_percent` and `collected_at_utc`, while `SHARED_CONTRACTS.md` uses `tenant_acme`, `coll_bengaluru_01`, `cpu_pct` and `event_time_utc`. The contracts are authoritative; the other two files need a `FIX`. The contract test above will fail loudly until they agree, which is the point.

## 6. Security and Privacy Tests

| Test | Method | Pass condition |
|---|---|---|
| Fake-secret leak scan | `scripts/grep_secrets.sh` searches `sample-data/` (except `raw/`), backend logs, a database dump, collector payloads | Zero hits for the markers |
| Marker list | `AKIAFAKEFAKEFAKE0000`, `hunter2-FAKE`, `FAKE.TOKEN.VALUE`, the fake email, the fake private IP and hostname | Kept in one file, `shared/fake_secret_markers.txt`, used by every check |
| Egress equals audit | Hash the bytes the backend received and compare with `content_hash` in the audit | Equal |
| Allow-list only | Inspect stored rows | Only allow-listed columns populated |
| Tenant isolation | Cross-tenant requests on every endpoint | All rejected with `TENANT_MISMATCH` or `NOT_FOUND` |
| Token handling | Bad, expired and wrong-tenant tokens | 401 or 403, and an `authentication_audit` row |
| Log hygiene | Log filter tests from `LOGGING_ARCHITECTURE.md` §12 | Pass |
| Repository scan | Secret scanner (or `git grep` for key patterns) | No real credentials committed |

## 7. End-to-End Scenario Matrix

One row per demo scenario. "Command" uses the collector CLI from `SETUP_SCRIPTS.md`. Fill the result column from real runs only.

| # | Scenario | Command | Pass condition | Evidence | Result |
|---|---|---|---|---|---|
| 1 | Normal monitoring | `generate --mode normal` | Dashboards update; health Excellent or Good | Screenshot | |
| 2 | CPU spike | `generate --mode cpu_spike` | CPU anomaly with reason, alert shown | Screenshot, log times | |
| 3 | Memory spike | `generate --mode memory_spike` | Memory anomaly | Screenshot | |
| 4 | Latency spike | `generate --mode latency_spike` | Network anomaly | Screenshot | |
| 5 | Packet loss | `generate --mode packet_loss` | Network anomaly, health drops | Screenshot | |
| 6 | Failed logins | `generate --mode failed_logins` | Security event, no raw usernames or IPs | Screenshot | |
| 7 | Correlation | CPU plus latency together | One incident, not two, rules listed | Incident JSON | |
| 8 | Incident | Same as 7 | Priority and likely cause present | Incident JSON | |
| 9 | Recommendation | Same as 7 | Explanation with evidence | Screenshot | |
| 10 | Redaction | `generate --mode sensitive` | No marker in payload, DB or logs | Leak scan output | |
| 11 | Egress Proof Panel | Any payload | Panel shows exact JSON; hash matches | Screenshot | |
| 12 | SaaS outage | Stop backend | Collector keeps collecting | Collector log | |
| 13 | Local buffering | Same | Queue depth rises | `status` output | |
| 14 | Retry and recovery | Start backend | Backoff then drain | Logs | |
| 15 | Duplicate prevention | `replay --last 20` | Row count unchanged | SQL result | |
| 16 | Out-of-order | `generate --mode out_of_order` | Charts in event-time order | Screenshot | |
| 17 | Offline detection | Kill collector | Offline within target | Measured seconds | |
| 18 | Four health states | Prepared collectors | All four visible with reasons | Screenshot | |

## 8. Performance and Reliability Measurements

Method: timestamps already carried by payloads and logs, computed by `scripts/measure_latency.py` and the outage drill. Report N, conditions and the p95, not a single best run.

| Target | Measure | Samples | Pass if |
|---|---|---|---|
| Collection to dashboard | Dashboard receive time minus `event_time_utc` | At least 100 | p95 ≤ 10 s |
| Breach to alert | Alert shown time minus the first breaching `event_time_utc` | At least 5 spikes | ≤ 15 s |
| Offline detection | Offline flag time minus last heartbeat time | At least 5 kills | ≤ 60 s |
| Backlog | Generated minus stored; duplicate `payload_id` count | At least 3 drills (60 s, 120 s, with restart) | 0 and 0 |

If a target fails: record the real number and the reason. Do not retune the test.

## 9. How to Run (commands to confirm when code exists)

```bash
# per module
cd collector-security && pytest -q
cd backend-database   && pytest -q
cd aiops-engine       && pytest -q
cd frontend-dashboard && npm test && npm run typecheck

# contracts and leak scan (repository root)
pytest tests/test_contracts.py -q
bash scripts/grep_secrets.sh

# integration and drills
docker compose up -d --build
docker compose exec backend python scripts/seed_demo.py
bash scripts/outage_drill.sh 60
python scripts/measure_latency.py
```

## 10. Test Data

| Source | Use |
|---|---|
| `sample-data/raw/` | Fake raw telemetry with fake secrets (Member 1 only) |
| `sample-data/payloads/` | Approved payloads for backend and contract tests |
| `sample-data/timeseries/` | AIOps fixtures with known spike positions in `ts_*.meta.json` |
| `sample-data/api-responses/`, `ws-messages/` | Frontend mocks |
| `sample-data/scenarios/` | Ordered playlists for replay |

All secrets are obviously fake. Never use real credentials, even expired ones.

## 11. Priorities if Time Runs Short

Run in this order and stop when time is up:

1. Fake-secret leak scan and Egress Proof Panel check
2. Idempotency and outage drill
3. Tenant isolation
4. Offline detection measurement
5. Spike → anomaly → incident → recommendation
6. Four health states
7. Frontend rendering and empty states
8. Everything else

Matches the "never cut" list in `HACKATHON_24H_PLAN.md`.

## 12. Definition of Done (per feature)

- [ ] Unit test exists and passes locally, with the command recorded
- [ ] Uses contract field names (contract test passes)
- [ ] No secrets or raw values in logs
- [ ] Error and empty paths handled
- [ ] Mentioned in the module README if it adds a command
- [ ] Row updated in `FINAL_QUALITY_REPORT.md` with evidence, or marked "not tested"

## 13. CI (optional, only if time allows)

A single GitHub Actions workflow running the four module test commands, the contract tests and the leak scan on pushes to `integration`. A local `scripts/run_all_tests.sh` achieves the same without setup and is the fallback. The Docker stack is not run in CI during the hackathon.

## 14. Reporting

After each test round, add a dated line to `FINAL_QUALITY_REPORT.md` section 6 with the command, passed/total, and notes. Defects go in the Defect Log in `INTEGRATION_CHECKLIST.md` with an owner.

## 15. Known Limitations of This Strategy

- No load testing beyond demo scale.
- No browser end-to-end automation; the dashboard is checked by hand and with component tests.
- Real TLS validation and multi-machine clock skew are not covered unless the team runs them on separate machines.
- Test results exist only after they are run; this document is a plan.
