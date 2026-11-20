from __future__ import annotations

import json
import logging
import multiprocessing
import random
import secrets
import sqlite3
import sys
import time
from io import StringIO
from pathlib import Path
from typing import Any

import pytest
import requests

from collector.allowlist import AllowlistValidator
from collector.cli import _cmd_cleanup
from collector.config import CollectorConfig, CollectorConfigurationError
from collector.generator import TelemetryGenerator
from collector.logger import RedactionLogFilter
from collector.pipeline import CollectorPipeline
from collector.redaction import RedactionEngine, pseudonymize_source_id
from collector.sender import CollectorSender, compute_backoff_delay
import collector.store as store_module
from collector.store import CollectorStore, DuplicatePayloadConflict, QueueCapacityExceeded
from collector.store import MAX_STORED_ERROR_LENGTH


def _claim_then_hold_store(
    db_path: str, start_event: Any, claimed_event: Any, release_event: Any, result_queue: Any
) -> None:
    store = CollectorStore(Path(db_path))
    try:
        start_event.wait(timeout=10)
        claimed = store.fetch_due_batch(batch_size=20, now_utc="2999-01-01T00:00:00Z")
        result_queue.put([item["payload_id"] for item in claimed])
        claimed_event.set()
        release_event.wait(timeout=15)
    except Exception as exc:
        result_queue.put({"error": repr(exc)})
    finally:
        store.close()


def _open_and_claim_after_first_claim(
    db_path: str, claimed_event: Any, result_queue: Any
) -> None:
    try:
        if not claimed_event.wait(timeout=10):
            raise TimeoutError("first process did not claim its batch")
        store = CollectorStore(Path(db_path))
        try:
            claimed = store.fetch_due_batch(batch_size=20, now_utc="2999-01-01T00:00:00Z")
            result_queue.put([item["payload_id"] for item in claimed])
        finally:
            store.close()
    except Exception as exc:
        result_queue.put({"error": repr(exc)})


def _hold_exclusive_recovery_before_recovery(
    db_path: str, acquired_event: Any
) -> None:
    original_recovery = CollectorStore.recover_inflight

    def blocked_recovery(store: CollectorStore) -> int:
        acquired_event.set()
        time.sleep(60)
        return original_recovery(store)

    CollectorStore.recover_inflight = blocked_recovery
    CollectorStore(Path(db_path))


def _construct_after_exclusive_owner_dies(
    db_path: str, attempting_event: Any, result_queue: Any
) -> None:
    original_flock = store_module.fcntl.flock

    def observe_lock_attempt(fd: int, operation: int) -> None:
        if operation & store_module.fcntl.LOCK_EX:
            attempting_event.set()
        original_flock(fd, operation)

    store_module.fcntl.flock = observe_lock_attempt
    try:
        store = CollectorStore(Path(db_path))
        try:
            result_queue.put(store.get_queue_stats())
        finally:
            store.close()
    except Exception as exc:
        result_queue.put({"error": repr(exc)})

BACKEND_ROOT = Path(__file__).resolve().parents[2] / "backend-database"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.schemas.telemetry import (  # noqa: E402
    CollectorHeartbeat,
    TelemetryEventCreate,
    TelemetryEventResponse,
)


class _DummyResponse:
    def __init__(self, status_code: int, text: str = "") -> None:
        self.status_code = status_code
        self.text = text


class _DummySession:
    def __init__(self, responses: list[_DummyResponse | Exception]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def post(self, url: str, **kwargs: Any) -> _DummyResponse:
        self.calls.append({"url": url, "kwargs": kwargs})
        nxt = self.responses.pop(0) if self.responses else _DummyResponse(200, '{"status":"ok"}')
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


def test_allowlist_default_deny_and_strict_reject() -> None:
    validator = AllowlistValidator.from_file(Path("shared/allowlist.json"))
    env = {
        "payload_id": "p-100",
        "tenant_id": "tnt_acme_001",
        "collector_id": "col_acme_blr_01",
        "source_id": "src_abcdef1234",
        "event_type": "infrastructure",
        "event_time_utc": "2026-11-20T10:15:03Z",
        "source_timezone": "Asia/Kolkata",
        "received_at_utc": "2026-11-20T10:15:03Z",
        "raw_hostname": "db-01.internal",
        "data": {
            "cpu_pct": 44.2,
            "memory_pct": 61.0,
            "disk_pct": 70.0,
            "service_available": True,
            "service_name": "api",
            "password": "hunter2-FAKE",
            "raw_ip": "10.0.0.9",
        },
    }

    filtered, dropped = validator.validate_and_filter(env, strict_reject=False)
    assert "raw_hostname" not in filtered
    assert "password" not in filtered["data"]
    assert "raw_ip" not in filtered["data"]
    assert filtered["data"]["cpu_pct"] == 44.2
    assert set(dropped) == {"received_at_utc", "raw_hostname", "data.password", "data.raw_ip"}

    with pytest.raises(ValueError):
        validator.validate_and_filter(env, strict_reject=True)


def test_secret_scrubbing_and_pseudonymization() -> None:
    redactor = RedactionEngine.from_rules_file(
        Path("shared/redaction_rules.json"), pseudonym_salt="salt-1"
    )
    dirty = (
        "Alert key=AKIAFAKEFAKEFAKE0000 password=hunter2-FAKE "
        "auth=Bearer FAKE.TOKEN.VALUE user=alice@acme.example ip=192.168.1.50"
    )
    cleaned, rules = redactor.scrub_string(dirty)
    assert "AKIAFAKEFAKEFAKE0000" not in cleaned
    assert "hunter2-FAKE" not in cleaned
    assert "FAKE.TOKEN.VALUE" not in cleaned
    assert "alice@acme.example" not in cleaned
    assert "192.168.1.50" not in cleaned
    assert "[REDACTED]" in cleaned
    assert len(rules) >= 4

    s1 = pseudonymize_source_id("db-primary.internal", "salt-1")
    s1_again = pseudonymize_source_id("db-primary.internal", "salt-1")
    s2_diff_salt = pseudonymize_source_id("db-primary.internal", "salt-2")
    assert s1.startswith("src_")
    assert s1 == s1_again
    assert s1 != s2_diff_salt
    assert "db-primary" not in s1


def test_auth_failure_burst_summarization_and_local_raw_store(tmp_path: Path) -> None:
    cfg = CollectorConfig(
        sqlite_path=tmp_path / "collector.db",
        log_file_path=tmp_path / "collector.log",
        auth_failure_burst_threshold=3,
        auth_failure_window_seconds=60,
    )
    store = CollectorStore(cfg.sqlite_path)
    pipe = CollectorPipeline(cfg, store)

    emitted_types: list[str] = []
    for i in range(4):
        res = pipe.process_raw_event(
            {
                "event_type": "auth_failure_raw",
                "host": "auth-srv-01.internal",
                "raw_ip": "198.51.100.10",
                "raw_user": "bob@acme.example",
                "event_time_utc": f"2026-11-20T10:15:0{i}Z",
                "source_timezone": "Asia/Kolkata",
                "reason": "bad password=hunter2-FAKE",
            }
        )
        if res is not None:
            emitted_types.append(res["envelope"]["event_type"])
            assert "bob@acme.example" not in json.dumps(res["envelope"])
            assert "198.51.100.10" not in json.dumps(res["envelope"])
            assert "hunter2-FAKE" not in json.dumps(res["envelope"])

    assert emitted_types == ["security", "security"]
    raw_rows = store.conn.execute("SELECT COUNT(*) AS c FROM raw_events;").fetchone()["c"]
    assert raw_rows == 4
    store.close()


def test_store_crash_recovery_and_sender_outcomes(tmp_path: Path) -> None:
    db_path = tmp_path / "queue.db"
    store = CollectorStore(db_path)
    cfg = CollectorConfig(
        sqlite_path=db_path,
        log_file_path=tmp_path / "collector.log",
        saas_base_url="http://localhost:8000",
    )

    env = {
        "payload_id": "11111111-1111-4111-8111-111111111111",
        "tenant_id": "tnt_acme_001",
        "collector_id": "col_acme_blr_01",
        "source_id": "src_1111111111",
        "event_type": "network_metrics",
        "event_time_utc": "2026-11-20T10:15:03Z",
        "source_timezone": "Asia/Kolkata",
        "received_at_utc": "2026-11-20T10:15:03Z",
        "data": {
            "bandwidth_mbps": 500.0,
            "latency_ms": 20.0,
            "packet_loss_pct": 0.0,
            "connectivity_status": "up",
        },
    }
    store.enqueue_payload(env, fields_redacted=[])

    # Mark in_flight and simulate restart recovery
    due = store.fetch_due_batch(batch_size=1)
    assert len(due) == 1
    store.close()

    reopened = CollectorStore(db_path)
    assert reopened.get_queue_stats()["pending"] == 1

    # Transient failure -> retry scheduled, then 200 -> delivered
    sess = _DummySession([_DummyResponse(503, "unavailable"), _DummyResponse(200, '{"status":"ok"}')])
    sender = CollectorSender(cfg, reopened, session=sess, rng=random.Random(42))
    r1 = sender.send_batch_once(batch_size=1)
    assert r1["failed"] == 1
    assert reopened.get_queue_stats()["pending"] == 1

    # Reset next_attempt_utc to now for immediate second attempt
    reopened.conn.execute("UPDATE outbound_queue SET next_attempt_utc = '2000-01-01T00:00:00Z';")
    reopened.conn.commit()

    r2 = sender.send_batch_once(batch_size=1)
    assert r2["sent"] == 1
    assert reopened.get_queue_stats()["delivered"] == 1
    reopened.close()


def test_backoff_progression_and_log_filter() -> None:
    rng = random.Random(42)
    d1 = compute_backoff_delay(1, initial_delay=1.0, backoff_factor=2.0, max_delay=60.0, jitter_max=0.5, rng=rng)
    d2 = compute_backoff_delay(2, initial_delay=1.0, backoff_factor=2.0, max_delay=60.0, jitter_max=0.5, rng=rng)
    d8 = compute_backoff_delay(8, initial_delay=1.0, backoff_factor=2.0, max_delay=60.0, jitter_max=0.5, rng=rng)
    assert 1.0 <= d1 <= 1.5
    assert 2.0 <= d2 <= 2.5
    assert 60.0 <= d8 <= 60.5

    flt = RedactionLogFilter()
    assert "[REDACTED]" in flt.scrub_text("token=Bearer SECRET123")
    sanitized = flt.sanitize_dict({"password": "abc", "count": 3})
    assert sanitized == {"password": "[REDACTED]", "count": 3}


def test_generator_determinism() -> None:
    g1 = TelemetryGenerator(seed=42, mode="cpu_spike")
    g2 = TelemetryGenerator(seed=42, mode="cpu_spike")
    b1 = g1.generate_raw_batch(now_utc=__import__("datetime").datetime(2026, 11, 20, 10, 0, 0, tzinfo=__import__("datetime").timezone.utc))
    b2 = g2.generate_raw_batch(now_utc=__import__("datetime").datetime(2026, 11, 20, 10, 0, 0, tzinfo=__import__("datetime").timezone.utc))
    assert b1[0]["cpu_pct"] == b2[0]["cpu_pct"]
    assert b1[0]["cpu_pct"] >= 92.0


def test_auth_pause_and_422_non_blocking_queue(tmp_path: Path) -> None:
    db_path = tmp_path / "edge.db"
    store = CollectorStore(db_path)
    cfg = CollectorConfig(
        sqlite_path=db_path,
        log_file_path=tmp_path / "collector.log",
        saas_base_url="http://localhost:8000",
    )

    base_env = {
        "tenant_id": "tnt_acme_001",
        "collector_id": "col_acme_blr_01",
        "source_id": "src_9999999999",
        "event_type": "infrastructure",
        "event_time_utc": "2026-11-20T10:15:03Z",
        "source_timezone": "Asia/Kolkata",
        "received_at_utc": "2026-11-20T10:15:03Z",
        "data": {
            "cpu_pct": 50.0,
            "memory_pct": 55.0,
            "disk_pct": 60.0,
            "service_available": True,
            "service_name": "worker",
        },
    }
    e1 = dict(base_env, payload_id="22222222-2222-4222-8222-222222222221")
    e2 = dict(base_env, payload_id="22222222-2222-4222-8222-222222222222")
    store.enqueue_payload(e1, fields_redacted=[])
    store.enqueue_payload(e2, fields_redacted=[])

    # First item gets 422 (permanently rejected), second item gets 200 (delivered)
    sess1 = _DummySession([_DummyResponse(422, "schema error"), _DummyResponse(200, '{"status":"ok"}')])
    sender1 = CollectorSender(cfg, store, session=sess1, rng=random.Random(42))
    res1 = sender1.send_batch_once(batch_size=2)
    assert res1["rejected"] == 1
    assert res1["sent"] == 1
    stats1 = store.get_queue_stats()
    assert stats1["rejected"] == 1
    assert stats1["delivered"] == 1

    # Enqueue a third item and simulate 401 auth failure -> pauses sending, keeps pending
    e3 = dict(base_env, payload_id="22222222-2222-4222-8222-222222222223")
    store.enqueue_payload(e3, fields_redacted=[])
    sess2 = _DummySession([_DummyResponse(401, "unauthorized")])
    sender2 = CollectorSender(cfg, store, session=sess2, rng=random.Random(42))
    res2 = sender2.send_batch_once(batch_size=1)
    assert res2["paused_auth"] is True
    assert store.get_queue_stats()["pending"] == 1

    # Subsequent call while auth_paused is True does not hit network
    res3 = sender2.send_batch_once(batch_size=1)
    assert res3["paused_auth"] is True
    assert len(sess2.calls) == 1
    store.close()


def test_auth_failure_reschedules_every_unprocessed_claimed_payload(tmp_path: Path) -> None:
    db_path = tmp_path / "auth_batch_pause.db"
    store = CollectorStore(db_path)
    cfg = CollectorConfig(
        sqlite_path=db_path,
        log_file_path=tmp_path / "auth_batch_pause.log",
        saas_base_url="http://localhost:8000",
        retry_initial_delay_seconds=30,
        retry_jitter_seconds=0,
    )
    payload_ids = ["auth-batch-1", "auth-batch-2", "auth-batch-3"]
    try:
        for payload_id in payload_ids:
            store.enqueue_payload(_duplicate_test_payload(payload_id), fields_redacted=[])

        session = _DummySession([_DummyResponse(401, "unauthorized")])
        sender = CollectorSender(cfg, store, session=session, rng=random.Random(42))
        result = sender.send_batch_once(batch_size=3)

        rows = store.conn.execute(
            "SELECT payload_id, status, attempts, last_error FROM outbound_queue "
            "ORDER BY payload_id"
        ).fetchall()
        assert result == {"sent": 0, "failed": 3, "rejected": 0, "paused_auth": True}
        assert sender.auth_paused is True
        assert len(session.calls) == 1
        assert [row["payload_id"] for row in rows] == sorted(payload_ids)
        assert all(row["status"] == "pending" for row in rows)
        assert all(row["attempts"] == 1 for row in rows)
        assert all("authentication_error" in row["last_error"] for row in rows)
        assert store.get_queue_stats()["in_flight"] == 0
    finally:
        store.close()


def test_replay_preserves_payload_id_and_hash(tmp_path: Path) -> None:
    db_path = tmp_path / "replay.db"
    store = CollectorStore(db_path)
    cfg = CollectorConfig(
        sqlite_path=db_path,
        log_file_path=tmp_path / "collector.log",
        saas_base_url="http://localhost:8000",
    )

    env = {
        "payload_id": "33333333-3333-4333-8333-333333333331",
        "tenant_id": "tnt_acme_001",
        "collector_id": "col_acme_blr_01",
        "source_id": "src_3333333333",
        "event_type": "infrastructure",
        "event_time_utc": "2026-11-20T10:15:03Z",
        "source_timezone": "Asia/Kolkata",
        "received_at_utc": "2026-11-20T10:15:03Z",
        "data": {
            "cpu_pct": 65.0,
            "memory_pct": 70.0,
            "disk_pct": 55.0,
            "service_available": True,
            "service_name": "billing-api",
        },
    }
    enq = store.enqueue_payload(env, fields_redacted=[])
    sess = _DummySession([_DummyResponse(200, '{"status":"ok"}'), _DummyResponse(200, '{"status":"ok"}')])
    sender = CollectorSender(cfg, store, session=sess, rng=random.Random(42))

    first = sender.send_batch_once(batch_size=1)
    assert first["sent"] == 1
    assert store.get_queue_stats()["delivered"] == 1

    store.reschedule_retry(env["payload_id"], delay_seconds=0.0, error_msg="replay")
    assert store.get_queue_stats()["pending"] == 1

    due = store.fetch_due_batch(batch_size=1)
    assert len(due) == 1
    assert due[0]["payload_id"] == env["payload_id"]
    assert due[0]["content_hash"] == enq["content_hash"]
    assert due[0]["attempts"] == 2
    store.close()


def test_sender_accepts_201(tmp_path: Path) -> None:
    db_path = tmp_path / "status_codes.db"
    store = CollectorStore(db_path)
    cfg = CollectorConfig(
        sqlite_path=db_path,
        log_file_path=tmp_path / "collector.log",
        saas_base_url="http://127.0.0.1:8000",
    )

    env1 = {
        "payload_id": "44444444-4444-4444-8444-444444444441",
        "tenant_id": "tnt_acme_001",
        "collector_id": "col_acme_blr_01",
        "source_id": "src_4444444444",
        "event_type": "infrastructure",
        "event_time_utc": "2026-11-20T10:15:03Z",
        "source_timezone": "Asia/Kolkata",
        "received_at_utc": "2026-11-20T10:15:03Z",
        "data": {
            "cpu_pct": 50.0,
            "memory_pct": 60.0,
            "disk_pct": 40.0,
            "service_available": True,
            "service_name": "api-gw",
        },
    }
    store.enqueue_payload(env1, fields_redacted=[])

    sess = _DummySession([_DummyResponse(201, '{"status":"created"}')])
    sender = CollectorSender(cfg, store, session=sess, rng=random.Random(42))
    res = sender.send_batch_once(batch_size=1)
    assert res["sent"] == 1
    assert res["failed"] == 0
    assert store.get_queue_stats()["delivered"] == 1
    store.close()


@pytest.mark.parametrize(
    ("verify_tls", "ca_bundle_path", "expected_verify"),
    [
        (False, "", False),
        (True, "", True),
        (True, "/tmp/test-ca-bundle.pem", "/tmp/test-ca-bundle.pem"),
    ],
)
def test_sender_passes_tls_verification_setting_to_http_client(
    tmp_path: Path,
    verify_tls: bool,
    ca_bundle_path: str,
    expected_verify: bool | str,
) -> None:
    db_path = tmp_path / f"tls_verify_{verify_tls}_{bool(ca_bundle_path)}.db"
    store = CollectorStore(db_path)
    cfg = CollectorConfig(
        sqlite_path=db_path,
        log_file_path=tmp_path / "tls_verify.log",
        saas_base_url="https://mock-saas:8000",
        saas_verify_tls=verify_tls,
        saas_ca_bundle_path=ca_bundle_path,
    )
    store.enqueue_payload(_duplicate_test_payload("tls-verification-payload"), fields_redacted=[])
    session = _DummySession([_DummyResponse(200)])
    sender = CollectorSender(cfg, store, session=session, rng=random.Random(42))

    try:
        result = sender.send_batch_once(batch_size=1)
        assert result["sent"] == 1
        assert len(session.calls) == 1
        assert session.calls[0]["kwargs"]["verify"] == expected_verify
    finally:
        store.close()


def test_sender_treats_actual_http_409_as_idempotently_delivered(tmp_path: Path) -> None:
    db_path = tmp_path / "actual_409.db"
    store = CollectorStore(db_path)
    cfg = CollectorConfig(
        sqlite_path=db_path,
        log_file_path=tmp_path / "actual_409.log",
        saas_base_url="http://localhost:8000",
    )
    payload = _duplicate_test_payload("actual-http-409-payload")
    store.enqueue_payload(payload, fields_redacted=["data.private"])
    audit_before = dict(
        store.conn.execute(
            "SELECT * FROM egress_audit WHERE payload_id = ?", (payload["payload_id"],)
        ).fetchone()
    )
    sender = CollectorSender(
        cfg,
        store,
        session=_DummySession([_DummyResponse(409, "duplicate payload")]),
        rng=random.Random(42),
    )

    try:
        result = sender.send_batch_once(batch_size=1)
        queue_row = store.conn.execute(
            "SELECT * FROM outbound_queue WHERE payload_id = ?", (payload["payload_id"],)
        ).fetchone()
        audit_after = dict(
            store.conn.execute(
                "SELECT * FROM egress_audit WHERE payload_id = ?", (payload["payload_id"],)
            ).fetchone()
        )

        assert result["sent"] == 1
        assert result["failed"] == 0
        assert result["rejected"] == 0
        assert queue_row["status"] == "delivered"
        assert queue_row["attempts"] == 1
        assert queue_row["delivered_at_utc"] is not None
        assert audit_after["audit_id"] == audit_before["audit_id"]
        assert audit_after["payload_id"] == audit_before["payload_id"]
        assert audit_after["fields_sent"] == audit_before["fields_sent"]
        assert audit_after["fields_redacted"] == audit_before["fields_redacted"]
        assert audit_after["content_hash"] == audit_before["content_hash"]
        assert audit_after["queued_at_utc"] == audit_before["queued_at_utc"]
        assert audit_after["sent_at_utc"] is not None
        assert store.conn.execute(
            "SELECT COUNT(*) FROM egress_audit WHERE payload_id = ?", (payload["payload_id"],)
        ).fetchone()[0] == 1
    finally:
        store.close()


def test_generator_failed_logins_and_out_of_order_modes() -> None:
    from datetime import datetime, timezone
    gen = TelemetryGenerator(seed=42, mode="failed_logins", source_timezone="Asia/Kolkata")
    burst_events = gen.generate_raw_batch(
        now_utc=datetime(2026, 11, 20, 10, 15, 0, tzinfo=timezone.utc),
        mode="failed_logins",
    )
    assert len(burst_events) >= 1

    ooo_events = gen.generate_raw_batch(
        now_utc=datetime(2026, 11, 20, 10, 15, 0, tzinfo=timezone.utc),
        mode="out_of_order",
    )
    assert len(ooo_events) >= 1
    assert all(isinstance(ev, dict) and len(ev) > 0 for ev in ooo_events)


def test_pipeline_payloads_match_backend_contract_and_required_fields(tmp_path: Path) -> None:
    cfg = CollectorConfig(
        sqlite_path=tmp_path / "contract.db",
        log_file_path=tmp_path / "contract.log",
        auth_failure_burst_threshold=1,
    )
    store = CollectorStore(cfg.sqlite_path)
    pipe = CollectorPipeline(cfg, store)
    now = "2026-11-20T10:15:03Z"
    base = {"host": "contract-host.internal", "event_time_utc": now}
    raw_events = [
        {
            **base,
            "event_type": "infrastructure_metrics",
            "cpu_pct": 40,
            "memory_pct": 50,
            "disk_pct": 60,
            "service_available": True,
            "service_name": "api",
        },
        {
            **base,
            "event_type": "network_metrics",
            "bandwidth_mbps": 100,
            "latency_ms": 10,
            "packet_loss_pct": 0,
            "connectivity_status": "up",
        },
        {
            **base,
            "event_type": "auth_failure_raw",
            "reason": "invalid password=not-a-real-secret",
        },
    ]

    try:
        emitted = [pipe.process_raw_event(event) for event in raw_events]
        payloads = [item["envelope"] for item in emitted if item is not None]
        heartbeat = pipe.build_heartbeat_payload()
        payloads.append(heartbeat)

        assert {payload["event_type"] for payload in payloads} == {
            "infrastructure",
            "network",
            "security",
            "heartbeat",
        }
        required = {
            "payload_id",
            "tenant_id",
            "collector_id",
            "source_id",
            "event_type",
            "event_time_utc",
            "source_timezone",
            "data",
        }
        for payload in payloads:
            assert required <= payload.keys()
            assert "received_at_utc" not in payload
            TelemetryEventCreate.model_validate(payload)

        CollectorHeartbeat.model_validate(heartbeat["data"])
        response_payload = {**payloads[0], "received_at_utc": now}
        TelemetryEventResponse.model_validate(response_payload)
    finally:
        store.close()


def test_allowlist_requires_envelope_fields_and_rejects_unsupported_event_type() -> None:
    validator = AllowlistValidator.from_file(Path("shared/allowlist.json"))
    with pytest.raises(ValueError, match="Required envelope fields missing"):
        validator.validate_and_filter(
            {"event_type": "infrastructure", "data": {"cpu_pct": 1.0}}
        )

    with pytest.raises(ValueError, match="Unsupported or missing event_type"):
        validator.validate_and_filter(
            {
                "payload_id": "p-1",
                "tenant_id": "tenant-1",
                "collector_id": "collector-1",
                "source_id": "src_1234567890",
                "event_type": "infrastructure_metrics",
                "event_time_utc": "2026-11-20T10:15:03Z",
                "source_timezone": "UTC",
                "data": {"cpu_pct": 1.0},
            }
        )


def _duplicate_test_payload(payload_id: str, cpu_pct: float = 42.0) -> dict[str, Any]:
    return {
        "payload_id": payload_id,
        "tenant_id": "tenant_duplicate_test",
        "collector_id": "collector_duplicate_test",
        "source_id": "src_1234567890",
        "event_type": "infrastructure",
        "event_time_utc": "2026-11-20T10:15:03Z",
        "source_timezone": "UTC",
        "data": {
            "cpu_pct": cpu_pct,
            "memory_pct": 50.0,
            "disk_pct": 60.0,
            "service_available": True,
            "service_name": "api",
        },
    }


def test_new_payload_is_inserted_with_one_audit_record(tmp_path: Path) -> None:
    store = CollectorStore(tmp_path / "new_payload.db")
    try:
        result = store.enqueue_payload(
            _duplicate_test_payload("duplicate-test-new"), fields_redacted=[]
        )
        queue_rows = store.conn.execute(
            "SELECT * FROM outbound_queue WHERE payload_id = ?",
            ("duplicate-test-new",),
        ).fetchall()
        audit_rows = store.conn.execute(
            "SELECT * FROM egress_audit WHERE payload_id = ?",
            ("duplicate-test-new",),
        ).fetchall()

        assert result["duplicate"] is False
        assert len(queue_rows) == 1
        assert queue_rows[0]["status"] == "pending"
        assert len(audit_rows) == 1
        assert audit_rows[0]["audit_id"] == result["audit_id"]
    finally:
        store.close()


def test_identical_duplicate_preserves_queue_and_audit_history(tmp_path: Path) -> None:
    store = CollectorStore(tmp_path / "identical_duplicate.db")
    payload = _duplicate_test_payload("duplicate-test-identical")
    try:
        first = store.enqueue_payload(payload, fields_redacted=["data.secret"])
        before_queue = dict(
            store.conn.execute(
                "SELECT * FROM outbound_queue WHERE payload_id = ?",
                (payload["payload_id"],),
            ).fetchone()
        )
        before_audit = [
            dict(row)
            for row in store.conn.execute(
                "SELECT * FROM egress_audit WHERE payload_id = ?",
                (payload["payload_id"],),
            ).fetchall()
        ]

        second = store.enqueue_payload(payload, fields_redacted=["different.audit.marker"])

        after_queue = dict(
            store.conn.execute(
                "SELECT * FROM outbound_queue WHERE payload_id = ?",
                (payload["payload_id"],),
            ).fetchone()
        )
        after_audit = [
            dict(row)
            for row in store.conn.execute(
                "SELECT * FROM egress_audit WHERE payload_id = ?",
                (payload["payload_id"],),
            ).fetchall()
        ]

        assert second["duplicate"] is True
        assert second["audit_id"] == first["audit_id"]
        assert after_queue == before_queue
        assert after_audit == before_audit
        assert store.conn.execute(
            "SELECT COUNT(*) FROM outbound_queue WHERE payload_id = ?",
            (payload["payload_id"],),
        ).fetchone()[0] == 1
    finally:
        store.close()


def test_identical_duplicate_does_not_reset_delivered_status(tmp_path: Path) -> None:
    store = CollectorStore(tmp_path / "delivered_duplicate.db")
    payload = _duplicate_test_payload("duplicate-test-delivered")
    try:
        first = store.enqueue_payload(payload, fields_redacted=[])
        store.mark_delivered(payload["payload_id"], delivered_at_utc="2026-11-20T10:16:00Z")
        before_queue = dict(
            store.conn.execute(
                "SELECT * FROM outbound_queue WHERE payload_id = ?",
                (payload["payload_id"],),
            ).fetchone()
        )
        before_audit = [
            dict(row)
            for row in store.conn.execute(
                "SELECT * FROM egress_audit WHERE payload_id = ?",
                (payload["payload_id"],),
            ).fetchall()
        ]

        result = store.enqueue_payload(payload, fields_redacted=[])

        after_queue = dict(
            store.conn.execute(
                "SELECT * FROM outbound_queue WHERE payload_id = ?",
                (payload["payload_id"],),
            ).fetchone()
        )
        after_audit = [
            dict(row)
            for row in store.conn.execute(
                "SELECT * FROM egress_audit WHERE payload_id = ?",
                (payload["payload_id"],),
            ).fetchall()
        ]

        assert result["duplicate"] is True
        assert result["audit_id"] == first["audit_id"]
        assert after_queue == before_queue
        assert after_queue["status"] == "delivered"
        assert after_audit == before_audit
    finally:
        store.close()


def test_different_content_with_same_id_is_rejected_without_mutation(tmp_path: Path) -> None:
    store = CollectorStore(tmp_path / "conflicting_duplicate.db")
    payload = _duplicate_test_payload("duplicate-test-conflict")
    try:
        first = store.enqueue_payload(payload, fields_redacted=["data.secret"])
        store.mark_delivered(payload["payload_id"], delivered_at_utc="2026-11-20T10:16:00Z")
        before_queue = dict(
            store.conn.execute(
                "SELECT * FROM outbound_queue WHERE payload_id = ?",
                (payload["payload_id"],),
            ).fetchone()
        )
        before_audit = [
            dict(row)
            for row in store.conn.execute(
                "SELECT * FROM egress_audit WHERE payload_id = ?",
                (payload["payload_id"],),
            ).fetchall()
        ]
        changed_payload = _duplicate_test_payload(
            payload["payload_id"], cpu_pct=99.0
        )

        with pytest.raises(DuplicatePayloadConflict, match="already exists with different content"):
            store.enqueue_payload(changed_payload, fields_redacted=["different.audit.marker"])

        after_queue = dict(
            store.conn.execute(
                "SELECT * FROM outbound_queue WHERE payload_id = ?",
                (payload["payload_id"],),
            ).fetchone()
        )
        after_audit = [
            dict(row)
            for row in store.conn.execute(
                "SELECT * FROM egress_audit WHERE payload_id = ?",
                (payload["payload_id"],),
            ).fetchall()
        ]

        assert after_queue == before_queue
        assert after_queue["body_json"] == json.dumps(payload, separators=(",", ":"), sort_keys=True)
        assert after_audit == before_audit
        assert after_audit[0]["audit_id"] == first["audit_id"]
    finally:
        store.close()


def _set_production_config_env(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> None:
    values = {
        "APP_ENV": "production",
        "SAAS_BASE_URL": "https://ingest.example.test",
        "SAAS_VERIFY_TLS": "true",
        "COLLECTOR_TOKEN": secrets.token_urlsafe(32),
        "PSEUDONYM_SALT": secrets.token_urlsafe(32),
    }
    values.update(overrides)
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def test_production_configuration_accepts_secure_settings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    token = secrets.token_urlsafe(32)
    salt = secrets.token_urlsafe(32)
    _set_production_config_env(
        monkeypatch,
        COLLECTOR_TOKEN=token,
        PSEUDONYM_SALT=salt,
    )

    config = CollectorConfig.from_env(tmp_path / "no-config.env")

    assert config.app_env == "production"
    assert config.saas_base_url == "https://ingest.example.test"
    assert config.saas_verify_tls is True
    assert config.collector_token == token
    assert config.pseudonym_salt == salt
    assert token not in repr(config)
    assert salt not in repr(config)


@pytest.mark.parametrize(
    ("override", "expected_message", "sensitive_value"),
    [
        ({"SAAS_BASE_URL": "http://ingest.example.test"}, "SAAS_BASE_URL must use HTTPS", ""),
        ({"SAAS_BASE_URL": "http://backend:8000"}, "SAAS_BASE_URL must use HTTPS", ""),
        ({"SAAS_VERIFY_TLS": "false"}, "SAAS_VERIFY_TLS must be true", ""),
        ({"COLLECTOR_TOKEN": "dev-collector-token"}, "COLLECTOR_TOKEN must be a non-default", "dev-collector-token"),
        ({"COLLECTOR_TOKEN": "short"}, "COLLECTOR_TOKEN must be a non-default", "short"),
        ({"COLLECTOR_TOKEN": ""}, "COLLECTOR_TOKEN must be a non-default", ""),
        ({"PSEUDONYM_SALT": "short-salt"}, "PSEUDONYM_SALT must be", "short-salt"),
        (
            {"PSEUDONYM_SALT": "replace-with-generated-salt"},
            "PSEUDONYM_SALT must be",
            "replace-with-generated-salt",
        ),
    ],
)
def test_production_configuration_rejects_insecure_settings_without_echoing_values(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    override: dict[str, str],
    expected_message: str,
    sensitive_value: str,
) -> None:
    _set_production_config_env(monkeypatch, **override)

    with pytest.raises(CollectorConfigurationError) as exc_info:
        CollectorConfig.from_env(tmp_path / "no-config.env")

    error = str(exc_info.value)
    assert expected_message in error
    if sensitive_value:
        assert sensitive_value not in error


def test_local_development_keeps_http_and_development_defaults(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    for key in ("APP_ENV", "SAAS_BASE_URL", "SAAS_VERIFY_TLS", "COLLECTOR_TOKEN", "PSEUDONYM_SALT"):
        monkeypatch.delenv(key, raising=False)

    config = CollectorConfig.from_env(tmp_path / "no-config.env")

    assert config.app_env == "development"
    assert config.saas_base_url == "http://localhost:8000"
    assert config.saas_verify_tls is False
    assert config.collector_token == "dev-collector-token"
    assert config.pseudonym_salt == "dev-pseudonym-salt-change-in-prod"


def test_production_credentials_do_not_appear_in_sender_logs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    token = secrets.token_urlsafe(32)
    salt = secrets.token_urlsafe(32)
    _set_production_config_env(monkeypatch, COLLECTOR_TOKEN=token, PSEUDONYM_SALT=salt)
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    cfg = CollectorConfig.from_env(tmp_path / "no-config.env")
    store = CollectorStore(tmp_path / "production_log_secrets.db")
    store.enqueue_payload(_duplicate_test_payload("production-log-secrets"), fields_redacted=[])
    sender = CollectorSender(
        cfg,
        store,
        session=_DummySession([_DummyResponse(503, "retry later")]),
        rng=random.Random(42),
    )
    captured_logs = StringIO()
    capture_handler = logging.StreamHandler(captured_logs)
    sender.logger.addHandler(capture_handler)

    try:
        assert sender.send_batch_once(batch_size=1)["failed"] == 1
        logs = captured_logs.getvalue()
        assert token not in repr(cfg)
        assert salt not in repr(cfg)
        assert token not in logs
        assert salt not in logs
    finally:
        sender.logger.removeHandler(capture_handler)
        capture_handler.close()
        store.close()


def test_demo_configuration_permits_http_backend(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("APP_ENV", "demo")
    monkeypatch.setenv("SAAS_BASE_URL", "http://127.0.0.1:8000")

    config = CollectorConfig.from_env(tmp_path / "no-config.env")
    assert config.app_env == "demo"
    assert config.saas_base_url == "http://127.0.0.1:8000"


@pytest.mark.parametrize("environment", ["development", "demo"])
def test_nonproduction_configuration_permits_internal_docker_backend(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, environment: str
) -> None:
    monkeypatch.setenv("APP_ENV", environment)
    monkeypatch.setenv("SAAS_BASE_URL", "http://backend:8000")

    config = CollectorConfig.from_env(tmp_path / "no-config.env")

    assert config.app_env == environment
    assert config.saas_base_url == "http://backend:8000"


@pytest.mark.parametrize("environment", ["development", "demo"])
@pytest.mark.parametrize("url", ["http://192.0.2.10:8000", "http://backend:8001"])
def test_nonproduction_configuration_rejects_remote_http_backend(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    environment: str,
    url: str,
) -> None:
    monkeypatch.setenv("APP_ENV", environment)
    monkeypatch.setenv("SAAS_BASE_URL", url)
    with pytest.raises(CollectorConfigurationError, match="HTTP only with localhost or a loopback"):
        CollectorConfig.from_env(tmp_path / "no-config.env")


@pytest.mark.parametrize("url", ["http://localhost:8000", "http://127.0.0.1:8000", "http://[::1]:8000"])
def test_nonproduction_configuration_permits_loopback_http(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, url: str
) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("SAAS_BASE_URL", url)
    assert CollectorConfig.from_env(tmp_path / "no-config.env").saas_base_url == url


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("COLLECTOR_QUEUE_MAX_MB", "0", "COLLECTOR_QUEUE_MAX_MB must be greater than zero"),
        ("COLLECTOR_QUEUE_MAX_MB", "-1", "COLLECTOR_QUEUE_MAX_MB must be greater than zero"),
        ("COLLECTOR_QUEUE_MAX_MB", "nan", "COLLECTOR_QUEUE_MAX_MB must be greater than zero"),
        (
            "COLLECTOR_LOCAL_RETENTION_HOURS",
            "0",
            "COLLECTOR_LOCAL_RETENTION_HOURS must be greater than zero",
        ),
        (
            "COLLECTOR_LOCAL_RETENTION_HOURS",
            "-1",
            "COLLECTOR_LOCAL_RETENTION_HOURS must be greater than zero",
        ),
    ],
)
def test_configuration_rejects_nonpositive_queue_and_retention(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    key: str,
    value: str,
    message: str,
) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv(key, value)
    with pytest.raises(CollectorConfigurationError, match=message):
        CollectorConfig.from_env(tmp_path / "no-config.env")


def test_sender_stores_safe_error_summaries_and_logs_no_sensitive_error_data(
    tmp_path: Path,
) -> None:
    store = CollectorStore(tmp_path / "safe_sender_errors.db")
    cfg = CollectorConfig(
        sqlite_path=tmp_path / "safe_sender_errors.db",
        log_file_path=tmp_path / "safe_sender_errors.log",
        saas_base_url="http://localhost:8000",
    )
    sensitive_values = [
        "Bearer supersecret-token-value",
        "password=hunter2-sensitive",
        "operator.private@example.test",
        "198.51.100.77",
        "AKIA1234567890ABCDEF",
        "-----BEGIN PRIVATE KEY-----FAKE-PRIVATE-KEY-MATERIAL-----END PRIVATE KEY-----",
    ]
    secret_blob = " | ".join(sensitive_values)
    store.enqueue_payload(_duplicate_test_payload("safe-error-http"), fields_redacted=[])
    store.enqueue_payload(_duplicate_test_payload("safe-error-exception"), fields_redacted=[])

    session = _DummySession(
        [
            _DummyResponse(422, f"Rejected request: {secret_blob}"),
            requests.exceptions.ConnectionError(f"Connection failed: {secret_blob}"),
        ]
    )
    sender = CollectorSender(cfg, store, session=session, rng=random.Random(42))
    captured_logs = StringIO()
    capture_handler = logging.StreamHandler(captured_logs)
    sender.logger.addHandler(capture_handler)

    try:
        result = sender.send_batch_once(batch_size=2)
        assert result["rejected"] == 1
        assert result["failed"] == 1

        error_rows = store.conn.execute(
            "SELECT payload_id, status, last_error FROM outbound_queue "
            "WHERE payload_id IN (?, ?) ORDER BY payload_id",
            ("safe-error-http", "safe-error-exception"),
        ).fetchall()
        error_texts = [str(row["last_error"]) for row in error_rows]
        assert len(error_texts) == 2
        assert any("HTTP 422" in message and "schema_rejected" in message for message in error_texts)
        assert any("connection_error" in message for message in error_texts)
        assert all(len(message) <= MAX_STORED_ERROR_LENGTH for message in error_texts)

        emitted = captured_logs.getvalue()
        for sensitive_value in sensitive_values:
            assert all(sensitive_value not in message for message in error_texts)
            assert sensitive_value not in emitted
        assert "Rejected request" not in " ".join(error_texts)
        assert "Connection failed:" not in " ".join(error_texts)
        assert "Authorization" not in emitted
    finally:
        sender.logger.removeHandler(capture_handler)
        capture_handler.close()
        store.close()


def test_store_redacts_and_bounds_error_summaries(tmp_path: Path) -> None:
    store = CollectorStore(tmp_path / "bounded_error.db")
    payload_id = "safe-error-store-boundary"
    store.enqueue_payload(_duplicate_test_payload(payload_id), fields_redacted=[])
    sensitive_error = (
        "HTTP error password=hidden-pass user=private@example.test from 203.0.113.81 "
        "Bearer hidden-bearer-token "
        "-----BEGIN PRIVATE KEY-----FAKE-----END PRIVATE KEY----- "
        + "x" * 500
    )
    try:
        store.reschedule_retry(payload_id, delay_seconds=1, error_msg=sensitive_error)
        stored_error = store.conn.execute(
            "SELECT last_error FROM outbound_queue WHERE payload_id = ?", (payload_id,)
        ).fetchone()[0]
        assert len(stored_error) <= MAX_STORED_ERROR_LENGTH
        for sensitive_value in (
            "hidden-pass",
            "private@example.test",
            "203.0.113.81",
            "hidden-bearer-token",
            "FAKE",
        ):
            assert sensitive_value not in stored_error
    finally:
        store.close()


def _serialized_payload_size(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))


def _queue_capacity_mb(byte_limit: int) -> float:
    return byte_limit / (1024 * 1024)


def test_queue_payload_below_capacity_is_inserted(tmp_path: Path) -> None:
    payload = _duplicate_test_payload("capacity-below-limit")
    payload_size = _serialized_payload_size(payload)
    store = CollectorStore(
        tmp_path / "capacity_below.db",
        queue_max_mb=_queue_capacity_mb(payload_size + 1),
    )
    try:
        store.enqueue_payload(payload, fields_redacted=[])
        assert store.get_queue_usage_bytes() == payload_size
        assert store.get_queue_stats()["pending"] == 1
    finally:
        store.close()


def test_queue_rejects_over_capacity_without_partial_queue_or_audit_insert(
    tmp_path: Path,
) -> None:
    first = _duplicate_test_payload("capacity-full-0001")
    second = _duplicate_test_payload("capacity-full-0002")
    capacity = _serialized_payload_size(first)
    assert _serialized_payload_size(second) == capacity
    store = CollectorStore(
        tmp_path / "capacity_reject.db",
        queue_max_mb=_queue_capacity_mb(capacity),
    )
    try:
        store.enqueue_payload(first, fields_redacted=["first-redaction"])
        queue_before = [
            dict(row) for row in store.conn.execute("SELECT * FROM outbound_queue ORDER BY payload_id")
        ]
        audit_before = [
            dict(row) for row in store.conn.execute("SELECT * FROM egress_audit ORDER BY audit_id")
        ]

        with pytest.raises(QueueCapacityExceeded) as exc_info:
            store.enqueue_payload(second, fields_redacted=["should-not-be-audited"])

        queue_after = [
            dict(row) for row in store.conn.execute("SELECT * FROM outbound_queue ORDER BY payload_id")
        ]
        audit_after = [
            dict(row) for row in store.conn.execute("SELECT * FROM egress_audit ORDER BY audit_id")
        ]
        assert "capacity exceeded" in str(exc_info.value).lower()
        assert exc_info.value.current_bytes == capacity
        assert exc_info.value.requested_bytes == capacity
        assert exc_info.value.limit_bytes == capacity
        assert queue_after == queue_before
        assert audit_after == audit_before
        assert store.get_queue_usage_bytes() == capacity
    finally:
        store.close()


def test_queue_capacity_boundary_accepts_exact_fit(tmp_path: Path) -> None:
    payload = _duplicate_test_payload("capacity-exact-boundary")
    payload_size = _serialized_payload_size(payload)
    store = CollectorStore(
        tmp_path / "capacity_boundary.db",
        queue_max_mb=_queue_capacity_mb(payload_size),
    )
    try:
        assert store.queue_max_bytes == payload_size
        store.enqueue_payload(payload, fields_redacted=[])
        assert store.get_queue_usage_bytes() == store.queue_max_bytes
    finally:
        store.close()


def test_identical_duplicate_is_noop_when_queue_is_full(tmp_path: Path) -> None:
    payload = _duplicate_test_payload("capacity-duplicate-full")
    payload_size = _serialized_payload_size(payload)
    store = CollectorStore(
        tmp_path / "capacity_duplicate.db",
        queue_max_mb=_queue_capacity_mb(payload_size),
    )
    try:
        first = store.enqueue_payload(payload, fields_redacted=["original-audit"])
        queue_before = dict(
            store.conn.execute(
                "SELECT * FROM outbound_queue WHERE payload_id = ?", (payload["payload_id"],)
            ).fetchone()
        )
        audit_before = [
            dict(row)
            for row in store.conn.execute(
                "SELECT * FROM egress_audit WHERE payload_id = ?", (payload["payload_id"],)
            )
        ]

        duplicate = store.enqueue_payload(payload, fields_redacted=["changed-audit"])

        queue_after = dict(
            store.conn.execute(
                "SELECT * FROM outbound_queue WHERE payload_id = ?", (payload["payload_id"],)
            ).fetchone()
        )
        audit_after = [
            dict(row)
            for row in store.conn.execute(
                "SELECT * FROM egress_audit WHERE payload_id = ?", (payload["payload_id"],)
            )
        ]
        assert duplicate["duplicate"] is True
        assert duplicate["audit_id"] == first["audit_id"]
        assert queue_after == queue_before
        assert audit_after == audit_before
        assert store.get_queue_usage_bytes() == payload_size
    finally:
        store.close()


def test_conflicting_duplicate_is_rejected_when_queue_is_full(tmp_path: Path) -> None:
    payload = _duplicate_test_payload("capacity-conflict-full")
    capacity = _serialized_payload_size(payload)
    store = CollectorStore(
        tmp_path / "capacity_conflict.db",
        queue_max_mb=_queue_capacity_mb(capacity),
    )
    try:
        store.enqueue_payload(payload, fields_redacted=[])
        altered = _duplicate_test_payload(payload["payload_id"], cpu_pct=99.0)
        with pytest.raises(DuplicatePayloadConflict):
            store.enqueue_payload(altered, fields_redacted=[])
        assert store.get_queue_stats()["pending"] == 1
        assert store.get_queue_usage_bytes() == capacity
        assert store.conn.execute("SELECT COUNT(*) FROM egress_audit").fetchone()[0] == 1
    finally:
        store.close()


def test_concurrent_processes_claim_disjoint_queue_batches(tmp_path: Path) -> None:
    db_path = tmp_path / "concurrent_claims.db"
    store = CollectorStore(db_path)
    try:
        for index in range(40):
            store.enqueue_payload(
                _duplicate_test_payload(f"concurrent-claim-{index:02d}"), fields_redacted=[]
            )
    finally:
        store.close()

    context = multiprocessing.get_context("spawn")
    start_event = context.Event()
    claimed_event = context.Event()
    release_event = context.Event()
    result_queue = context.Queue()
    processes = [
        context.Process(
            target=_claim_then_hold_store,
            args=(str(db_path), start_event, claimed_event, release_event, result_queue),
        ),
        context.Process(
            target=_open_and_claim_after_first_claim,
            args=(str(db_path), claimed_event, result_queue),
        ),
    ]
    try:
        for process in processes:
            process.start()
        start_event.set()
        claimed_batches = [result_queue.get(timeout=15) for _ in processes]
        release_event.set()
        for process in processes:
            process.join(timeout=15)
        assert all(process.exitcode == 0 for process in processes)
        assert all(isinstance(batch, list) for batch in claimed_batches)
        first, second = claimed_batches
        assert len(first) == len(second) == 20
        assert set(first).isdisjoint(second)
        assert len(set(first) | set(second)) == 40
    finally:
        release_event.set()
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        result_queue.close()


def test_waiting_constructor_retries_exclusive_recovery_after_owner_is_killed(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "recovery_owner_crash.db"
    store = CollectorStore(db_path)
    try:
        store.enqueue_payload(_duplicate_test_payload("recovery-owner-crash-1"), fields_redacted=[])
        assert len(store.fetch_due_batch(batch_size=1, now_utc="2999-01-01T00:00:00Z")) == 1
    finally:
        store.close()

    context = multiprocessing.get_context("spawn")
    owner_acquired = context.Event()
    waiter_attempting = context.Event()
    result_queue = context.Queue()
    owner = context.Process(
        target=_hold_exclusive_recovery_before_recovery,
        args=(str(db_path), owner_acquired),
    )
    waiter = context.Process(
        target=_construct_after_exclusive_owner_dies,
        args=(str(db_path), waiter_attempting, result_queue),
    )
    try:
        owner.start()
        assert owner_acquired.wait(timeout=10)
        waiter.start()
        assert waiter_attempting.wait(timeout=10)
        assert owner.is_alive()

        owner.kill()
        owner.join(timeout=10)
        assert owner.exitcode == -9

        recovered_stats = result_queue.get(timeout=15)
        waiter.join(timeout=15)
        assert waiter.exitcode == 0
        assert "error" not in recovered_stats
        assert recovered_stats["pending"] == 1
        assert recovered_stats["in_flight"] == 0
    finally:
        for process in (owner, waiter):
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        result_queue.close()


def test_queue_claim_rolls_back_all_rows_when_claim_update_fails(tmp_path: Path) -> None:
    store = CollectorStore(tmp_path / "claim_rollback.db")
    try:
        for payload_id in ("claim-rollback-1", "claim-rollback-2"):
            store.enqueue_payload(_duplicate_test_payload(payload_id), fields_redacted=[])
        store.conn.execute(
            """
            CREATE TRIGGER fail_second_queue_claim
            BEFORE UPDATE OF status ON outbound_queue
            WHEN OLD.payload_id = 'claim-rollback-2'
            BEGIN
                SELECT RAISE(ABORT, 'forced claim failure');
            END;
            """
        )
        store.conn.commit()

        with pytest.raises(sqlite3.IntegrityError, match="forced claim failure"):
            store.fetch_due_batch(batch_size=2, now_utc="2999-01-01T00:00:00Z")

        rows = store.conn.execute(
            "SELECT status, attempts FROM outbound_queue ORDER BY payload_id"
        ).fetchall()
        assert [(row["status"], row["attempts"]) for row in rows] == [
            ("pending", 0),
            ("pending", 0),
        ]

        store.conn.execute("DROP TRIGGER fail_second_queue_claim")
        store.conn.commit()
        assert len(store.fetch_due_batch(batch_size=2, now_utc="2999-01-01T00:00:00Z")) == 2
    finally:
        store.close()


def test_delivered_and_rejected_rows_do_not_consume_queue_capacity(tmp_path: Path) -> None:
    first = _duplicate_test_payload("capacity-release-0001")
    second = _duplicate_test_payload("capacity-release-0002")
    capacity = _serialized_payload_size(first)
    assert _serialized_payload_size(second) == capacity
    store = CollectorStore(
        tmp_path / "capacity_release.db",
        queue_max_mb=_queue_capacity_mb(capacity),
    )
    try:
        store.enqueue_payload(first, fields_redacted=[])
        store.mark_delivered(first["payload_id"])
        assert store.get_queue_usage_bytes() == 0
        store.enqueue_payload(second, fields_redacted=[])
        store.mark_rejected(second["payload_id"], "schema error")
        assert store.get_queue_usage_bytes() == 0
    finally:
        store.close()


def _insert_raw_event_with_created_at(store: CollectorStore, created_at_utc: str) -> int:
    cur = store.conn.execute(
        "INSERT INTO raw_events (event_type, event_time_utc, raw_json, created_at_utc) "
        "VALUES (?, ?, ?, ?)",
        ("test_event", "2026-11-22T12:00:00Z", "{}", created_at_utc),
    )
    store.conn.commit()
    return int(cur.lastrowid)


def test_raw_retention_deletes_old_rows_and_preserves_queue_and_audit(
    tmp_path: Path,
) -> None:
    store = CollectorStore(tmp_path / "raw_retention.db")
    old_id = _insert_raw_event_with_created_at(store, "2026-11-21T11:59:59Z")
    cutoff_id = _insert_raw_event_with_created_at(store, "2026-11-21T12:00:00Z")
    recent_id = _insert_raw_event_with_created_at(store, "2026-11-22T11:00:00Z")
    first = _duplicate_test_payload("retention-queue-pending")
    second = _duplicate_test_payload("retention-queue-flight")
    store.enqueue_payload(first, fields_redacted=[])
    store.enqueue_payload(second, fields_redacted=[])
    in_flight = store.fetch_due_batch(batch_size=1)
    assert len(in_flight) == 1
    queue_before = [
        dict(row) for row in store.conn.execute("SELECT * FROM outbound_queue ORDER BY payload_id")
    ]
    audit_before = [
        dict(row) for row in store.conn.execute("SELECT * FROM egress_audit ORDER BY audit_id")
    ]

    try:
        result = store.cleanup_raw_events(
            retention_hours=24,
            now_utc="2026-11-22T12:00:00Z",
        )

        remaining_raw_ids = {
            int(row[0]) for row in store.conn.execute("SELECT id FROM raw_events")
        }
        queue_after = [
            dict(row) for row in store.conn.execute("SELECT * FROM outbound_queue ORDER BY payload_id")
        ]
        audit_after = [
            dict(row) for row in store.conn.execute("SELECT * FROM egress_audit ORDER BY audit_id")
        ]
        assert result["deleted_raw_events"] == 1
        assert result["cutoff_utc"] == "2026-11-21T12:00:00.000000Z"
        assert old_id not in remaining_raw_ids
        assert cutoff_id in remaining_raw_ids
        assert recent_id in remaining_raw_ids
        assert queue_after == queue_before
        assert {row["status"] for row in queue_after} == {"pending", "in_flight"}
        assert audit_after == audit_before
        assert result["audit_records_deleted"] == 0
    finally:
        store.close()


def test_raw_retention_no_qualifying_rows_is_safe(tmp_path: Path) -> None:
    store = CollectorStore(tmp_path / "raw_retention_empty.db")
    _insert_raw_event_with_created_at(store, "2026-11-22T11:00:00Z")
    before = store.conn.execute("SELECT COUNT(*) FROM raw_events").fetchone()[0]
    try:
        result = store.cleanup_raw_events(
            retention_hours=24,
            now_utc="2026-11-22T12:00:00Z",
        )
        after = store.conn.execute("SELECT COUNT(*) FROM raw_events").fetchone()[0]
        assert result["deleted_raw_events"] == 0
        assert after == before == 1
    finally:
        store.close()


def test_raw_retention_keeps_malformed_legacy_timestamps(tmp_path: Path) -> None:
    store = CollectorStore(tmp_path / "raw_retention_malformed.db")
    malformed_id = _insert_raw_event_with_created_at(store, "not-a-valid-timestamp")
    blank_id = _insert_raw_event_with_created_at(store, "")
    old_id = _insert_raw_event_with_created_at(store, "2026-11-20T12:00:00Z")
    try:
        result = store.cleanup_raw_events(
            retention_hours=24,
            now_utc="2026-11-22T12:00:00Z",
        )
        remaining_ids = {int(row[0]) for row in store.conn.execute("SELECT id FROM raw_events")}
        assert result["deleted_raw_events"] == 1
        assert old_id not in remaining_ids
        assert malformed_id in remaining_ids
        assert blank_id in remaining_ids
    finally:
        store.close()


def test_cleanup_cli_reports_expiry_and_indefinite_audit_retention(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = CollectorConfig(
        sqlite_path=tmp_path / "cleanup_cli.db",
        log_file_path=tmp_path / "cleanup_cli.log",
        local_retention_hours=24,
    )
    store = CollectorStore(cfg.sqlite_path)
    _insert_raw_event_with_created_at(store, "2000-01-01T00:00:00Z")
    try:
        assert _cmd_cleanup(cfg, store) == 0
        output = json.loads(capsys.readouterr().out)
        assert output["deleted_raw_events"] == 1
        assert output["audit_records_deleted"] == 0
        assert output["egress_audit_retention"] == "indefinite"
    finally:
        store.close()
