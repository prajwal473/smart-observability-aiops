from __future__ import annotations

import ipaddress
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit


class CollectorConfigurationError(ValueError):
    """Raised when collector settings violate the selected environment's requirements."""


_DEVELOPMENT_TOKENS = {
    "dev-collector-token",
    "development-token",
    "test-token",
    "dummy-token",
    "replace-with-token-from-seed-script",
    "change-me-dev-only",
    "changeme",
    "your-token-here",
}
_DEVELOPMENT_SALTS = {
    "dev-pseudonym-salt-change-in-prod",
    "replace-with-generated-salt",
    "changeme",
    "your-secret-here",
}
MIN_PRODUCTION_TOKEN_BYTES = 32


def _production_config_errors(config: "CollectorConfig") -> list[str]:
    errors: list[str] = []
    environment = config.app_env.strip().lower()

    if environment not in {"development", "demo", "production"}:
        errors.append("APP_ENV must be development, demo, or production.")
        return errors

    try:
        parsed_url = urlsplit(config.saas_base_url)
        hostname = (parsed_url.hostname or "").lower()
        port = parsed_url.port
    except ValueError:
        parsed_url = None
        hostname = ""
        port = None

    if parsed_url is None or parsed_url.scheme not in {"http", "https"} or not hostname:
        errors.append("SAAS_BASE_URL must be a valid HTTP or HTTPS URL with a hostname.")
        return errors

    if parsed_url.scheme == "http" and environment in {"development", "demo"}:
        is_localhost = hostname == "localhost"
        try:
            is_loopback = ipaddress.ip_address(hostname).is_loopback
        except ValueError:
            is_loopback = False
        is_internal_docker_backend = (
            hostname == "backend"
            and port == 8000
            and parsed_url.username is None
            and parsed_url.password is None
            and parsed_url.path in {"", "/"}
            and not parsed_url.query
            and not parsed_url.fragment
        )
        if not (is_localhost or is_loopback or is_internal_docker_backend):
            errors.append(
                "SAAS_BASE_URL may use HTTP only with localhost or a loopback address, "
                "or the internal Docker service backend:8000."
            )

    if not math.isfinite(config.queue_max_mb) or config.queue_max_mb <= 0:
        errors.append("COLLECTOR_QUEUE_MAX_MB must be greater than zero.")
    if config.local_retention_hours <= 0:
        errors.append("COLLECTOR_LOCAL_RETENTION_HOURS must be greater than zero.")

    if environment == "production":
        if parsed_url.scheme != "https":
            errors.append("SAAS_BASE_URL must use HTTPS when APP_ENV=production.")
        if not config.saas_verify_tls:
            errors.append("SAAS_VERIFY_TLS must be true when APP_ENV=production.")
        if parsed_url.username is not None or parsed_url.password is not None:
            errors.append("SAAS_BASE_URL must not contain embedded credentials.")
        if parsed_url.query or parsed_url.fragment:
            errors.append("SAAS_BASE_URL must not contain a query string or fragment.")

        token = config.collector_token.strip()
        token_lower = token.lower()
        if (
            len(token.encode("utf-8")) < MIN_PRODUCTION_TOKEN_BYTES
            or token_lower in _DEVELOPMENT_TOKENS
            or token_lower.startswith(
                ("replace-with-", "change-me", "dev-", "test-", "dummy-")
            )
        ):
            errors.append(
                "COLLECTOR_TOKEN must be a non-default registered token of at least "
                f"{MIN_PRODUCTION_TOKEN_BYTES} bytes. Generate one with "
                "secrets.token_urlsafe(32)."
            )

        salt = config.pseudonym_salt.strip()
        salt_lower = salt.lower()
        if (
            len(salt.encode("utf-8")) < 32
            or len(set(salt)) < 16
            or salt_lower in _DEVELOPMENT_SALTS
            or salt_lower.startswith(("replace-with-", "change-me", "dev-", "test-", "dummy-"))
        ):
            errors.append(
                "PSEUDONYM_SALT must be a non-default value of at least 32 bytes with at least 16 distinct characters."
            )
    return errors


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
    app_env: str = "development"
    collector_id: str = "col_acme_blr_01"
    tenant_id: str = "tnt_acme_001"
    collector_token: str = field(default="dev-collector-token", repr=False)
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

    pseudonym_salt: str = field(default="dev-pseudonym-salt-change-in-prod", repr=False)
    allowlist_path: Path = Path("./shared/allowlist.json")
    redaction_rules_path: Path = Path("./shared/redaction_rules.json")
    log_file_path: Path = Path("./logs/collector/collector.log")
    log_level: str = "INFO"

    generator_mode: str = "normal"
    generator_seed: int = 42
    auth_failure_burst_threshold: int = 5
    auth_failure_window_seconds: int = 60
    extra: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        errors = _production_config_errors(self)
        if errors:
            raise CollectorConfigurationError("Invalid collector configuration: " + " ".join(errors))

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
            app_env=_env_str("APP_ENV", "development").lower(),
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
