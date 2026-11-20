from __future__ import annotations

import hashlib
import hmac
import json
import re
from pathlib import Path
from typing import Any, Optional

DEFAULT_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED]"),
    ("bearer_token", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-~+/=]+"), "Bearer [REDACTED]"),
    (
        "password_assignment",
        re.compile(r'(?i)(?:password|passwd|pwd|secret|api_key|apikey|token)\s*[:=]\s*[^\s,;"\']+'),
        "[REDACTED]",
    ),
    (
        "private_key_block",
        re.compile(
            r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----.*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
            re.DOTALL,
        ),
        "[REDACTED]",
    ),
    ("credit_card_like", re.compile(r"\b(?:\d[ -]*?){13,16}\b"), "[REDACTED]"),
    (
        "email_address",
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
        "[REDACTED]",
    ),
    (
        "ipv4_address",
        re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b"),
        "[REDACTED]",
    ),
]


def pseudonymize_source_id(real_identifier: str, tenant_salt: str, prefix: str = "src_") -> str:
    """
    Generates a deterministic, non-reversible pseudonymous source identifier:
    HMAC-SHA256(tenant_salt, real_identifier) truncated to 10 hex chars with prefix `src_`.
    """
    digest = hmac.new(
        key=tenant_salt.encode("utf-8"),
        msg=real_identifier.strip().encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()
    return f"{prefix}{digest[:10]}"


class RedactionEngine:
    """Scrubs secrets and sensitive identifiers from free-text and structured values."""

    def __init__(
        self,
        pseudonym_salt: str,
        patterns: Optional[list[tuple[str, re.Pattern[str], str]]] = None,
    ) -> None:
        self.pseudonym_salt = pseudonym_salt
        self.patterns = patterns if patterns is not None else DEFAULT_PATTERNS

    @classmethod
    def from_rules_file(cls, path: Path, pseudonym_salt: str) -> "RedactionEngine":
        if not path.exists():
            return cls(pseudonym_salt=pseudonym_salt)
        raw = json.loads(path.read_text(encoding="utf-8"))
        compiled: list[tuple[str, re.Pattern[str], str]] = []
        for entry in raw.get("secret_patterns", []):
            name = str(entry.get("name", "custom"))
            pat_str = str(entry.get("pattern", ""))
            repl = str(entry.get("replacement", "[REDACTED]"))
            flags = re.DOTALL if "PRIVATE KEY" in pat_str else 0
            compiled.append((name, re.compile(pat_str, flags=flags), repl))
        return cls(pseudonym_salt=pseudonym_salt, patterns=compiled or DEFAULT_PATTERNS)

    def scrub_string(self, text: str) -> tuple[str, list[str]]:
        """Scrubs secret/sensitive substrings from `text`; returns (cleaned_text, matched_rule_names)."""
        cleaned = text
        matched: list[str] = []
        for rule_name, regex, replacement in self.patterns:
            new_val, count = regex.subn(replacement, cleaned)
            if count > 0:
                matched.append(rule_name)
                cleaned = new_val
        return cleaned, matched

    def redact_data_fields(
        self,
        data: dict[str, Any],
        free_text_fields: set[str],
    ) -> tuple[dict[str, Any], list[str]]:
        """
        Scrubs allow-listed free-text fields and flags any field where secrets were scrubbed.
        Returns (redacted_data, redacted_field_names).
        """
        out = dict(data)
        redacted_fields: list[str] = []
        for field_name in sorted(free_text_fields):
            if field_name in out and isinstance(out[field_name], str):
                scrubbed, hits = self.scrub_string(out[field_name])
                if hits:
                    out[field_name] = scrubbed
                    redacted_fields.append(f"data.{field_name}")
        return out, redacted_fields

    def pseudonymize(self, real_identifier: str) -> str:
        return pseudonymize_source_id(real_identifier, self.pseudonym_salt)
