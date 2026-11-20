from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional


def _iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class TelemetryGenerator:
    """Deterministic raw telemetry generator for Member 1 testing and demo modes."""

    SUPPORTED_MODES = {
        "normal",
        "cpu_spike",
        "memory_spike",
        "latency_spike",
        "packet_loss",
        "failed_logins",
        "sensitive",
        "out_of_order",
    }

    def __init__(
        self,
        seed: int = 42,
        mode: str = "normal",
        source_timezone: str = "Asia/Kolkata",
        hosts: Optional[list[str]] = None,
    ) -> None:
        self.seed = seed
        self.mode = mode if mode in self.SUPPORTED_MODES else "normal"
        self.source_timezone = source_timezone
        self.hosts = hosts or [
            "db-primary.internal.acme.local",
            "app-worker-01.internal.acme.local",
            "edge-gw-01.internal.acme.local",
        ]
        self.rng = random.Random(seed)
        self.tick = 0

    def set_mode(self, mode: str) -> None:
        if mode not in self.SUPPORTED_MODES:
            raise ValueError(f"Unsupported generator mode: '{mode}'")
        self.mode = mode

    def generate_raw_batch(
        self,
        now_utc: Optional[datetime] = None,
        mode: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        active_mode = mode if mode in self.SUPPORTED_MODES else self.mode
        base_dt = now_utc or datetime.now(timezone.utc)
        self.tick += 1
        host = self.hosts[(self.tick - 1) % len(self.hosts)]
        raw_ip = f"10.24.{((self.tick - 1) % 4) + 1}.{10 + (self.tick % 40)}"

        event_dt = base_dt
        if active_mode == "out_of_order" and self.tick % 2 == 0:
            event_dt = base_dt - timedelta(seconds=25)

        cpu_pct = round(38.0 + self.rng.uniform(-4.5, 5.0), 1)
        memory_pct = round(58.0 + self.rng.uniform(-3.0, 4.0), 1)
        disk_pct = round(66.0 + self.rng.uniform(-1.0, 1.5), 1)
        bandwidth_mbps = round(780.0 + self.rng.uniform(-60.0, 90.0), 1)
        latency_ms = round(22.0 + self.rng.uniform(-3.0, 5.0), 1)
        packet_loss_pct = round(max(0.0, 0.1 + self.rng.uniform(-0.05, 0.15)), 2)
        connectivity_status = "up"

        if active_mode == "cpu_spike":
            cpu_pct = round(92.0 + self.rng.uniform(0.0, 6.5), 1)
        elif active_mode == "memory_spike":
            memory_pct = round(90.5 + self.rng.uniform(0.0, 6.0), 1)
        elif active_mode == "latency_spike":
            latency_ms = round(185.0 + self.rng.uniform(10.0, 65.0), 1)
            bandwidth_mbps = round(320.0 + self.rng.uniform(-20.0, 40.0), 1)
        elif active_mode == "packet_loss":
            packet_loss_pct = round(6.5 + self.rng.uniform(0.5, 4.0), 2)
            connectivity_status = "degraded"

        infra_raw: dict[str, Any] = {
            "raw_event_id": str(uuid.uuid4()),
            "event_type": "infrastructure_metrics",
            "host": host,
            "raw_ip": raw_ip,
            "raw_user": "ops_admin@acme.example",
            "event_time_utc": _iso_utc(event_dt),
            "source_timezone": self.source_timezone,
            "cpu_pct": cpu_pct,
            "memory_pct": memory_pct,
            "disk_pct": disk_pct,
            "service_available": True,
            "service_name": "db-primary" if "db" in host else "app-worker",
            "debug_process_cmd": "/usr/bin/java -Dapi_key=AKIAFAKEFAKEFAKE0000",
        }

        net_raw: dict[str, Any] = {
            "raw_event_id": str(uuid.uuid4()),
            "event_type": "network_metrics",
            "host": host,
            "raw_ip": raw_ip,
            "event_time_utc": _iso_utc(event_dt),
            "source_timezone": self.source_timezone,
            "bandwidth_mbps": bandwidth_mbps,
            "latency_ms": latency_ms,
            "packet_loss_pct": packet_loss_pct,
            "connectivity_status": connectivity_status,
            "interface_mac": "02:42:ac:11:00:08",
        }

        events: list[dict[str, Any]] = [infra_raw, net_raw]

        if active_mode == "failed_logins":
            for idx in range(6):
                events.append(
                    {
                        "raw_event_id": str(uuid.uuid4()),
                        "event_type": "auth_failure_raw",
                        "host": host,
                        "raw_ip": f"198.51.100.{20 + idx}",
                        "raw_user": f"user_{idx}@acme.example",
                        "event_time_utc": _iso_utc(event_dt),
                        "source_timezone": self.source_timezone,
                        "reason": "invalid_password",
                    }
                )
        elif active_mode == "sensitive":
            events.append(
                {
                    "raw_event_id": str(uuid.uuid4()),
                    "event_type": "auth_failure_raw",
                    "host": host,
                    "raw_ip": "203.0.113.77",
                    "raw_user": "alice@acme.example",
                    "event_time_utc": _iso_utc(event_dt),
                    "source_timezone": self.source_timezone,
                    "reason": (
                        "Auth failed for alice@acme.example from 203.0.113.77 "
                        "key=AKIAFAKEFAKEFAKE0000 password=hunter2-FAKE token=Bearer FAKE.TOKEN.VALUE"
                    ),
                }
            )

        return events
