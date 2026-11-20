"""
Client for retrieving telemetry from the Smart Observability backend.
"""

import urllib.error
import urllib.request
import json


def fetch_backend_telemetry(
    base_url: str = "http://127.0.0.1:8000",
    tenant_id: str = "tenant-001",
    limit: int = 100,
    timeout: int = 10,
) -> list[dict]:
    """
    Fetch telemetry events from the backend REST API.

    Raises RuntimeError when the backend request fails.
    """

    if not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")

    url = (
        f"{base_url.rstrip('/')}/api/v1/telemetry/"
        f"{tenant_id}/events?limit={limit}"
    )

    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json"},
        method="GET",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))

    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            f"Backend returned HTTP {exc.code}"
        ) from exc

    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Unable to connect to backend: {exc.reason}"
        ) from exc

    if not isinstance(payload, list):
        raise RuntimeError("Backend response was not a telemetry list")

    return payload