from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def compute_content_hash(payload_bytes: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload_bytes).hexdigest()


class CollectorStore:
    """SQLite local store for raw telemetry (local-only), outbound queue, and egress audit."""

    def __init__(self, db_path: Path, queue_max_mb: float = 100.0) -> None:
        self.db_path = Path(db_path)
        self.queue_max_bytes = int(queue_max_mb * 1024 * 1024)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_db()
        self.recover_inflight()

    def _init_db(self) -> None:
        cur = self.conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL;")
        cur.execute("PRAGMA synchronous=NORMAL;")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS raw_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                event_time_utc TEXT NOT NULL,
                raw_json TEXT NOT NULL,
                created_at_utc TEXT NOT NULL
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS outbound_queue (
                payload_id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                event_time_utc TEXT NOT NULL,
                body_json TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt_utc TEXT NOT NULL,
                last_error TEXT,
                queued_at_utc TEXT NOT NULL,
                delivered_at_utc TEXT
            );
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_queue_pending
            ON outbound_queue (status, event_time_utc);
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS egress_audit (
                audit_id TEXT PRIMARY KEY,
                payload_id TEXT NOT NULL,
                fields_sent TEXT NOT NULL,
                fields_redacted TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                queued_at_utc TEXT NOT NULL,
                sent_at_utc TEXT
            );
            """
        )
        self.conn.commit()

    def recover_inflight(self) -> int:
        now = utc_now_iso()
        cur = self.conn.cursor()
        cur.execute(
            """
            UPDATE outbound_queue
            SET status = 'pending', next_attempt_utc = ?
            WHERE status = 'in_flight';
            """,
            (now,),
        )
        self.conn.commit()
        return cur.rowcount

    def record_raw_event(self, event_type: str, event_time_utc: str, raw_event: dict[str, Any]) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO raw_events (event_type, event_time_utc, raw_json, created_at_utc)
            VALUES (?, ?, ?, ?);
            """,
            (
                event_type,
                event_time_utc,
                json.dumps(raw_event, sort_keys=True, default=str),
                utc_now_iso(),
            ),
        )
        self.conn.commit()

    def _collect_field_paths(self, obj: Any, prefix: str = "") -> list[str]:
        paths: list[str] = []
        if isinstance(obj, dict):
            for k, v in obj.items():
                path = f"{prefix}.{k}" if prefix else str(k)
                if isinstance(v, dict):
                    paths.extend(self._collect_field_paths(v, path))
                else:
                    paths.append(path)
        return paths

    def enqueue_payload(
        self,
        envelope: dict[str, Any],
        fields_redacted: list[str],
        queued_at_utc: Optional[str] = None,
    ) -> dict[str, Any]:
        payload_id = str(envelope["payload_id"])
        event_type = str(envelope["event_type"])
        event_time_utc = str(envelope["event_time_utc"])
        queued_ts = queued_at_utc or utc_now_iso()
        body_json = json.dumps(envelope, separators=(",", ":"), sort_keys=True)
        content_hash = compute_content_hash(body_json.encode("utf-8"))
        fields_sent = sorted(self._collect_field_paths(envelope))
        audit_id = f"egress_{uuid.uuid4().hex[:8]}"

        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT OR REPLACE INTO outbound_queue (
                payload_id, event_type, event_time_utc, body_json, content_hash,
                status, attempts, next_attempt_utc, last_error, queued_at_utc, delivered_at_utc
            ) VALUES (?, ?, ?, ?, ?, 'pending', 0, ?, NULL, ?, NULL);
            """,
            (payload_id, event_type, event_time_utc, body_json, content_hash, queued_ts, queued_ts),
        )
        cur.execute(
            """
            INSERT OR REPLACE INTO egress_audit (
                audit_id, payload_id, fields_sent, fields_redacted,
                content_hash, queued_at_utc, sent_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, NULL);
            """,
            (
                audit_id,
                payload_id,
                json.dumps(fields_sent),
                json.dumps(sorted(set(fields_redacted))),
                content_hash,
                queued_ts,
            ),
        )
        self.conn.commit()
        return {
            "audit_id": audit_id,
            "payload_id": payload_id,
            "content_hash": content_hash,
            "fields_sent": fields_sent,
        }

    def fetch_due_batch(self, batch_size: int = 50, now_utc: Optional[str] = None) -> list[dict[str, Any]]:
        now = now_utc or utc_now_iso()
        cur = self.conn.cursor()
        rows = cur.execute(
            """
            SELECT payload_id, event_type, event_time_utc, body_json, content_hash, attempts
            FROM outbound_queue
            WHERE status = 'pending' AND next_attempt_utc <= ?
            ORDER BY event_time_utc ASC, queued_at_utc ASC
            LIMIT ?;
            """,
            (now, batch_size),
        ).fetchall()

        batch: list[dict[str, Any]] = []
        for r in rows:
            new_attempts = int(r["attempts"]) + 1
            cur.execute(
                """
                UPDATE outbound_queue
                SET status = 'in_flight', attempts = ?
                WHERE payload_id = ?;
                """,
                (new_attempts, r["payload_id"]),
            )
            batch.append(
                {
                    "payload_id": r["payload_id"],
                    "event_type": r["event_type"],
                    "event_time_utc": r["event_time_utc"],
                    "body_json": r["body_json"],
                    "content_hash": r["content_hash"],
                    "attempts": new_attempts,
                }
            )
        self.conn.commit()
        return batch

    def mark_delivered(self, payload_id: str, delivered_at_utc: Optional[str] = None) -> None:
        ts = delivered_at_utc or utc_now_iso()
        cur = self.conn.cursor()
        cur.execute(
            """
            UPDATE outbound_queue
            SET status = 'delivered', delivered_at_utc = ?, last_error = NULL
            WHERE payload_id = ?;
            """,
            (ts, payload_id),
        )
        cur.execute(
            """
            UPDATE egress_audit
            SET sent_at_utc = ?
            WHERE payload_id = ? AND sent_at_utc IS NULL;
            """,
            (ts, payload_id),
        )
        self.conn.commit()

    def reschedule_retry(self, payload_id: str, delay_seconds: float, error_msg: str) -> None:
        next_ts = (datetime.now(timezone.utc) + timedelta(seconds=max(0.0, delay_seconds))).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        cur = self.conn.cursor()
        cur.execute(
            """
            UPDATE outbound_queue
            SET status = 'pending', next_attempt_utc = ?, last_error = ?
            WHERE payload_id = ?;
            """,
            (next_ts, error_msg[:250], payload_id),
        )
        self.conn.commit()

    def mark_rejected(self, payload_id: str, error_msg: str) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            UPDATE outbound_queue
            SET status = 'rejected', last_error = ?
            WHERE payload_id = ?;
            """,
            (error_msg[:250], payload_id),
        )
        self.conn.commit()

    def get_queue_stats(self) -> dict[str, int]:
        cur = self.conn.cursor()
        rows = cur.execute(
            "SELECT status, COUNT(*) AS cnt FROM outbound_queue GROUP BY status;"
        ).fetchall()
        counts = {"pending": 0, "in_flight": 0, "delivered": 0, "rejected": 0}
        for r in rows:
            counts[str(r["status"])] = int(r["cnt"])
        return counts

    def close(self) -> None:
        self.conn.close()
