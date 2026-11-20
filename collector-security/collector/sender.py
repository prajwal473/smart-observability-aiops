from __future__ import annotations

import random
import time
from typing import Any, Optional

import requests

from collector.config import CollectorConfig
from collector.logger import get_logger
from collector.store import CollectorStore, utc_now_iso


def compute_backoff_delay(
    consecutive_failures: int,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
    max_delay: float = 60.0,
    jitter_max: float = 0.5,
    rng: Optional[random.Random] = None,
) -> float:
    failures = max(1, consecutive_failures)
    base = min(max_delay, initial_delay * (backoff_factor ** (failures - 1)))
    jitter_rng = rng or random
    jitter = jitter_rng.uniform(0.0, max(0.0, jitter_max)) if jitter_max > 0 else 0.0
    return round(base + jitter, 4)


class CollectorSender:
    """Drains queued payloads over HTTP/HTTPS with backoff + jitter and sends collector heartbeats."""

    def __init__(
        self,
        config: CollectorConfig,
        store: CollectorStore,
        session: Optional[requests.Session] = None,
        rng: Optional[random.Random] = None,
    ) -> None:
        self.config = config
        self.store = store
        self.session = session or requests.Session()
        self.rng = rng or random.Random(config.generator_seed)
        self.consecutive_failures = 0
        self.auth_paused = False
        self.last_successful_send_utc: Optional[str] = None
        self.logger = get_logger(
            component="sender",
            log_file_path=config.log_file_path,
            level=config.log_level,
        )

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config.collector_token}",
            "Content-Type": "application/json",
        }

    def _verify_param(self) -> bool | str:
        if not self.config.saas_verify_tls:
            return False
        if self.config.saas_ca_bundle_path:
            return self.config.saas_ca_bundle_path
        return True

    def _exception_error_summary(self, exc: Exception) -> str:
        if isinstance(exc, requests.exceptions.SSLError):
            category, message = "tls_error", "TLS connection or certificate verification failed."
        elif isinstance(exc, requests.exceptions.Timeout):
            category, message = "timeout", "The request timed out."
        elif isinstance(exc, requests.exceptions.ConnectionError):
            category, message = "connection_error", "The connection to the backend failed."
        elif isinstance(exc, requests.exceptions.RequestException):
            category, message = "request_error", "The HTTP request failed."
        else:
            category, message = "unexpected_error", "The sender encountered an unexpected error."
        return f"ERROR [{category}]: {message} Exception details omitted."

    @staticmethod
    def _http_error_summary(status_code: int, category: str, message: str) -> str:
        return f"HTTP {status_code} [{category}]: {message}"

    def send_batch_once(self, batch_size: Optional[int] = None) -> dict[str, Any]:
        if self.auth_paused:
            self.logger.warning(
                "Transmission paused due to authentication failure",
                extra={
                    "category": "reliability",
                    "event": "auth.failed",
                    "tenant_id": self.config.tenant_id,
                    "collector_id": self.config.collector_id,
                },
            )
            return {"sent": 0, "failed": 0, "rejected": 0, "paused_auth": True}

        limit = batch_size or self.config.send_batch_size
        batch = self.store.fetch_due_batch(batch_size=limit)
        if not batch:
            return {"sent": 0, "failed": 0, "rejected": 0, "paused_auth": False}

        sent_count = 0
        failed_count = 0
        rejected_count = 0
        url = f"{self.config.saas_base_url}/v1/ingest"
        timeout = (self.config.connect_timeout_seconds, self.config.read_timeout_seconds)

        for item_index, item in enumerate(batch):
            pid = item["payload_id"]
            try:
                resp = self.session.post(
                    url,
                    data=item["body_json"].encode("utf-8"),
                    headers=self._headers(),
                    timeout=timeout,
                    verify=self._verify_param(),
                )
                code = resp.status_code

                if 200 <= code < 300:
                    now_ts = utc_now_iso()
                    self.store.mark_delivered(pid, delivered_at_utc=now_ts)
                    self.last_successful_send_utc = now_ts
                    self.consecutive_failures = 0
                    sent_count += 1
                    self.logger.info(
                        "Delivered payload to SaaS ingest",
                        extra={
                            "category": "transmission",
                            "event": "transmit.success",
                            "tenant_id": self.config.tenant_id,
                            "collector_id": self.config.collector_id,
                            "payload_id": pid,
                            "details": {"status_code": code, "attempt": item["attempts"]},
                        },
                    )
                elif code == 409:
                    now_ts = utc_now_iso()
                    self.store.mark_delivered(pid, delivered_at_utc=now_ts)
                    self.last_successful_send_utc = now_ts
                    self.consecutive_failures = 0
                    sent_count += 1
                    self.logger.info(
                        "Duplicate payload already accepted by SaaS (idempotent)",
                        extra={
                            "category": "transmission",
                            "event": "transmit.duplicate_idempotent",
                            "tenant_id": self.config.tenant_id,
                            "collector_id": self.config.collector_id,
                            "payload_id": pid,
                            "details": {"status_code": code, "attempt": item["attempts"]},
                        },
                    )
                elif code in (401, 403):
                    self.auth_paused = True
                    self.consecutive_failures += 1
                    delay = compute_backoff_delay(
                        self.consecutive_failures,
                        self.config.retry_initial_delay_seconds,
                        self.config.retry_backoff_factor,
                        self.config.retry_max_delay_seconds,
                        self.config.retry_jitter_seconds,
                        rng=self.rng,
                    )
                    error_summary = self._http_error_summary(
                        code, "authentication_error", "Authentication was rejected; transmission paused."
                    )
                    # fetch_due_batch has already marked every row in the batch
                    # in_flight. Return the current and untouched rows to pending
                    # before pausing so none are stranded until process restart.
                    for unprocessed in batch[item_index:]:
                        self.store.reschedule_retry(
                            unprocessed["payload_id"], delay, error_summary
                        )
                    failed_count += len(batch) - item_index
                    self.logger.warning(
                        "Collector authentication rejected; pausing transmission",
                        extra={
                            "category": "reliability",
                            "event": "auth.failed",
                            "tenant_id": self.config.tenant_id,
                            "collector_id": self.config.collector_id,
                            "payload_id": pid,
                            "details": {"status_code": code, "retry_in_s": delay},
                        },
                    )
                    break
                elif code in (400, 422):
                    self.store.mark_rejected(
                        pid,
                        self._http_error_summary(
                            code,
                            "schema_rejected",
                            "The backend rejected the payload; response body omitted.",
                        ),
                    )
                    rejected_count += 1
                    self.logger.error(
                        "Payload permanently rejected by schema validation",
                        extra={
                            "category": "transmission",
                            "event": "ingest.rejected",
                            "tenant_id": self.config.tenant_id,
                            "collector_id": self.config.collector_id,
                            "payload_id": pid,
                            "details": {"status_code": code},
                        },
                    )
                else:
                    self.consecutive_failures += 1
                    delay = compute_backoff_delay(
                        self.consecutive_failures,
                        self.config.retry_initial_delay_seconds,
                        self.config.retry_backoff_factor,
                        self.config.retry_max_delay_seconds,
                        self.config.retry_jitter_seconds,
                        rng=self.rng,
                    )
                    self.store.reschedule_retry(
                        pid,
                        delay,
                        self._http_error_summary(
                            code, "transient_http_error", "The backend returned a retryable response."
                        ),
                    )
                    failed_count += 1
                    self.logger.warning(
                        "Transient ingest response; scheduled retry",
                        extra={
                            "category": "reliability",
                            "event": "retry.scheduled",
                            "tenant_id": self.config.tenant_id,
                            "collector_id": self.config.collector_id,
                            "payload_id": pid,
                            "details": {"status_code": code, "retry_in_s": delay},
                        },
                    )
            except Exception as exc:
                self.consecutive_failures += 1
                delay = compute_backoff_delay(
                    self.consecutive_failures,
                    self.config.retry_initial_delay_seconds,
                    self.config.retry_backoff_factor,
                    self.config.retry_max_delay_seconds,
                    self.config.retry_jitter_seconds,
                    rng=self.rng,
                )
                self.store.reschedule_retry(pid, delay, self._exception_error_summary(exc))
                failed_count += 1
                self.logger.warning(
                    "SaaS unreachable; payload remains buffered for retry",
                    extra={
                        "category": "reliability",
                        "event": "saas.unreachable",
                        "tenant_id": self.config.tenant_id,
                        "collector_id": self.config.collector_id,
                        "payload_id": pid,
                        "details": {"retry_in_s": delay, "attempts": item["attempts"]},
                    },
                )

        return {
            "sent": sent_count,
            "failed": failed_count,
            "rejected": rejected_count,
            "paused_auth": self.auth_paused,
        }

    def send_heartbeat(self, heartbeat_data: dict[str, Any]) -> bool:
        url = f"{self.config.saas_base_url}/v1/collectors/{self.config.collector_id}/heartbeat"
        timeout = (self.config.connect_timeout_seconds, self.config.read_timeout_seconds)
        try:
            resp = self.session.post(
                url,
                json=heartbeat_data,
                headers=self._headers(),
                timeout=timeout,
                verify=self._verify_param(),
            )
            ok = 200 <= resp.status_code < 300
            if ok:
                self.logger.info(
                    "Sent collector heartbeat",
                    extra={
                        "category": "collector_activity",
                        "event": "collector.heartbeat_sent",
                        "tenant_id": self.config.tenant_id,
                        "collector_id": self.config.collector_id,
                    },
                )
            return ok
        except Exception:
            return False

    def sleep_backoff(self) -> None:
        if self.consecutive_failures <= 0:
            time.sleep(max(0.1, self.config.send_interval_seconds))
            return
        delay = compute_backoff_delay(
            self.consecutive_failures,
            self.config.retry_initial_delay_seconds,
            self.config.retry_backoff_factor,
            self.config.retry_max_delay_seconds,
            self.config.retry_jitter_seconds,
            rng=self.rng,
        )
        time.sleep(delay)
