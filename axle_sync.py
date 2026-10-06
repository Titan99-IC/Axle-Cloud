"""Small dependency-free client for the Axle Cloud REST API.

Configure with environment variables:
  AXLE_CLOUD_URL
  AXLE_CLOUD_INSTANCE_ID
  AXLE_CLOUD_API_KEY

Use the same instance ID + API key on every trusted Axle device that should
share the same cloud memory/session in this first version.
"""
from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class AxleCloudError(RuntimeError):
    pass


class AxleCloudClient:
    def __init__(self, base_url: str | None = None, instance_id: str | None = None,
                 api_key: str | None = None, timeout: float = 10.0):
        self.base_url = (base_url or os.getenv("AXLE_CLOUD_URL", "")).rstrip("/")
        self.instance_id = instance_id or os.getenv("AXLE_CLOUD_INSTANCE_ID", "")
        self.api_key = api_key or os.getenv("AXLE_CLOUD_API_KEY", "")
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.instance_id and self.api_key)

    def _request(self, method: str, path: str, payload=None):
        if not self.configured:
            raise AxleCloudError(
                "Axle Cloud is not configured. Set AXLE_CLOUD_URL, "
                "AXLE_CLOUD_INSTANCE_ID, and AXLE_CLOUD_API_KEY."
            )

        data = None
        headers = {
            "Accept": "application/json",
            "X-API-Key": self.api_key,
        }
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = Request(
            self.base_url + path,
            data=data,
            headers=headers,
            method=method,
        )

        try:
            with urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else None
        except HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise AxleCloudError(f"Axle Cloud HTTP {e.code}: {body}") from e
        except URLError as e:
            raise AxleCloudError(f"Axle Cloud connection failed: {e.reason}") from e

    def health(self):
        # Health is intentionally public and does not need instance auth.
        req = Request(self.base_url + "/health", headers={"Accept": "application/json"})
        try:
            with urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            raise AxleCloudError(f"Axle Cloud health check failed: {e}") from e

    def get_memory(self):
        return self._request("GET", f"/api/memory/{self.instance_id}")

    def save_memory(self, category: str, key: str, value):
        return self._request(
            "POST",
            f"/api/memory/{self.instance_id}",
            {"category": category, "key": key, "value": value},
        )

    def delete_memory(self, category: str, key: str):
        return self._request(
            "DELETE",
            f"/api/memory/{self.instance_id}/{category}/{key}",
        )

    def get_session(self):
        try:
            return self._request("GET", f"/api/session/{self.instance_id}")
        except AxleCloudError as e:
            if "HTTP 404" in str(e):
                return None
            raise

    def save_session(self, session_data: dict, conversation_history: list):
        return self._request(
            "POST",
            f"/api/session/{self.instance_id}",
            {
                "session_data": session_data,
                "conversation_history": conversation_history,
            },
        )

    def append_history(self, role: str, content: str):
        return self._request(
            "POST",
            f"/api/session/{self.instance_id}/history",
            {"message": {"role": role, "content": content}},
        )


cloud = AxleCloudClient()
