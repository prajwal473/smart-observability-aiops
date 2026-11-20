from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Optional

DEFAULT_SENSITIVE_KEYS = {
    "password",
    "secret",
    "token",
    "authorization",
    "api_key",
    "cookie",
    "private_key",
    "raw_hostname",
    "raw_user",
    "raw_ip",
}

DEFAULT_SECRET_PATTERNS = [
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-~+/=]+"),
    re.compile(r'(?i)(?:password|passwd|pwd|secret|api_key|apikey|token)\s*[:=]\s*[^\s,;"\']+'),
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b"),
]


class RedactionLogFilter(logging.Filter):
    """Sanitizes log messages and extra details so secrets/raw values never appear in logs."""

    def __init__(
        self,
        sensitive_keys: Optional[set[str]] = None,
        patterns: Optional[list[re.Pattern[str]]] = None,
        max_str_len: int = 256,
    ) -> None:
        super().__init__()
        self.sensitive_keys = {k.lower() for k in (sensitive_keys or DEFAULT_SENSITIVE_KEYS)}
        self.patterns = patterns or DEFAULT_SECRET_PATTERNS
        self.max_str_len = max_str_len

    def scrub_text(self, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        out = value
        for pat in self.patterns:
            out = pat.sub("[REDACTED]", out)
        if len(out) > self.max_str_len:
            out = out[: self.max_str_len] + "...[TRUNCATED]"
        return out

    def sanitize_dict(self, data: Optional[dict[str, Any]]) -> dict[str, Any]:
        if not isinstance(data, dict):
            return {}
        clean: dict[str, Any] = {}
        for k, v in data.items():
            key_lower = str(k).lower()
            if key_lower in self.sensitive_keys:
                clean[str(k)] = "[REDACTED]"
                continue
            if isinstance(v, dict):
                clean[str(k)] = self.sanitize_dict(v)
            elif isinstance(v, list):
                clean[str(k)] = [
                    self.sanitize_dict(item) if isinstance(item, dict) else self.scrub_text(item)
                    for item in v
                ]
            else:
                clean[str(k)] = self.scrub_text(v)
        return clean

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = self.scrub_text(str(record.msg))
            raw_details = getattr(record, "details", None)
            record.safe_details = self.sanitize_dict(raw_details)
        except Exception:
            record.safe_details = {}
        return True


class JsonLineFormatter(logging.Formatter):
    """Emits one JSON object per line."""

    def __init__(self, service: str, component: str) -> None:
        super().__init__()
        self.service = service
        self.component = component

    def format(self, record: logging.LogRecord) -> str:
        try:
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            payload: dict[str, Any] = {
                "timestamp_utc": ts,
                "level": record.levelname,
                "service": self.service,
                "component": self.component,
                "category": getattr(record, "category", "collector_activity"),
                "event": getattr(record, "event", "collector.log"),
                "message": record.getMessage(),
                "tenant_id": getattr(record, "tenant_id", None),
                "collector_id": getattr(record, "collector_id", None),
                "payload_id": getattr(record, "payload_id", None),
                "request_id": getattr(record, "request_id", None),
                "trace_id": getattr(record, "trace_id", None),
                "duration_ms": getattr(record, "duration_ms", None),
                "details": getattr(record, "safe_details", {}),
            }
            return json.dumps(payload, default=str)
        except Exception:
            return '{"level":"ERROR","event":"error.logging_format_failed"}'


class _SafeStreamHandler(logging.StreamHandler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            super().emit(record)
        except Exception:
            pass


class _SafeRotatingFileHandler(RotatingFileHandler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            super().emit(record)
        except Exception:
            pass


def get_logger(
    component: str,
    service: str = "collector",
    log_file_path: Optional[Path] = None,
    level: str = "INFO",
    filter_instance: Optional[RedactionLogFilter] = None,
) -> logging.Logger:
    logger_name = f"{service}.{component}"
    logger = logging.getLogger(logger_name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False

    redaction_filter = filter_instance or RedactionLogFilter()
    if not any(isinstance(f, RedactionLogFilter) for f in logger.filters):
        logger.addFilter(redaction_filter)

    formatter = JsonLineFormatter(service=service, component=component)

    if not any(isinstance(h, _SafeStreamHandler) for h in logger.handlers):
        sh = _SafeStreamHandler()
        sh.setFormatter(formatter)
        sh.addFilter(redaction_filter)
        logger.addHandler(sh)

    target_file = log_file_path
    if target_file is None:
        env_log_dir = os.environ.get("LOG_DIR", "").strip()
        if env_log_dir:
            target_file = Path(env_log_dir) / service / f"{service}.log"

    if target_file is not None:
        resolved = str(target_file.resolve())
        already_has_file = any(
            isinstance(h, _SafeRotatingFileHandler) and getattr(h, "_resolved_path", None) == resolved
            for h in logger.handlers
        )
        if not already_has_file:
            try:
                target_file.parent.mkdir(parents=True, exist_ok=True)
                fh = _SafeRotatingFileHandler(
                    filename=str(target_file),
                    maxBytes=10 * 1024 * 1024,
                    backupCount=5,
                    encoding="utf-8",
                )
                fh._resolved_path = resolved  # type: ignore[attr-defined]
                fh.setFormatter(formatter)
                fh.addFilter(redaction_filter)
                logger.addHandler(fh)
            except Exception:
                pass

    return logger
