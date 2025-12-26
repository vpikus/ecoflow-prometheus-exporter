import hashlib
import hmac
import logging as log
import random
import time
import urllib.parse
from typing import Any

import requests

from .base import EcoflowApiClient
from .models import DeviceInfo, EcoflowApiException

HOST = "https://api.ecoflow.com"
DEVICE_LIST_URL = HOST + "/iot-open/sign/device/list"
GET_ALL_QUOTA_URL = HOST + "/iot-open/sign/device/quota/all"


class RestApiAuthentication:
    """HMAC-SHA256 signature generation for EcoFlow REST API."""

    def __init__(self, access_key: str, secret_key: str):
        self.access_key = access_key
        self.secret_key = secret_key

    def build_signature(self, message: str) -> str:
        """Build HMAC-SHA256 signature for API request."""
        log.debug("Message: %s", message)
        signature = hmac.new(
            self.secret_key.encode(), message.encode(), hashlib.sha256
        ).hexdigest()
        return signature


class RestApiClient(EcoflowApiClient):
    """REST API client using developer tokens (access_key/secret_key)."""

    def __init__(self, access_key: str, secret_key: str):
        self.auth = RestApiAuthentication(access_key, secret_key)
        self._devices_cache: list[DeviceInfo] | None = None

    def connect(self) -> None:
        """Validate credentials by fetching device list."""
        self._devices_cache = None
        devices = self.get_devices()
        log.info("Connected to EcoFlow API. Found %d device(s)", len(devices))

    def get_devices(self) -> list[DeviceInfo]:
        """Get list of registered devices."""
        data = self._execute_request("GET", DEVICE_LIST_URL, {})
        devices = [self._parse_device(d) for d in data]
        self._devices_cache = devices
        return devices

    def get_device(self, device_sn: str) -> DeviceInfo | None:
        """Get specific device info by serial number."""
        devices = self._devices_cache or self.get_devices()
        return next((d for d in devices if d.sn == device_sn), None)

    def get_device_quota(self, device_sn: str) -> dict[str, Any]:
        """Get device statistics/metrics."""
        return self._execute_request("GET", GET_ALL_QUOTA_URL, {"sn": device_sn})

    def _execute_request(
        self, method: str, url: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute signed API request."""
        sign_params = dict(params)
        sign_params.update(
            {
                "accessKey": self.auth.access_key,
                "nonce": f"{random.randint(100000, 999999)}",
                "timestamp": f"{int(time.time() * 1000)}",
            }
        )

        headers = {
            "sign": self.auth.build_signature(urllib.parse.urlencode(sign_params)),
        }
        headers.update(sign_params)

        response = requests.request(method, url, headers=headers, params=params)
        json_data = response.json()
        log.debug("Payload: %s", json_data)

        return self._unwrap_response(json_data)

    def _unwrap_response(self, response: dict[str, Any]) -> Any:
        """Extract data from API response or raise exception."""
        if str(response.get("message", "")).lower() == "success":
            return response.get("data", {})
        raise EcoflowApiException(f"API error: {response.get('message')}")

    def _parse_device(self, data: dict[str, Any]) -> DeviceInfo:
        """Parse device data from API response."""
        return DeviceInfo(
            sn=data.get("sn", ""),
            name=data.get("deviceName", ""),
            product_name=data.get("productName", ""),
            online=data.get("online", 0) == 1,
        )
