"""Dependency-free Axle Cloud client with per-device identity.

Existing v2 environment variables continue to work as the shared account
bootstrap credentials:
  AXLE_CLOUD_URL
  AXLE_CLOUD_INSTANCE_ID   (shared account id; legacy name)
  AXLE_CLOUD_API_KEY       (shared account key; legacy name)

Optional clearer aliases are also supported:
  AXLE_CLOUD_ACCOUNT_ID
  AXLE_CLOUD_ACCOUNT_KEY
  AXLE_CLOUD_DEVICE_NAME

Each computer automatically registers its own device credential once and stores
it outside the Axle project at ~/.axle/cloud_device.json. Normal sync requests
then use the per-device credential, while memory/session data remain shared by
the account id.
"""
from __future__ import annotations

import json
import os
import platform
import threading
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class AxleCloudError(RuntimeError):
    pass


class AxleCloudClient:
    def __init__(
        self,
        base_url: str | None = None,
        instance_id: str | None = None,
        api_key: str | None = None,
        timeout: float = 10.0,
    ):
        self.base_url = (base_url or os.getenv("AXLE_CLOUD_URL", "")).rstrip("/")
        self.account_id = (
            instance_id
            or os.getenv("AXLE_CLOUD_ACCOUNT_ID", "")
            or os.getenv("AXLE_CLOUD_INSTANCE_ID", "")
        )
        self.account_key = (
            api_key
            or os.getenv("AXLE_CLOUD_ACCOUNT_KEY", "")
            or os.getenv("AXLE_CLOUD_API_KEY", "")
        )
        self.timeout = timeout

        # Compatibility aliases used by cloud_sync.py and older callers.
        self.instance_id = self.account_id
        self.api_key = self.account_key

        self.device_name = (
            os.getenv("AXLE_CLOUD_DEVICE_NAME", "").strip()
            or platform.node().strip()
            or "Axle Device"
        )
        self.device_id = os.getenv("AXLE_CLOUD_DEVICE_ID", "").strip()
        self.device_key = os.getenv("AXLE_CLOUD_DEVICE_KEY", "").strip()
        self._device_lock = threading.Lock()

        custom_file = os.getenv("AXLE_CLOUD_DEVICE_FILE", "").strip()
        self.device_file = (
            Path(custom_file).expanduser()
            if custom_file
            else Path.home() / ".axle" / "cloud_device.json"
        )

        if not (self.device_id and self.device_key):
            self._load_device_credentials()

    @property
    def configured(self) -> bool:
        # Account key is only needed to bootstrap a new device. Once a device
        # credential exists, the shared account key can be removed locally.
        has_auth = bool(
            (self.device_id and self.device_key)
            or self.account_key
        )
        return bool(self.base_url and self.account_id and has_auth)

    @property
    def using_device_auth(self) -> bool:
        return bool(self.device_id and self.device_key)

    def _load_device_credentials(self) -> None:
        try:
            data = json.loads(self.device_file.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return

        if data.get("base_url", "").rstrip("/") != self.base_url:
            return
        if data.get("account_id") != self.account_id:
            return

        device_id = str(data.get("device_id") or "").strip()
        device_key = str(data.get("device_key") or "").strip()
        if device_id and device_key:
            self.device_id = device_id
            self.device_key = device_key
            saved_name = str(data.get("device_name") or "").strip()
            if saved_name:
                self.device_name = saved_name

    def _save_device_credentials(self) -> None:
        self.device_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "base_url": self.base_url,
            "account_id": self.account_id,
            "device_id": self.device_id,
            "device_key": self.device_key,
            "device_name": self.device_name,
        }
        tmp = self.device_file.with_suffix(self.device_file.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, self.device_file)

    def _send(self, method: str, path: str, payload=None, headers=None):
        data = None
        request_headers = {"Accept": "application/json"}
        if headers:
            request_headers.update(headers)
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            request_headers["Content-Type"] = "application/json"

        req = Request(
            self.base_url + path,
            data=data,
            headers=request_headers,
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

    def ensure_device(self):
        """Register this computer once, then reuse its local device credential."""
        if self.using_device_auth:
            return {
                "account_id": self.account_id,
                "device_id": self.device_id,
                "device_name": self.device_name,
            }

        if not (self.base_url and self.account_id):
            raise AxleCloudError(
                "Axle Cloud is not configured. Set AXLE_CLOUD_URL and "
                "AXLE_CLOUD_INSTANCE_ID (or AXLE_CLOUD_ACCOUNT_ID)."
            )
        if not self.account_key:
            raise AxleCloudError(
                "This computer has no saved device credential yet. Temporarily set "
                "AXLE_CLOUD_API_KEY (or AXLE_CLOUD_ACCOUNT_KEY) so it can register."
            )

        with self._device_lock:
            if self.using_device_auth:
                return {
                    "account_id": self.account_id,
                    "device_id": self.device_id,
                    "device_name": self.device_name,
                }

            data = self._send(
                "POST",
                f"/api/accounts/{self.account_id}/devices",
                {"device_name": self.device_name},
                {"X-API-Key": self.account_key},
            )
            self.device_id = str(data.get("device_id") or "")
            self.device_key = str(data.get("device_key") or "")
            if not self.device_id or not self.device_key:
                raise AxleCloudError("Axle Cloud returned an incomplete device registration")
            self.device_name = str(data.get("device_name") or self.device_name)
            self._save_device_credentials()
            return data

    def _auth_headers(self):
        self.ensure_device()
        return {
            "X-Device-ID": self.device_id,
            "X-Device-Key": self.device_key,
        }

    def _request(self, method: str, path: str, payload=None):
        if not self.configured:
            raise AxleCloudError(
                "Axle Cloud is not configured. Set AXLE_CLOUD_URL, the shared "
                "account ID, and either a saved device credential or account key."
            )
        return self._send(method, path, payload, self._auth_headers())

    def health(self):
        return self._send("GET", "/health")

    def get_memory(self):
        return self._request("GET", f"/api/memory/{self.account_id}")

    def save_memory(self, category: str, key: str, value):
        return self._request(
            "POST",
            f"/api/memory/{self.account_id}",
            {"category": category, "key": key, "value": value},
        )

    def delete_memory(self, category: str, key: str):
        return self._request(
            "DELETE",
            f"/api/memory/{self.account_id}/{category}/{key}",
        )

    def get_session(self):
        try:
            return self._request("GET", f"/api/session/{self.account_id}")
        except AxleCloudError as e:
            if "HTTP 404" in str(e):
                return None
            raise

    def save_session(self, session_data: dict, conversation_history: list):
        session_data = dict(session_data or {})
        self.ensure_device()
        session_data.setdefault("device_id", self.device_id)
        session_data.setdefault("device_name", self.device_name)
        return self._request(
            "POST",
            f"/api/session/{self.account_id}",
            {
                "session_data": session_data,
                "conversation_history": conversation_history,
            },
        )

    def append_history(self, role: str, content: str):
        return self._request(
            "POST",
            f"/api/session/{self.account_id}/history",
            {"message": {"role": role, "content": content}},
        )

    def list_devices(self):
        if not self.account_key:
            raise AxleCloudError("AXLE_CLOUD_API_KEY / AXLE_CLOUD_ACCOUNT_KEY is required to list devices")
        return self._send(
            "GET",
            f"/api/accounts/{self.account_id}/devices",
            headers={"X-API-Key": self.account_key},
        )

    def revoke_device(self, device_id: str):
        if not self.account_key:
            raise AxleCloudError("AXLE_CLOUD_API_KEY / AXLE_CLOUD_ACCOUNT_KEY is required to revoke devices")
        return self._send(
            "DELETE",
            f"/api/accounts/{self.account_id}/devices/{device_id}",
            headers={"X-API-Key": self.account_key},
        )

    def identity(self):
        self.ensure_device()
        return {
            "account_id": self.account_id,
            "device_id": self.device_id,
            "device_name": self.device_name,
            "credential_file": str(self.device_file),
        }


cloud = AxleCloudClient()
