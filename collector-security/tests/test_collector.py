from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

import pytest

from collector.allowlist import AllowlistValidator
from collector.config import CollectorConfig
from collector.generator import TelemetryGenerator
from collector.logger import RedactionLogFilter
from collector.pipeline import CollectorPipeline
from collector.redaction import RedactionEngine, pseudonymize_source_id
from collector.sender import CollectorSender, compute_backoff_delay
from collector.store import CollectorStore


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
        "event_type": "infrastructure_metrics",
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
    assert set(dropped) == {"raw_hostname", "data.password", "data.raw_ip"}

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

    assert emitted_types == ["security_events", "security_events"]
    raw_rows = store.conn.execute("SELECT COUNT(*) AS c FROM raw_events;").fetchone()["c"]
    assert raw_rows == 4
    store.close()


def test_store_crash_recovery_and_sender_outcomes(tmp_path: Path) -> None:
    db_path = tmp_path / "queue.db"
    store = CollectorStore(db_path)
    cfg = CollectorConfig(
        sqlite_path=db_path,
        log_file_path=tmp_path / "collector.log",
        saas_base_url="http://mock-saas:8000",
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
        saas_base_url="http://mock-saas:8000",
    )

    base_env = {
        "tenant_id": "tnt_acme_001",
        "collector_id": "col_acme_blr_01",
        "source_id": "src_9999999999",
        "event_type": "infrastructure_metrics",
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


def test_replay_preserves_payload_id_and_hash(tmp_path: Path) -> None:
    db_path = tmp_path / "replay.db"
    store = CollectorStore(db_path)
    cfg = CollectorConfig(
        sqlite_path=db_path,
        log_file_path=tmp_path / "collector.log",
        saas_base_url="http://mock-saas:8000",
    )

    env = {
        "payload_id": "33333333-3333-4333-8333-333333333331",
        "tenant_id": "tnt_acme_001",
        "collector_id": "col_acme_blr_01",
        "source_id": "src_3333333333",
        "event_type": "infrastructure_metrics",
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


def test_sender_accepts_201_and_handles_409_conflict_idempotently(tmp_path: Path) -> None:
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
        "event_type": "infrastructure_metrics",
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
