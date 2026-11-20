from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


def _load_dotenv_if_present(env_path: Optional[Path]) -> None:
    if not env_path or not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def _env_str(key: str, default: str) -> str:
    return os.environ.get(key, default).strip()


def _env_int(key: str, default: int) -> int:
    val = os.environ.get(key, "").strip()
    return int(val) if val else default


def _env_float(key: str, default: float) -> float:
    val = os.environ.get(key, "").strip()
    return float(val) if val else default


def _env_bool(key: str, default: bool) -> bool:
    val = os.environ.get(key, "").strip().lower()
    if not val:
        return default
    return val in {"1", "true", "yes", "on"}


@dataclass
class CollectorConfig:
    collector_id: str = "col_acme_blr_01"
    tenant_id: str = "tnt_acme_001"
    collector_token: str = "dev-collector-token"
    collector_version: str = "0.1.0"
    source_timezone: str = "Asia/Kolkata"
    saas_base_url: str = "http://localhost:8000"
    saas_verify_tls: bool = False
    saas_ca_bundle_path: str = ""
    connect_timeout_seconds: float = 3.0
    read_timeout_seconds: float = 10.0

    data_dir: Path = Path("./collector-security/data")
    sqlite_path: Path = Path("./collector-security/data/collector.db")
    local_retention_hours: int = 24
    queue_max_mb: float = 100.0
    send_batch_size: int = 50

    collect_interval_seconds: float = 5.0
    send_interval_seconds: float = 5.0
    aggregation_window_seconds: float = 5.0
    heartbeat_interval_seconds: float = 5.0

    retry_initial_delay_seconds: float = 1.0
    retry_max_delay_seconds: float = 60.0
    retry_backoff_factor: float = 2.0
    retry_jitter_seconds: float = 0.5

    pseudonym_salt: str = "dev-pseudonym-salt-change-in-prod"
    allowlist_path: Path = Path("./shared/allowlist.json")
    redaction_rules_path: Path = Path("./shared/redaction_rules.json")
    log_file_path: Path = Path("./logs/collector/collector.log")
    log_level: str = "INFO"

    generator_mode: str = "normal"
    generator_seed: int = 42
    auth_failure_burst_threshold: int = 5
    auth_failure_window_seconds: int = 60
    extra: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_env(cls, config_path: Optional[str | Path] = None) -> "CollectorConfig":
        repo_root = Path(__file__).resolve().parents[2]
        if config_path:
            p = Path(config_path)
            if not p.is_absolute() and not p.exists():
                candidate = repo_root / p
                if candidate.exists():
                    p = candidate
            _load_dotenv_if_present(p)
        else:
            default_env = repo_root / ".env"
            if default_env.exists():
                _load_dotenv_if_present(default_env)

        def resolve_path(env_key: str, default_rel: str) -> Path:
            raw = _env_str(env_key, default_rel)
            pth = Path(raw)
            if not pth.is_absolute():
                return repo_root / pth
            return pth

        log_dir = Path(_env_str("LOG_DIR", str(repo_root / "logs")))
        if not log_dir.is_absolute():
            log_dir = repo_root / log_dir

        return cls(
            collector_id=_env_str("COLLECTOR_ID", "col_acme_blr_01"),
            tenant_id=_env_str("COLLECTOR_TENANT_ID", "tnt_acme_001"),
            collector_token=_env_str("COLLECTOR_TOKEN", "dev-collector-token"),
            collector_version=_env_str("COLLECTOR_VERSION", "0.1.0"),
            source_timezone=_env_str("COLLECTOR_SOURCE_TIMEZONE", "Asia/Kolkata"),
            saas_base_url=_env_str("SAAS_BASE_URL", "http://localhost:8000").rstrip("/"),
            saas_verify_tls=_env_bool("SAAS_VERIFY_TLS", False),
            saas_ca_bundle_path=_env_str("SAAS_CA_BUNDLE_PATH", ""),
            connect_timeout_seconds=_env_float("SAAS_CONNECT_TIMEOUT_SECONDS", 3.0),
            read_timeout_seconds=_env_float("SAAS_READ_TIMEOUT_SECONDS", 10.0),
            data_dir=resolve_path("COLLECTOR_DATA_DIR", "collector-security/data"),
            sqlite_path=resolve_path("COLLECTOR_SQLITE_PATH", "collector-security/data/collector.db"),
            local_retention_hours=_env_int("COLLECTOR_LOCAL_RETENTION_HOURS", 24),
            queue_max_mb=_env_float("COLLECTOR_QUEUE_MAX_MB", 100.0),
            send_batch_size=_env_int("COLLECTOR_SEND_BATCH_SIZE", 50),
            collect_interval_seconds=_env_float("COLLECTOR_COLLECT_INTERVAL_SECONDS", 5.0),
            send_interval_seconds=_env_float("COLLECTOR_SEND_INTERVAL_SECONDS", 5.0),
            aggregation_window_seconds=_env_float("COLLECTOR_AGGREGATION_WINDOW_SECONDS", 5.0),
            heartbeat_interval_seconds=_env_float("HEARTBEAT_INTERVAL_SECONDS", 5.0),
            retry_initial_delay_seconds=_env_float("RETRY_INITIAL_DELAY_SECONDS", 1.0),
            retry_max_delay_seconds=_env_float("RETRY_MAX_DELAY_SECONDS", 60.0),
            retry_backoff_factor=_env_float("RETRY_BACKOFF_FACTOR", 2.0),
            retry_jitter_seconds=_env_float("RETRY_JITTER_SECONDS", 0.5),
            pseudonym_salt=_env_str("PSEUDONYM_SALT", "dev-pseudonym-salt-change-in-prod"),
            allowlist_path=resolve_path("ALLOWLIST_PATH", "shared/allowlist.json"),
            redaction_rules_path=resolve_path("REDACTION_RULES_PATH", "shared/redaction_rules.json"),
            log_file_path=log_dir / "collector" / "collector.log",
            log_level=_env_str("LOG_LEVEL", "INFO").upper(),
            generator_mode=_env_str("GENERATOR_MODE", "normal"),
            generator_seed=_env_int("GENERATOR_SEED", 42),
            auth_failure_burst_threshold=_env_int("AUTH_FAILURE_BURST_THRESHOLD", 5),
            auth_failure_window_seconds=_env_int("AUTH_FAILURE_WINDOW_SECONDS", 60),
        )
