# Collector & Security (`collector-security`)

Local telemetry collector, allow-list enforcement, redaction/pseudonymization pipeline, SQLite queue + egress audit store, and CLI for `smart-observability`.

## Security & Data Boundaries

- **Local-only raw storage:** Raw events stay in local SQLite (`raw_events`) and are never transmitted directly to SaaS.
- **Default-deny allow-list:** Only fields explicitly permitted in `shared/allowlist.json` are included in outbound payloads.
- **Redaction & pseudonymization:** Secrets/sensitive identifiers matching `shared/redaction_rules.json` are redacted, and source identifiers are HMAC-SHA256 pseudonymized with `src_` prefixes.
- **Egress audit trail:** Every queued/sent payload records `fields_sent`, `fields_redacted`, `content_hash`, and timestamps in `egress_audit`.
- **Outbound queue capacity:** `COLLECTOR_QUEUE_MAX_MB` is a binary MiB limit (`1 MiB = 1,048,576 bytes`) over the UTF-8 serialized `body_json` bytes of pending and in-flight payloads. Delivered and rejected rows are excluded; SQLite pages, indexes, and audit rows are not part of this payload-byte limit.
- **Raw event retention:** `COLLECTOR_LOCAL_RETENTION_HOURS` controls expiry by `created_at_utc`. Cleanup runs at collector startup and hourly while `run` is active, once at `generate` startup, or on demand with `PYTHONPATH=collector-security python3 -m collector.cli cleanup`. Cleanup deletes only valid timestamps older than the UTC cutoff and leaves malformed legacy timestamps in place.
- **Egress audit retention:** Audit rows are retained indefinitely; raw-event cleanup never deletes them. The audit table and SQLite database can therefore grow without bound, so operators must monitor disk usage and arrange a separate archival policy if long-term storage limits require one.

## Key CLI Commands

Run from the repository root (`~/projects/smart-observability`) with `.venv` active:

PYTHONPATH=collector-security python3 -m collector.cli status
PYTHONPATH=collector-security python3 -m collector.cli generate --mode normal --count 2
PYTHONPATH=collector-security python3 -m collector.cli replay --last 2
PYTHONPATH=collector-security python3 -m collector.cli audit --last 5

## Production Security Configuration

Set `APP_ENV=production` and configure `SAAS_BASE_URL` with an `https://` endpoint and
`SAAS_VERIFY_TLS=true`. Set `COLLECTOR_TOKEN` to the registered collector credential with at
least 32 UTF-8 bytes. Generate a strong token with Python's `secrets` module, for example:

```sh
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
```

Store the generated value in your deployment secret manager and configure the collector from
that secret; do not print it in deployment logs. Set
`PSEUDONYM_SALT` to at least 32 random bytes with at least 16 distinct characters. The collector
rejects missing or development/default credentials and salts, plaintext HTTP, and disabled TLS
verification in production. For a private certificate authority, set `SAAS_CA_BUNDLE_PATH` to its
trusted CA bundle. Generate and store these values in your deployment secret manager; do not put
production secrets in `.env.example` or source control.

Local `development` and `demo` modes retain the development token and salt defaults and may use
HTTP with `localhost`, a loopback IP address, or the Docker Compose service `backend` on port
`8000`. Other remote backends require HTTPS in every mode. Use `APP_ENV=production` for any
production deployment; production always requires HTTPS and certificate verification, including
when the backend is on the Docker network.

## Verification

PYTHONPATH=collector-security pytest -v collector-security/tests/test_collector.py
./scripts/grep_secrets.sh
