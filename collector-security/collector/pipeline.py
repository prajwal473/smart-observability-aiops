from __future__ import annotations

import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any, Optional

from collector.allowlist import AllowlistValidator
from collector.config import CollectorConfig
from collector.logger import get_logger
from collector.redaction import RedactionEngine
from collector.store import CollectorStore, utc_now_iso


class CollectorPipeline:
    """
    Executes Tier 1 local processing:
    Collect -> Normalize -> Pseudonymize -> Redact -> Allow-list -> Local Auth Summary -> Audit & Queue.
    """

    def __init__(
        self,
        config: CollectorConfig,
        store: CollectorStore,
        validator: Optional[AllowlistValidator] = None,
        redactor: Optional[RedactionEngine] = None,
    ) -> None:
        self.config = config
        self.store = store
        self.validator = validator or AllowlistValidator.from_file(config.allowlist_path)
        self.redactor = redactor or RedactionEngine.from_rules_file(
            config.redaction_rules_path, config.pseudonym_salt
        )
        self.logger = get_logger(
            component="pipeline",
            log_file_path=config.log_file_path,
            level=config.log_level,
        )
        self._auth_failures_by_source: dict[str, deque[float]] = {}

    def _parse_ts_epoch(self, iso_ts: str) -> float:
        try:
            dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except Exception:
            return datetime.now(timezone.utc).timestamp()

    def _record_auth_failure_and_maybe_summarize(
        self,
        source_id: str,
        event_time_utc: str,
        source_timezone: str,
        raw_reason: str,
    ) -> Optional[dict[str, Any]]:
        ts_epoch = self._parse_ts_epoch(event_time_utc)
        window = float(self.config.auth_failure_window_seconds)
        threshold = max(1, int(self.config.auth_failure_burst_threshold))

        dq = self._auth_failures_by_source.setdefault(source_id, deque())
        dq.append(ts_epoch)
        while dq and (ts_epoch - dq[0]) > window:
            dq.popleft()

        count = len(dq)
        if count < threshold:
            return None

        scrubbed_reason, _ = self.redactor.scrub_string(raw_reason)
        summary_context = (
            f"Repeated auth failures ({count}) within {int(window)}s window: {scrubbed_reason}"
        )
        summary_context, _ = self.redactor.scrub_string(summary_context)
        severity = "critical" if count >= threshold * 2 else "high"

        return {
            "payload_id": str(uuid.uuid4()),
            "tenant_id": self.config.tenant_id,
            "collector_id": self.config.collector_id,
            "source_id": source_id,
            "event_type": "security",
            "event_time_utc": event_time_utc,
            "source_timezone": source_timezone,
            "data": {
                "event_category": "auth_failure_burst",
                "severity": severity,
                "count": count,
                "window_seconds": int(window),
                "context": {"summary": summary_context},
            },
        }

    def _normalize_to_envelope(self, raw_event: dict[str, Any]) -> Optional[dict[str, Any]]:
        etype = str(raw_event.get("event_type", ""))
        raw_host = str(raw_event.get("host") or raw_event.get("source_id") or "unknown-source")
        source_id = self.redactor.pseudonymize(raw_host)
        event_time_utc = str(raw_event.get("event_time_utc") or utc_now_iso())
        source_timezone = str(raw_event.get("source_timezone") or self.config.source_timezone)

        if etype == "infrastructure_metrics":
            return {
                "payload_id": str(uuid.uuid4()),
                "tenant_id": self.config.tenant_id,
                "collector_id": self.config.collector_id,
                "source_id": source_id,
                "event_type": "infrastructure",
                "event_time_utc": event_time_utc,
                "source_timezone": source_timezone,
                "data": {
                    "cpu_pct": raw_event.get("cpu_pct", 0.0),
                    "memory_pct": raw_event.get("memory_pct", 0.0),
                    "disk_pct": raw_event.get("disk_pct", 0.0),
                    "service_available": bool(raw_event.get("service_available", True)),
                    "service_name": str(raw_event.get("service_name", "service")),
                },
            }

        if etype == "network_metrics":
            return {
                "payload_id": str(uuid.uuid4()),
                "tenant_id": self.config.tenant_id,
                "collector_id": self.config.collector_id,
                "source_id": source_id,
                "event_type": "network",
                "event_time_utc": event_time_utc,
                "source_timezone": source_timezone,
                "data": {
                    "bandwidth_mbps": raw_event.get("bandwidth_mbps", 0.0),
                    "latency_ms": raw_event.get("latency_ms", 0.0),
                    "packet_loss_pct": raw_event.get("packet_loss_pct", 0.0),
                    "connectivity_status": str(raw_event.get("connectivity_status", "up")),
                },
            }

        if etype == "auth_failure_raw":
            reason = str(raw_event.get("reason", "authentication_failure"))
            return self._record_auth_failure_and_maybe_summarize(
                source_id=source_id,
                event_time_utc=event_time_utc,
                source_timezone=source_timezone,
                raw_reason=reason,
            )

        return None

    def process_raw_event(self, raw_event: dict[str, Any]) -> Optional[dict[str, Any]]:
        etype = str(raw_event.get("event_type", "unknown"))
        etime = str(raw_event.get("event_time_utc") or utc_now_iso())

        # 1. Keep raw event locally in SQLite raw_events (never leaves customer environment)
        self.store.record_raw_event(event_type=etype, event_time_utc=etime, raw_event=raw_event)

        # 2. Normalize (or summarize locally for repeated auth failures)
        envelope = self._normalize_to_envelope(raw_event)
        if envelope is None:
            return None

        # 3. Scrub secrets from allow-listed free-text fields
        free_text = self.validator.free_text_data_keys(envelope["event_type"])
        redacted_data, redacted_fields = self.redactor.redact_data_fields(
            envelope["data"], free_text
        )
        envelope["data"] = redacted_data

        # 4. Default-deny allow-list filter
        filtered_envelope, dropped_fields = self.validator.validate_and_filter(
            envelope, strict_reject=False
        )
        all_redacted = sorted(set(redacted_fields + dropped_fields))

        # 5. Write egress_audit & enqueue in SQLite outbound_queue
        audit_info = self.store.enqueue_payload(filtered_envelope, fields_redacted=all_redacted)

        self.logger.info(
            "Payload prepared and queued for egress",
            extra={
                "category": "egress_audit",
                "event": "egress.payload_recorded",
                "tenant_id": self.config.tenant_id,
                "collector_id": self.config.collector_id,
                "payload_id": filtered_envelope["payload_id"],
                "details": {
                    "event_type": filtered_envelope["event_type"],
                    "dropped_count": len(dropped_fields),
                    "redacted_count": len(all_redacted),
                },
            },
        )
        return {
            "envelope": filtered_envelope,
            "dropped_fields": dropped_fields,
            "redacted_fields": all_redacted,
            "audit": audit_info,
        }

    def build_heartbeat_payload(self, last_successful_send_utc: Optional[str] = None) -> dict[str, Any]:
        env: dict[str, Any] = {
            "payload_id": str(uuid.uuid4()),
            "tenant_id": self.config.tenant_id,
            "collector_id": self.config.collector_id,
            "source_id": self.redactor.pseudonymize(self.config.collector_id),
            "event_type": "heartbeat",
            "event_time_utc": utc_now_iso(),
            "source_timezone": self.config.source_timezone,
            "data": {
                "collector_version": self.config.collector_version,
                "resource_cpu_pct": 2.4,
                "resource_memory_mb": 64,
                "config_status": "valid",
                "last_successful_send_utc": last_successful_send_utc or utc_now_iso(),
            },
        }
        filtered, _ = self.validator.validate_and_filter(env, strict_reject=True)
        return filtered
