import hashlib
import hmac
import json
import logging as log
import os
import secrets
import time
import urllib.parse
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..metrics import get_analytics
from .base import EcoflowApiClient
from .models import DeviceInfo, EcoflowApiException

# Configuration via environment variables
ECOFLOW_API_HOST = os.getenv("ECOFLOW_API_HOST", "api-e.ecoflow.com")
HTTP_TIMEOUT = int(os.getenv("HTTP_TIMEOUT", "30"))
HTTP_RETRIES = int(os.getenv("HTTP_RETRIES", "3"))
HTTP_BACKOFF_FACTOR = float(os.getenv("HTTP_BACKOFF_FACTOR", "0.5"))
DEVICE_LIST_CACHE_TTL = int(os.getenv("DEVICE_LIST_CACHE_TTL", "60"))

# API endpoints
HOST = f"https://{ECOFLOW_API_HOST}"
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
        signature = hmac.new(self.secret_key.encode(), message.encode(), hashlib.sha256).hexdigest()
        return signature


def _create_session() -> requests.Session:
    """Create a requests session with retry logic and connection pooling."""
    session = requests.Session()

    # Configure retry strategy with exponential backoff
    retry_strategy = Retry(
        total=HTTP_RETRIES,
        backoff_factor=HTTP_BACKOFF_FACTOR,
        status_forcelist=[429, 500, 502, 503, 504],  # Retry on these status codes
        allowed_methods=["GET", "POST"],
        raise_on_status=False,  # Don't raise, let us handle it
    )

    adapter = HTTPAdapter(
        max_retries=retry_strategy,
        pool_connections=10,
        pool_maxsize=10,
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    return session


class RestApiClient(EcoflowApiClient):
    """REST API client using developer tokens (access_key/secret_key).

    Features:
    - Connection pooling for efficient HTTP requests
    - Automatic retry with exponential backoff on transient failures
    - Configurable timeouts via environment variables
    """

    def __init__(self, access_key: str, secret_key: str):
        self.auth = RestApiAuthentication(access_key, secret_key)
        self._devices_cache: list[DeviceInfo] | None = None
        self._devices_cache_time: float | None = None
        self._session: requests.Session | None = None

    def connect(self) -> None:
        """Validate credentials by fetching device list."""
        # Create session with connection pooling
        self._session = _create_session()

        self._devices_cache = None
        self._devices_cache_time = None
        devices = self.get_devices()
        log.info("Connected to EcoFlow API. Found %d device(s)", len(devices))

    def disconnect(self) -> None:
        """Close the session and release resources."""
        if self._session:
            self._session.close()
            self._session = None

    def get_devices(self) -> list[DeviceInfo]:
        """Get list of registered devices.

        Note: This method always fetches from the API and refreshes the cache.
        Cache hit/miss metrics are tracked in get_device() which checks cache
        validity before calling this method. Direct calls (e.g., from connect())
        are cache initialization, not cache lookups.
        """
        data = self._execute_request("GET", DEVICE_LIST_URL, {})
        devices = [self._parse_device(d) for d in data]
        self._devices_cache = devices
        self._devices_cache_time = time.time()
        return devices

    def get_device(self, device_sn: str) -> DeviceInfo | None:
        """Get specific device info by serial number.

        Cache metrics track lookup decisions, not fetch outcomes:
        - miss: cache expired, fetch attempted (success/failure tracked by http_requests_total)
        - hit: cache valid, no fetch needed
        """
        analytics = get_analytics()
        if self._is_cache_expired():
            # Count miss before fetch - tracks cache decision, not fetch outcome
            analytics.cache_operations_total.labels(result="miss").inc()
            self.get_devices()
        else:
            analytics.cache_operations_total.labels(result="hit").inc()
        devices = self._devices_cache or []
        return next((d for d in devices if d.sn == device_sn), None)

    def _is_cache_expired(self) -> bool:
        """Check if device list cache has expired."""
        if self._devices_cache is None or self._devices_cache_time is None:
            return True
        return (time.time() - self._devices_cache_time) > DEVICE_LIST_CACHE_TTL

    def get_device_quota(self, device_sn: str) -> dict[str, Any]:
        """Get device statistics/metrics."""
        return self._execute_request("GET", GET_ALL_QUOTA_URL, {"sn": device_sn})

    def _execute_request(self, method: str, url: str, params: dict[str, Any]) -> Any:
        """Execute signed API request with automatic retry.

        Returns:
            The data field from the API response. Type varies by endpoint:
            - /device/list: list[dict] of device records
            - /device/quota/all: dict[str, Any] of device metrics
        """
        # Ensure session exists
        if not self._session:
            self._session = _create_session()

        # Extract endpoint for metrics (e.g., "/device/list" from full URL)
        endpoint = url.replace(HOST, "")
        analytics = get_analytics()

        sign_params = dict(params)
        sign_params.update(
            {
                "accessKey": self.auth.access_key,
                "nonce": f"{secrets.randbelow(900000) + 100000}",
                "timestamp": f"{int(time.time() * 1000)}",
            }
        )

        sign_message = urllib.parse.urlencode(sign_params)

        headers = {
            "sign": self.auth.build_signature(sign_message),
        }
        headers.update(sign_params)

        try:
            with analytics.time_http_request(endpoint):
                response = self._session.request(
                    method, url, headers=headers, params=params, timeout=HTTP_TIMEOUT
                )
        except requests.Timeout as e:
            analytics.http_requests_total.labels(endpoint=endpoint, status="timeout").inc()
            raise EcoflowApiException(f"Request to {url} timed out after {HTTP_TIMEOUT}s") from e
        except requests.RequestException as e:
            analytics.http_requests_total.labels(endpoint=endpoint, status="error").inc()
            raise EcoflowApiException(f"Request failed: {e}") from e

        # Check for HTTP errors
        if response.status_code >= 400:
            analytics.http_requests_total.labels(endpoint=endpoint, status="error").inc()
            raise EcoflowApiException(f"HTTP {response.status_code}: {response.text[:200]}")

        # Parse JSON response
        try:
            json_data = response.json()
        except json.JSONDecodeError as e:
            analytics.http_requests_total.labels(endpoint=endpoint, status="error").inc()
            raise EcoflowApiException(f"Invalid JSON response: {e}") from e

        log.debug("Payload: %s", json_data)

        try:
            return self._unwrap_response(json_data, endpoint)
        except EcoflowApiException:
            raise  # Already tracked in _unwrap_response
        except Exception as e:
            # Unexpected error in response processing
            analytics.http_requests_total.labels(endpoint=endpoint, status="error").inc()
            raise EcoflowApiException(f"Error processing response: {e}") from e

    def _unwrap_response(self, response: dict[str, Any], endpoint: str) -> Any:
        """Extract data from API response or raise exception.

        EcoFlow API returns code "0" for success.
        """
        analytics = get_analytics()
        code = str(response.get("code", ""))
        if code == "0":
            analytics.http_requests_total.labels(endpoint=endpoint, status="success").inc()
            return response.get("data", {})

        analytics.http_requests_total.labels(endpoint=endpoint, status="error").inc()
        message = response.get("message", "Unknown error")
        raise EcoflowApiException(f"API error (code={code}): {message}")

    def _parse_device(self, data: dict[str, Any]) -> DeviceInfo:
        """Parse device data from API response."""
        return DeviceInfo(
            sn=data.get("sn", ""),
            name=data.get("deviceName", ""),
            product_name=data.get("productName", ""),
            online=data.get("online", 0) == 1,
        )
