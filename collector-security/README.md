# Collector & Security (`collector-security`)

Local telemetry collector, allow-list enforcement, redaction/pseudonymization pipeline, SQLite queue + egress audit store, and CLI for `smart-observability`.

## Security & Data Boundaries

- **Local-only raw storage:** Raw events stay in local SQLite (`raw_events`) and are never transmitted directly to SaaS.
- **Default-deny allow-list:** Only fields explicitly permitted in `shared/allowlist.json` are included in outbound payloads.
- **Redaction & pseudonymization:** Secrets/sensitive identifiers matching `shared/redaction_rules.json` are redacted, and source identifiers are HMAC-SHA256 pseudonymized with `src_` prefixes.
- **Egress audit trail:** Every queued/sent payload records `fields_sent`, `fields_redacted`, `content_hash`, and timestamps in `egress_audit`.

## Key CLI Commands

Run from the repository root (`~/projects/smart-observability`) with `.venv` active:

PYTHONPATH=collector-security python3 -m collector.cli status
PYTHONPATH=collector-security python3 -m collector.cli generate --mode normal --count 2
PYTHONPATH=collector-security python3 -m collector.cli replay --last 2
PYTHONPATH=collector-security python3 -m collector.cli audit --last 5

## Verification

PYTHONPATH=collector-security pytest -v collector-security/tests/test_collector.py
./scripts/grep_secrets.sh
