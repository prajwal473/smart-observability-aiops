from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

DEFAULT_ALLOWLIST: dict[str, Any] = {
    "contract_version": "1.0",
    "envelope_fields": [
        "payload_id",
        "tenant_id",
        "collector_id",
        "source_id",
        "event_type",
        "event_time_utc",
        "source_timezone",
        "data",
    ],
    "required_envelope_fields": [
        "payload_id",
        "tenant_id",
        "collector_id",
        "source_id",
        "event_type",
        "event_time_utc",
        "source_timezone",
        "data",
    ],
    "event_types": {
        "infrastructure": {
            "allowed_data_fields": [
                "cpu_pct",
                "memory_pct",
                "disk_pct",
                "service_available",
                "service_name",
            ],
            "free_text_fields": ["service_name"],
        },
        "network": {
            "allowed_data_fields": [
                "bandwidth_mbps",
                "latency_ms",
                "packet_loss_pct",
                "connectivity_status",
            ],
            "free_text_fields": [],
        },
        "security": {
            "allowed_data_fields": [
                "event_category",
                "severity",
                "count",
                "window_seconds",
                "context",
            ],
            "free_text_fields": ["context"],
        },
        "heartbeat": {
            "allowed_data_fields": [
                "collector_version",
                "resource_cpu_pct",
                "resource_memory_mb",
                "config_status",
                "last_successful_send_utc",
            ],
            "free_text_fields": [],
        },
    },
}


class AllowlistValidator:
    """Default-deny allow-list validator enforcing SHARED_CONTRACTS.md §1-5."""

    def __init__(self, spec: Optional[dict[str, Any]] = None) -> None:
        self.spec = spec or DEFAULT_ALLOWLIST
        self.envelope_fields: set[str] = set(self.spec.get("envelope_fields", []))
        self.required_envelope_fields: set[str] = set(
            self.spec.get("required_envelope_fields", self.envelope_fields)
        )
        self.event_types: dict[str, dict[str, Any]] = self.spec.get("event_types", {})

    @classmethod
    def from_file(cls, path: Path) -> "AllowlistValidator":
        if not path.exists():
            return cls(DEFAULT_ALLOWLIST)
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(data)

    def allowed_data_keys(self, event_type: str) -> set[str]:
        et_cfg = self.event_types.get(event_type)
        if not et_cfg:
            return set()
        return set(et_cfg.get("allowed_data_fields", []))

    def free_text_data_keys(self, event_type: str) -> set[str]:
        et_cfg = self.event_types.get(event_type)
        if not et_cfg:
            return set()
        return set(et_cfg.get("free_text_fields", []))

    def validate_and_filter(
        self,
        envelope: dict[str, Any],
        strict_reject: bool = False,
    ) -> tuple[dict[str, Any], list[str]]:
        """
        Filters an envelope and its nested `data` dict against the allow-list.
        Returns (filtered_payload, dropped_field_paths).
        If strict_reject=True and any disallowed field is present, raises ValueError.
        """
        if not isinstance(envelope, dict):
            raise ValueError("Envelope must be a dict")

        missing = self.required_envelope_fields - envelope.keys()
        if missing:
            raise ValueError(f"Required envelope fields missing: {sorted(missing)}")

        event_type = str(envelope.get("event_type", ""))
        if event_type not in self.event_types:
            raise ValueError(f"Unsupported or missing event_type: '{event_type}'")

        dropped: list[str] = []
        filtered: dict[str, Any] = {}

        for key, val in envelope.items():
            if key not in self.envelope_fields:
                dropped.append(key)
                continue
            filtered[key] = val

        raw_data = envelope.get("data")
        if not isinstance(raw_data, dict):
            raise ValueError("Envelope 'data' must be a dict")

        permitted_data_keys = self.allowed_data_keys(event_type)
        filtered_data: dict[str, Any] = {}
        for dkey, dval in raw_data.items():
            if dkey not in permitted_data_keys:
                dropped.append(f"data.{dkey}")
                continue
            filtered_data[dkey] = dval

        filtered["data"] = filtered_data

        if strict_reject and dropped:
            raise ValueError(f"Disallowed fields rejected: {sorted(dropped)}")

        return filtered, dropped
