# SECURITY_DESIGN.md

Security is scored directly in Phase 2 (25 marks) and underpins the "proof that raw data stays
local" check in Phase 3 (35 marks). This document is the single reference for every security
control in the system — no member should implement an ad-hoc auth/redaction scheme outside this
design.

---

## 1. Collector Authentication

- Each collector is **registered** with the backend once (via an admin/onboarding flow) and
  receives a unique `collector_id` + a secret credential.
- **MVP approach (24h-feasible):** a per-collector API key, sent as a bearer token on every
  request, checked against a hashed value stored in PostgreSQL (never store the raw key).
- **Stretch goal (if time allows):** mutual TLS with a per-collector client certificate instead
  of/in addition to the API key, for a stronger story in the Phase 2 security-controls
  discussion.
- Every authenticated request is tied to exactly one `collector_id` → exactly one `tenant_id`.
  A collector can never act on behalf of another tenant — this is enforced at the auth
  middleware level, before any handler code runs.
- Failed authentication attempts are logged (collector_id attempted, timestamp, result) — this
  log itself never contains the credential value.

## 2. Transport Encryption

- All collector↔SaaS traffic uses **TLS 1.2+**. No endpoint accepts plaintext HTTP in any
  non-local-dev context.
- WebSocket connections (dashboard↔backend) also run over TLS (`wss://`) in any
  non-local-dev deployment.
- Local collector↔generator/agent communication (entirely within the customer environment) is
  not required to be encrypted for the hackathon scope, since it never crosses the trust
  boundary — documented explicitly as a scope decision, not an oversight.

## 3. Field Allow-Listing (Default-Deny)

This is the single most important security control in the whole system, because it's what makes
"metadata-only" true rather than aspirational.

- For every event type (`infrastructure_metrics`, `network_metrics`, `security_events`,
  `collector_heartbeat`), there is an explicit, versioned allow-list of field names that are
  *permitted* to leave the collector.
- The allow-list validator operates as **default-deny**: any field not explicitly listed is
  dropped, never passed through "just in case." This is enforced in code as a single shared
  function (`shared/allowlist.py` logically; concretely owned by Member 1, schema defined in
  `SHARED_CONTRACTS.md`) that every event passes through before it's eligible for the buffer
  queue — no collector code path may bypass it.
- The allow-list is re-checked, independently, at the SaaS ingestion endpoint (defense in
  depth): if a payload somehow contains a non-allow-listed field, ingestion rejects the whole
  payload rather than silently stripping and accepting it. A rejected payload is logged on the
  SaaS side as a schema violation for investigation — this is a signal that the collector-side
  control has a bug, and should never happen in a correctly functioning system.

## 4. Secret Scrubbing

- Applied to any field that *is* allow-listed but could still carry embedded secrets inside free
  text (e.g. a `message` or `context` field on a security event).
- Pattern-based scrubbing for common secret shapes: API-key-like tokens, bearer tokens,
  password-assignment patterns (`password=...`, `pwd:...`), AWS-key-like strings, and
  credit-card-like digit sequences.
- Scrubbing runs **before** the allow-list check on any free-text field that passes the
  allow-list, so a matched pattern is replaced with a `[REDACTED]` marker rather than ever being
  queued.
- Unit tests (owned by Member 1) assert specific known secret patterns are always caught; this
  is called out as a test obligation, not just a "best effort" feature.

## 5. Sensitive Data Redaction & Pseudonymization

- Any field carrying a real identifier (hostname, username, IP address) that needs to exist for
  correlation purposes — but not to be exposed as-is — is replaced with a **pseudonymous
  source identifier**: `source_id = HMAC(tenant_salt, real_identifier)`.
- The `tenant_salt` lives only on the collector side (per-tenant config), so the SaaS platform
  can consistently correlate events from the same source across time (same `source_id`
  reappears) **without ever being able to reverse it** back to the real hostname/IP/username.
- Raw identifiers are retained only in the local-only raw SQLite store, which the SaaS side has
  no access path to.

## 6. Local Retention & Auditable Transfer Records

- Raw telemetry (with secrets/identifiers intact) lives in a local SQLite store with a
  **configurable retention window** (e.g. 7 days default) after which old raw rows are purged.
- Every payload that is queued for transmission is also written to an **egress audit** table
  locally, recording: `payload_id`, exact field list sent, a content hash, and the timestamp it
  was queued/sent. This is what powers the Egress Proof Panel and gives a durable, inspectable
  record independent of whether the SaaS side received it.
- The audit record is never deleted on the same short cycle as raw data — it's the compliance
  trail, so it's kept longer (documented as a config value, not hardcoded).

## 7. Tenant Isolation (SaaS side)

- Every tenant-scoped table (`telemetry_metadata`, `incidents`, `anomaly_events`,
  `recommendations`, `collectors`, etc.) has a mandatory, indexed `tenant_id` column.
- All reads/writes go through a shared data-access layer that **requires** a `tenant_id` and
  injects it into the `WHERE` clause automatically — individual endpoint handlers cannot
  "forget" to scope a query, because the unscoped query function doesn't exist.
- `tenant_id` is derived server-side from the authenticated collector/user session — it is
  **never** accepted as a client-supplied parameter that could be spoofed to view another
  tenant's data.
- Unit test obligation (Member 2): an authenticated request for tenant A attempting to fetch a
  resource ID belonging to tenant B must return "not found," not the resource and not an error
  that reveals the resource exists.

## 8. Logging Discipline

Applies to every workspace, not just the security module:

- Collector-side logs: may reference field *names* that were redacted/dropped, never the actual
  secret/sensitive values.
- SaaS-side logs: must never contain raw telemetry content — only metadata that was already
  legitimately allow-listed, plus operational info (request IDs, timestamps, status codes).
- Authentication logs record attempt metadata, never the credential itself.
- See `LOGGING_ARCHITECTURE.md` (Batch 5) for the full structured-logging spec across all
  workspaces.

## 9. What This Design Explicitly Does Not Attempt (24h scope)

- Full key-rotation/secret-management infrastructure for collector credentials — a single
  stored hashed key per collector is sufficient for the hackathon demo; documented as a
  production gap, not hidden.
- Formal encryption-at-rest for PostgreSQL beyond standard managed-Postgres defaults — noted as
  a production consideration in `FINAL_QUALITY_REPORT.md` (Batch 8), not built.
- Real policy-engine-gated Autonomous Ops execution — Stage 5 stays simulated per
  `MASTER_PROJECT.md` §7.
