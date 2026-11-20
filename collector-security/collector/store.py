from __future__ import annotations

import fcntl
import hashlib
import json
import re
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

MAX_STORED_ERROR_LENGTH = 240
_ERROR_REDACTION_PATTERNS = (
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-~+/=]+"),
    re.compile(r'(?i)(?:password|passwd|pwd|secret|api_key|apikey|token|authorization)\s*[:=]\s*[^\s,;"\']+'),
    re.compile(
        r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|$)",
        re.DOTALL,
    ),
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b"),
    re.compile(r"\b(?:\d[ -]*?){13,16}\b"),
)


def sanitize_error_summary(error_msg: str) -> str:
    """Redact common sensitive values and bound persisted queue error text."""
    sanitized = str(error_msg)
    for pattern in _ERROR_REDACTION_PATTERNS:
        sanitized = pattern.sub("[REDACTED]", sanitized)
    if len(sanitized) > MAX_STORED_ERROR_LENGTH:
        sanitized = sanitized[: MAX_STORED_ERROR_LENGTH - 14] + "...[TRUNCATED]"
    return sanitized


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def compute_content_hash(payload_bytes: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload_bytes).hexdigest()


class DuplicatePayloadConflict(ValueError):
    """Raised when a payload ID is reused for different serialized content."""


class QueueCapacityExceeded(ValueError):
    """Raised when a new active payload would exceed the configured queue byte limit."""

    def __init__(self, current_bytes: int, requested_bytes: int, limit_bytes: int) -> None:
        self.current_bytes = current_bytes
        self.requested_bytes = requested_bytes
        self.limit_bytes = limit_bytes
        super().__init__(
            "Outbound queue capacity exceeded: "
            f"{current_bytes} bytes used + {requested_bytes} bytes requested "
            f"exceeds {limit_bytes} byte limit"
        )


class CollectorStore:
    """SQLite store; capacity counts UTF-8 body_json bytes in pending/in-flight rows."""

    def __init__(self, db_path: Path, queue_max_mb: float = 100.0) -> None:
        # Resolve aliases before deriving lock paths so symlinked paths to the same
        # database coordinate on the same sidecars.
        self.db_path = Path(db_path).expanduser().resolve()
        self.queue_max_bytes = int(queue_max_mb * 1024 * 1024)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # The startup gate serializes the recovery-lock decision. If an exclusive
        # initializer dies, the next waiter must retry exclusive ownership before it
        # can join the shared live-store lock.
        self._startup_lock_file = open(f"{self.db_path}.startup.lock", "a+")
        self._recovery_lock_file = open(f"{self.db_path}.recovery.lock", "a+")
        fcntl.flock(self._startup_lock_file.fileno(), fcntl.LOCK_EX)
        try:
            try:
                fcntl.flock(
                    self._recovery_lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB
                )
                self._owns_recovery_lock = True
            except BlockingIOError:
                fcntl.flock(self._recovery_lock_file.fileno(), fcntl.LOCK_SH)
                self._owns_recovery_lock = False

            self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            self._init_db()
            if self._owns_recovery_lock:
                self.recover_inflight()
                fcntl.flock(self._recovery_lock_file.fileno(), fcntl.LOCK_SH)
        except Exception:
            if hasattr(self, "conn"):
                self.conn.close()
            self._recovery_lock_file.close()
            raise
        finally:
            fcntl.flock(self._startup_lock_file.fileno(), fcntl.LOCK_UN)
            self._startup_lock_file.close()

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
            CREATE INDEX IF NOT EXISTS ix_raw_events_created_julian
            ON raw_events (julianday(created_at_utc));
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
            CREATE TABLE IF NOT EXISTS outbound_queue_usage (
                singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                active_bytes INTEGER NOT NULL CHECK (active_bytes >= 0)
            );
            """
        )
        # Seed existing databases once. Subsequent queue changes maintain this counter in their
        # transactions, so insertion does not need to scan all active payload rows.
        cur.execute(
            """
            INSERT OR IGNORE INTO outbound_queue_usage (singleton_id, active_bytes)
            SELECT 1, COALESCE(SUM(length(CAST(body_json AS BLOB))), 0)
            FROM outbound_queue
            WHERE status IN ('pending', 'in_flight');
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

    def cleanup_raw_events(
        self,
        retention_hours: int,
        now_utc: Optional[str] = None,
    ) -> dict[str, Any]:
        """Delete validly timestamped raw rows older than retention; queue and audit are untouched."""
        if retention_hours < 0:
            raise ValueError("retention_hours must be zero or greater")

        now_text = now_utc or utc_now_iso()
        try:
            now = datetime.fromisoformat(now_text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("now_utc must be a valid ISO-8601 timestamp") from exc
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        now = now.astimezone(timezone.utc)
        cutoff = now - timedelta(hours=retention_hours)
        cutoff_text = cutoff.isoformat(timespec="microseconds").replace("+00:00", "Z")

        cur = self.conn.cursor()
        cur.execute("BEGIN IMMEDIATE;")
        try:
            cur.execute(
                "DELETE FROM raw_events "
                "WHERE julianday(created_at_utc) IS NOT NULL "
                "AND julianday(created_at_utc) < julianday(?);",
                (cutoff_text,),
            )
            deleted = cur.rowcount
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return {
            "deleted_raw_events": deleted,
            "retention_hours": retention_hours,
            "cutoff_utc": cutoff_text,
            "audit_records_deleted": 0,
        }

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
        cur.execute("BEGIN IMMEDIATE;")
        try:
            existing = cur.execute(
                """
                SELECT body_json, content_hash
                FROM outbound_queue
                WHERE payload_id = ?;
                """,
                (payload_id,),
            ).fetchone()

            if existing is not None:
                if existing["body_json"] != body_json or existing["content_hash"] != content_hash:
                    raise DuplicatePayloadConflict(
                        f"Payload ID '{payload_id}' already exists with different content"
                    )

                existing_audit = cur.execute(
                    """
                    SELECT audit_id, fields_sent, content_hash
                    FROM egress_audit
                    WHERE payload_id = ?
                    ORDER BY queued_at_utc, audit_id
                    LIMIT 1;
                    """,
                    (payload_id,),
                ).fetchone()
                self.conn.commit()
                return {
                    "audit_id": existing_audit["audit_id"] if existing_audit else None,
                    "payload_id": payload_id,
                    "content_hash": existing["content_hash"],
                    "fields_sent": json.loads(existing_audit["fields_sent"])
                    if existing_audit
                    else fields_sent,
                    "duplicate": True,
                }

            payload_bytes = len(body_json.encode("utf-8"))
            usage = cur.execute(
                "SELECT active_bytes FROM outbound_queue_usage WHERE singleton_id = 1;"
            ).fetchone()
            current_bytes = int(usage["active_bytes"])
            if current_bytes + payload_bytes > self.queue_max_bytes:
                raise QueueCapacityExceeded(current_bytes, payload_bytes, self.queue_max_bytes)

            cur.execute(
                """
                INSERT INTO outbound_queue (
                    payload_id, event_type, event_time_utc, body_json, content_hash,
                    status, attempts, next_attempt_utc, last_error, queued_at_utc, delivered_at_utc
                ) VALUES (?, ?, ?, ?, ?, 'pending', 0, ?, NULL, ?, NULL);
                """,
                (payload_id, event_type, event_time_utc, body_json, content_hash, queued_ts, queued_ts),
            )
            cur.execute(
                """
                INSERT INTO egress_audit (
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
            cur.execute(
                "UPDATE outbound_queue_usage SET active_bytes = active_bytes + ? WHERE singleton_id = 1;",
                (payload_bytes,),
            )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return {
            "audit_id": audit_id,
            "payload_id": payload_id,
            "content_hash": content_hash,
            "fields_sent": fields_sent,
            "duplicate": False,
        }

    def fetch_due_batch(self, batch_size: int = 50, now_utc: Optional[str] = None) -> list[dict[str, Any]]:
        now = now_utc or utc_now_iso()
        cur = self.conn.cursor()
        batch: list[dict[str, Any]] = []
        cur.execute("BEGIN IMMEDIATE;")
        try:
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

            for r in rows:
                new_attempts = int(r["attempts"]) + 1
                cur.execute(
                    """
                    UPDATE outbound_queue
                    SET status = 'in_flight', attempts = ?
                    WHERE payload_id = ? AND status = 'pending';
                    """,
                    (new_attempts, r["payload_id"]),
                )
                if cur.rowcount != 1:
                    raise sqlite3.OperationalError("Queue row changed while claiming due payloads")
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
        except Exception:
            self.conn.rollback()
            raise
        return batch

    def mark_delivered(self, payload_id: str, delivered_at_utc: Optional[str] = None) -> None:
        ts = delivered_at_utc or utc_now_iso()
        cur = self.conn.cursor()
        cur.execute("BEGIN IMMEDIATE;")
        row = cur.execute(
            "SELECT status, length(CAST(body_json AS BLOB)) AS body_bytes "
            "FROM outbound_queue WHERE payload_id = ?;",
            (payload_id,),
        ).fetchone()
        cur.execute(
            """
            UPDATE outbound_queue
            SET status = 'delivered', delivered_at_utc = ?, last_error = NULL
            WHERE payload_id = ?;
            """,
            (ts, payload_id),
        )
        if row is not None and row["status"] in {"pending", "in_flight"}:
            cur.execute(
                "UPDATE outbound_queue_usage "
                "SET active_bytes = MAX(0, active_bytes - ?) WHERE singleton_id = 1;",
                (int(row["body_bytes"]),),
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
        cur.execute("BEGIN IMMEDIATE;")
        row = cur.execute(
            "SELECT status, length(CAST(body_json AS BLOB)) AS body_bytes "
            "FROM outbound_queue WHERE payload_id = ?;",
            (payload_id,),
        ).fetchone()
        if row is not None and row["status"] not in {"pending", "in_flight"}:
            usage = cur.execute(
                "SELECT active_bytes FROM outbound_queue_usage WHERE singleton_id = 1;"
            ).fetchone()
            current_bytes = int(usage["active_bytes"])
            payload_bytes = int(row["body_bytes"])
            if current_bytes + payload_bytes > self.queue_max_bytes:
                self.conn.rollback()
                raise QueueCapacityExceeded(current_bytes, payload_bytes, self.queue_max_bytes)
        cur.execute(
            """
            UPDATE outbound_queue
            SET status = 'pending', next_attempt_utc = ?, last_error = ?
            WHERE payload_id = ?;
            """,
            (next_ts, sanitize_error_summary(error_msg), payload_id),
        )
        if row is not None and row["status"] not in {"pending", "in_flight"}:
            cur.execute(
                "UPDATE outbound_queue_usage SET active_bytes = active_bytes + ? "
                "WHERE singleton_id = 1;",
                (int(row["body_bytes"]),),
            )
        self.conn.commit()

    def mark_rejected(self, payload_id: str, error_msg: str) -> None:
        cur = self.conn.cursor()
        cur.execute("BEGIN IMMEDIATE;")
        row = cur.execute(
            "SELECT status, length(CAST(body_json AS BLOB)) AS body_bytes "
            "FROM outbound_queue WHERE payload_id = ?;",
            (payload_id,),
        ).fetchone()
        cur.execute(
            """
            UPDATE outbound_queue
            SET status = 'rejected', last_error = ?
            WHERE payload_id = ?;
            """,
            (sanitize_error_summary(error_msg), payload_id),
        )
        if row is not None and row["status"] in {"pending", "in_flight"}:
            cur.execute(
                "UPDATE outbound_queue_usage "
                "SET active_bytes = MAX(0, active_bytes - ?) WHERE singleton_id = 1;",
                (int(row["body_bytes"]),),
            )
        self.conn.commit()

    def get_queue_usage_bytes(self) -> int:
        row = self.conn.execute(
            "SELECT active_bytes FROM outbound_queue_usage WHERE singleton_id = 1;"
        ).fetchone()
        return int(row["active_bytes"])

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
        self._recovery_lock_file.close()
