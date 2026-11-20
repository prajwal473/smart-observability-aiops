from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from typing import Optional

from collector.config import CollectorConfig
from collector.generator import TelemetryGenerator
from collector.logger import get_logger
from collector.pipeline import CollectorPipeline
from collector.sender import CollectorSender
from collector.store import CollectorStore


class _StopFlag:
    def __init__(self) -> None:
        self.stop = False

    def handle(self, _signum: int, _frame: object) -> None:
        self.stop = True


def _cmd_status(cfg: CollectorConfig, store: CollectorStore) -> int:
    stats = store.get_queue_stats()
    cur = store.conn.cursor()
    raw_count = cur.execute("SELECT COUNT(*) AS cnt FROM raw_events;").fetchone()["cnt"]
    audit_count = cur.execute("SELECT COUNT(*) AS cnt FROM egress_audit;").fetchone()["cnt"]
    output = {
        "collector_id": cfg.collector_id,
        "tenant_id": cfg.tenant_id,
        "saas_base_url": cfg.saas_base_url,
        "sqlite_path": str(cfg.sqlite_path),
        "raw_events_local_count": int(raw_count),
        "egress_audit_count": int(audit_count),
        "queue": stats,
    }
    print(json.dumps(output, indent=2))
    return 0


def _cmd_audit(cfg: CollectorConfig, store: CollectorStore, last_n: int) -> int:
    cur = store.conn.cursor()
    rows = cur.execute(
        """
        SELECT audit_id, payload_id, fields_sent, fields_redacted, content_hash, queued_at_utc, sent_at_utc
        FROM egress_audit
        ORDER BY queued_at_utc DESC
        LIMIT ?;
        """,
        (max(1, last_n),),
    ).fetchall()
    items = [
        {
            "audit_id": r["audit_id"],
            "payload_id": r["payload_id"],
            "fields_sent": json.loads(r["fields_sent"]),
            "fields_redacted": json.loads(r["fields_redacted"]),
            "content_hash": r["content_hash"],
            "queued_at_utc": r["queued_at_utc"],
            "sent_at_utc": r["sent_at_utc"],
        }
        for r in rows
    ]
    print(json.dumps({"collector_id": cfg.collector_id, "entries": items}, indent=2))
    return 0


def _cmd_replay(cfg: CollectorConfig, store: CollectorStore, last_n: int) -> int:
    cur = store.conn.cursor()
    rows = cur.execute(
        """
        SELECT payload_id
        FROM outbound_queue
        ORDER BY queued_at_utc DESC
        LIMIT ?;
        """,
        (max(1, last_n),),
    ).fetchall()
    ids = [r["payload_id"] for r in rows]
    for pid in ids:
        store.reschedule_retry(pid, delay_seconds=0.0, error_msg="manual replay")
    sender = CollectorSender(cfg, store)
    result = sender.send_batch_once(batch_size=max(1, len(ids)))
    print(json.dumps({"replayed_count": len(ids), "send_result": result}, indent=2))
    return 0


def _cmd_generate(
    cfg: CollectorConfig,
    store: CollectorStore,
    mode: str,
    duration_s: float,
    count: Optional[int],
    transmit: bool,
) -> int:
    gen = TelemetryGenerator(
        seed=cfg.generator_seed,
        mode=mode,
        source_timezone=cfg.source_timezone,
    )
    pipe = CollectorPipeline(cfg, store)
    sender = CollectorSender(cfg, store)

    start = time.monotonic()
    batches = 0
    enqueued_total = 0

    while True:
        raw_batch = gen.generate_raw_batch(mode=mode)
        for raw_ev in raw_batch:
            res = pipe.process_raw_event(raw_ev)
            if res is not None:
                enqueued_total += 1
        batches += 1

        if transmit:
            sender.send_batch_once()

        if count is not None and batches >= count:
            break
        if count is None and duration_s <= 0:
            break
        if count is None and (time.monotonic() - start) >= duration_s:
            break
        time.sleep(min(0.2, cfg.collect_interval_seconds))

    print(
        json.dumps(
            {
                "mode": mode,
                "batches_generated": batches,
                "enqueued_payloads": enqueued_total,
                "queue": store.get_queue_stats(),
            },
            indent=2,
        )
    )
    return 0


def _cmd_run(cfg: CollectorConfig, store: CollectorStore) -> int:
    logger = get_logger("cli", log_file_path=cfg.log_file_path, level=cfg.log_level)
    gen = TelemetryGenerator(
        seed=cfg.generator_seed,
        mode=cfg.generator_mode,
        source_timezone=cfg.source_timezone,
    )
    pipe = CollectorPipeline(cfg, store)
    sender = CollectorSender(cfg, store)

    stop_flag = _StopFlag()
    signal.signal(signal.SIGINT, stop_flag.handle)
    signal.signal(signal.SIGTERM, stop_flag.handle)

    logger.info(
        "Collector loop started",
        extra={
            "category": "collector_activity",
            "event": "collector.started",
            "tenant_id": cfg.tenant_id,
            "collector_id": cfg.collector_id,
            "details": {"mode": cfg.generator_mode, "saas_base_url": cfg.saas_base_url},
        },
    )

    last_collect = 0.0
    last_send = 0.0
    last_hb = 0.0

    while not stop_flag.stop:
        now = time.monotonic()
        if (now - last_collect) >= cfg.collect_interval_seconds:
            for raw_ev in gen.generate_raw_batch():
                pipe.process_raw_event(raw_ev)
            last_collect = now

        if (now - last_hb) >= cfg.heartbeat_interval_seconds:
            hb_env = pipe.build_heartbeat_payload(sender.last_successful_send_utc)
            sender.send_heartbeat(hb_env["data"])
            last_hb = now

        if (now - last_send) >= cfg.send_interval_seconds:
            res = sender.send_batch_once()
            last_send = now
            if res.get("failed", 0) > 0:
                sender.sleep_backoff()
                continue

        time.sleep(0.2)

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="collector.cli", description="Member 1 Collector CLI")
    parser.add_argument("--config", default=None, help="Path to .env or config file")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("run", help="Run continuous local collect + queue + transmit loop")

    gen_p = sub.add_parser("generate", help="Generate deterministic telemetry in a given mode")
    gen_p.add_argument(
        "--mode",
        default="normal",
        choices=sorted(TelemetryGenerator.SUPPORTED_MODES),
    )
    gen_p.add_argument("--duration", type=float, default=0.0, help="Duration in seconds (0 = 1 batch)")
    gen_p.add_argument("--count", type=int, default=None, help="Number of batches to generate")
    gen_p.add_argument("--transmit", action="store_true", help="Attempt sending queued items after generate")

    rep_p = sub.add_parser("replay", help="Re-queue and resend last N payloads (idempotency check)")
    rep_p.add_argument("--last", type=int, default=20)

    sub.add_parser("status", help="Show local collector queue and audit counts")

    aud_p = sub.add_parser("audit", help="Show recent egress audit entries")
    aud_p.add_argument("--last", type=int, default=10)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    cfg = CollectorConfig.from_env(args.config)
    store = CollectorStore(cfg.sqlite_path, queue_max_mb=cfg.queue_max_mb)
    try:
        if args.command == "run":
            return _cmd_run(cfg, store)
        if args.command == "generate":
            return _cmd_generate(
                cfg,
                store,
                mode=args.mode,
                duration_s=args.duration,
                count=args.count,
                transmit=args.transmit,
            )
        if args.command == "replay":
            return _cmd_replay(cfg, store, last_n=args.last)
        if args.command == "status":
            return _cmd_status(cfg, store)
        if args.command == "audit":
            return _cmd_audit(cfg, store, last_n=args.last)
        return 1
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main())
