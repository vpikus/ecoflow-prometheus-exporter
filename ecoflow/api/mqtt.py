import base64
import json
import logging as log
import os
import ssl
import time
import uuid
from collections.abc import Callable
from threading import Event, Lock, Thread, Timer
from typing import Any

import paho.mqtt.client as mqtt
import requests

from ..metrics import get_analytics
from .base import EcoflowApiClient
from .models import DeviceInfo, EcoflowApiException

# Configuration via environment variables
ECOFLOW_API_HOST = os.getenv("ECOFLOW_API_HOST", "api.ecoflow.com")
MQTT_TIMEOUT = int(os.getenv("MQTT_TIMEOUT", "60"))
HTTP_TIMEOUT = int(os.getenv("HTTP_TIMEOUT", "30"))
IDLE_CHECK_INTERVAL = int(os.getenv("IDLE_CHECK_INTERVAL", "30"))
MQTT_KEEPALIVE = int(os.getenv("MQTT_KEEPALIVE", "60"))
MAX_RECONNECT_DELAY = int(os.getenv("MAX_RECONNECT_DELAY", "300"))


class RepeatTimer(Timer):
    """Timer that repeats execution at fixed intervals."""

    def run(self) -> None:
        while not self.finished.wait(self.interval):
            self.function(*self.args, **self.kwargs)


class MqttAuthentication:
    """Handles EcoFlow account login and MQTT credential retrieval."""

    def __init__(self, username: str, password: str, api_host: str = ECOFLOW_API_HOST):
        self.username = username
        self.password = password
        self.api_host = api_host

        self.mqtt_url: str = "mqtt.ecoflow.com"
        self.mqtt_port: int = 8883
        self.mqtt_username: str | None = None
        self.mqtt_password: str | None = None
        self.mqtt_client_id: str | None = None
        self.user_id: str | None = None
        self.user_name: str | None = None

    def authorize(self, client_type: str = "mqtt") -> None:
        """Login to EcoFlow API and retrieve MQTT credentials.

        Args:
            client_type: Type of client for metrics (mqtt or device).
        """
        analytics = get_analytics()
        try:
            with analytics.time_auth(client_type):
                token, user_id, user_name = self._login()
                self._get_mqtt_credentials(token, user_id)
                # Only set user info after all auth steps succeed
                self.user_id = user_id
                self.user_name = user_name
            analytics.auth_requests_total.labels(client_type=client_type, status="success").inc()
        except Exception:
            analytics.auth_requests_total.labels(client_type=client_type, status="error").inc()
            raise

    def _login(self) -> tuple[str, str, str]:
        """Login to EcoFlow API and return token and user info."""
        url = f"https://{self.api_host}/auth/login"
        headers = {"lang": "en_US", "content-type": "application/json"}
        data = {
            "email": self.username,
            "password": base64.b64encode(self.password.encode()).decode(),
            "scene": "IOT_APP",
            "userType": "ECOFLOW",
        }

        log.info("Logging in to EcoFlow API at %s", url)
        try:
            response = requests.post(url, json=data, headers=headers, timeout=HTTP_TIMEOUT)
        except requests.Timeout as e:
            raise EcoflowApiException(f"Login request to {url} timed out") from e
        except requests.RequestException as e:
            raise EcoflowApiException(f"Login request failed: {e}") from e
        json_response = self._parse_response(response)

        try:
            token = json_response["data"]["token"]
            user_id = json_response["data"]["user"]["userId"]
            user_name = json_response["data"]["user"]["name"]
        except KeyError as key:
            raise EcoflowApiException(f"Missing key {key} in login response") from key

        log.info("Successfully logged in as: %s", user_name)
        return token, user_id, user_name

    def _get_mqtt_credentials(self, token: str, user_id: str) -> None:
        """Retrieve MQTT credentials using auth token."""
        url = f"https://{self.api_host}/iot-auth/app/certification"
        headers = {"lang": "en_US", "authorization": f"Bearer {token}"}
        params = {"userId": user_id}

        log.info("Requesting MQTT credentials from %s", url)
        try:
            response = requests.get(url, params=params, headers=headers, timeout=HTTP_TIMEOUT)
        except requests.Timeout as e:
            raise EcoflowApiException(f"MQTT credentials request to {url} timed out") from e
        except requests.RequestException as e:
            raise EcoflowApiException(f"MQTT credentials request failed: {e}") from e
        json_response = self._parse_response(response)

        try:
            self.mqtt_url = json_response["data"]["url"]
            self.mqtt_port = int(json_response["data"]["port"])
            self.mqtt_username = json_response["data"]["certificateAccount"]
            self.mqtt_password = json_response["data"]["certificatePassword"]
            self.mqtt_client_id = f"ANDROID_{str(uuid.uuid4()).upper()}_{user_id}"
        except KeyError as key:
            raise EcoflowApiException(f"Missing key {key} in MQTT credentials response") from key

        log.info("MQTT credentials obtained for account: %s", self.mqtt_username)

    def _parse_response(self, response: requests.Response) -> dict[str, Any]:
        """Parse and validate API response.

        Handles both User API (message="Success") and Developer API (code="0").
        """
        if response.status_code != 200:
            raise EcoflowApiException(f"HTTP {response.status_code}: {response.text}")

        try:
            json_data = response.json()
        except json.JSONDecodeError as e:
            raise EcoflowApiException(f"Invalid JSON response: {e}") from e

        # Check for success: code="0" (Developer API) or message="Success" (User API)
        code = str(json_data.get("code", ""))
        message = json_data.get("message", "")

        if code == "0" or message.lower() == "success":
            return json_data

        raise EcoflowApiException(f"API error (code={code}): {message}")


class MqttConnection:
    """Manages MQTT connection and message handling."""

    def __init__(
        self,
        device_sn: str,
        auth: MqttAuthentication,
        message_callback: Callable[[str], None],
        timeout_seconds: int = MQTT_TIMEOUT,
        binary_callback: Callable[[bytes], None] | None = None,
        client_type: str = "mqtt",
    ):
        self.device_sn = device_sn
        self.auth = auth
        self.message_callback = message_callback
        self.binary_callback = binary_callback
        self.timeout_seconds = timeout_seconds
        self.client_type = client_type

        self.topic = f"/app/device/property/{device_sn}"
        self.last_message_time: float | None = None
        self.client: mqtt.Client | None = None
        self._connected = Event()
        self._subscribed = Event()

    def connect(self) -> None:
        """Establish MQTT connection."""
        # Clear state before connecting
        self._connected.clear()
        self._subscribed.clear()

        if self.client:
            self.client.loop_stop()
            self.client.disconnect()

        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, self.auth.mqtt_client_id)
        self.client.username_pw_set(self.auth.mqtt_username, self.auth.mqtt_password)
        self.client.tls_set(certfile=None, keyfile=None, cert_reqs=ssl.CERT_REQUIRED)
        self.client.tls_insecure_set(False)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.client.on_subscribe = self._on_subscribe

        # Enable automatic reconnection with backoff
        self.client.reconnect_delay_set(min_delay=1, max_delay=MAX_RECONNECT_DELAY)

        log.info(
            "Connecting to MQTT broker %s:%d",
            self.auth.mqtt_url,
            self.auth.mqtt_port,
        )
        self.client.connect(self.auth.mqtt_url, self.auth.mqtt_port, keepalive=MQTT_KEEPALIVE)
        self.client.loop_start()

    def disconnect(self) -> None:
        """Disconnect from MQTT broker."""
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()
            self._connected.clear()
            self._subscribed.clear()

    def is_connected(self) -> bool:
        """Check if MQTT is connected."""
        return self._connected.is_set()

    def wait_connected(self, timeout: float) -> bool:
        """Wait for connection with timeout. Returns True if connected."""
        return self._connected.wait(timeout)

    def wait_subscribed(self, timeout: float) -> bool:
        """Wait for subscription confirmation. Returns True if subscribed."""
        return self._subscribed.wait(timeout)

    def _on_connect(self, client: mqtt.Client, userdata, flags, reason_code, properties) -> None:
        """Handle MQTT connection callback."""
        self.last_message_time = time.time()
        analytics = get_analytics()

        if str(reason_code) == "Success":
            client.subscribe(self.topic)
            self._connected.set()
            analytics.mqtt_connected.labels(client_type=self.client_type).set(1)
            log.info("Subscribed to MQTT topic %s", self.topic)
        else:
            self._connected.clear()
            analytics.mqtt_connected.labels(client_type=self.client_type).set(0)
            log.error("MQTT connection failed: %s", reason_code)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties) -> None:
        """Handle MQTT disconnection callback."""
        self._connected.clear()
        self._subscribed.clear()
        analytics = get_analytics()
        analytics.mqtt_connected.labels(client_type=self.client_type).set(0)
        if reason_code != 0:
            log.error("Unexpected MQTT disconnection: %s", reason_code)

    def _on_subscribe(self, client, userdata, mid, reason_codes, properties) -> None:
        """Handle MQTT subscription callback."""
        self._subscribed.set()
        log.debug("Subscription confirmed (mid=%s)", mid)

    def _on_message(self, client, userdata, message) -> None:
        """Handle incoming MQTT message."""
        self.last_message_time = time.time()
        analytics = get_analytics()
        try:
            try:
                payload = message.payload.decode("utf-8")
                # Count as "text" (encoding type), not "json" - parse errors tracked separately
                analytics.mqtt_messages_total.labels(client_type=self.client_type, type="text").inc()
                self.message_callback(payload)
            except UnicodeDecodeError:
                # Binary payload (protobuf)
                analytics.mqtt_messages_total.labels(client_type=self.client_type, type="protobuf").inc()
                if self.binary_callback:
                    self.binary_callback(message.payload)
                else:
                    analytics.mqtt_message_errors_total.labels(client_type=self.client_type).inc()
                    log.warning("Received binary MQTT message but no binary handler configured")
        except Exception:
            # Catch-all to prevent MQTT loop from dying on callback errors
            analytics.mqtt_message_errors_total.labels(client_type=self.client_type).inc()
            log.exception("Error in MQTT message callback")


class MqttApiClient(EcoflowApiClient):
    """MQTT API client using user credentials (email/password).

    This client connects to EcoFlow's MQTT broker to receive real-time
    device data. Unlike REST API, MQTT is push-based so metrics are
    cached as they arrive. Supports both JSON and protobuf message formats.

    Args:
        username: EcoFlow account email.
        password: EcoFlow account password.
        device_sn: Device serial number.
    """

    def __init__(
        self,
        username: str,
        password: str,
        device_sn: str,
    ):
        self.device_sn = device_sn
        self.auth = MqttAuthentication(username, password)

        self._quota_cache: dict[str, Any] = {}
        self._cache_lock = Lock()
        self._last_update: float | None = None
        self._mqtt: MqttConnection | None = None
        self._idle_timer: RepeatTimer | None = None
        self._reconnect_delay: int = IDLE_CHECK_INTERVAL  # Exponential backoff

        # Initialize generic protobuf decoder for all devices
        from ..proto.decoder import get_decoder

        self._proto_decoder = get_decoder()
        log.info("Protobuf decoder enabled")

    def connect(self) -> None:
        """Authenticate and connect to MQTT broker."""
        self.auth.authorize()

        self._mqtt = MqttConnection(
            self.device_sn,
            self.auth,
            self._handle_message,
            binary_callback=self._handle_binary_message,
        )
        self._mqtt.connect()

        # Wait for initial connection using Event (efficient, no busy-wait)
        if not self._mqtt.wait_connected(timeout=10):
            raise EcoflowApiException("Failed to connect to MQTT broker")

        # Wait for subscription confirmation
        if not self._mqtt.wait_subscribed(timeout=5):
            log.warning("Subscription confirmation not received, proceeding anyway")

        # Start idle reconnection timer (check every 30s, not 10s)
        self._idle_timer = RepeatTimer(IDLE_CHECK_INTERVAL, self._check_idle)
        self._idle_timer.daemon = True
        self._idle_timer.start()

        # Reset reconnect delay on successful connection
        self._reconnect_delay = IDLE_CHECK_INTERVAL

        log.info("Connected to EcoFlow MQTT broker")

    def disconnect(self) -> None:
        """Disconnect from MQTT broker and stop timers."""
        if self._idle_timer:
            self._idle_timer.cancel()
            self._idle_timer = None
        if self._mqtt:
            self._mqtt.disconnect()
            self._mqtt = None
        # Update connection gauge immediately (don't wait for callback)
        analytics = get_analytics()
        analytics.mqtt_connected.labels(client_type="mqtt").set(0)

    def get_devices(self) -> list[DeviceInfo]:
        """Get list of devices (returns configured device only).

        Note: MQTT API doesn't provide device discovery.
        Returns the configured device based on available info.
        """
        return [self._get_device_info()]

    def get_device(self, device_sn: str) -> DeviceInfo | None:
        """Get device info by serial number."""
        if device_sn == self.device_sn:
            return self._get_device_info()
        return None

    def get_device_quota(self, device_sn: str) -> dict[str, Any]:
        """Get cached device metrics from MQTT messages."""
        if device_sn != self.device_sn:
            return {}

        with self._cache_lock:
            return dict(self._quota_cache)

    def _get_device_info(self) -> DeviceInfo:
        """Build DeviceInfo from available data."""
        online = self._mqtt.is_connected() if self._mqtt else False
        # Check if we've received data recently
        if self._last_update:
            age = time.time() - self._last_update
            online = online and age < MQTT_TIMEOUT

        return DeviceInfo(
            sn=self.device_sn,
            name=os.getenv("ECOFLOW_DEVICE_NAME", self.device_sn),
            product_name=None,
            online=online,
        )

    def _handle_message(self, payload: str) -> None:
        """Process incoming MQTT message and update cache."""
        analytics = get_analytics()
        try:
            data = json.loads(payload)
            params = data.get("params", {})

            with self._cache_lock:
                self._quota_cache.update(params)
                self._last_update = time.time()

            log.debug("Updated cache with %d parameters", len(params))
        except json.JSONDecodeError:
            analytics.mqtt_message_errors_total.labels(client_type="mqtt").inc()
            log.exception("Failed to parse MQTT payload")
        except Exception:
            analytics.mqtt_message_errors_total.labels(client_type="mqtt").inc()
            log.exception("Error processing MQTT message")

    def _handle_binary_message(self, payload: bytes) -> None:
        """Process incoming binary (protobuf) MQTT message."""
        analytics = get_analytics()
        try:
            params = self._proto_decoder.decode(payload)

            if params:
                with self._cache_lock:
                    self._quota_cache.update(params)
                    self._last_update = time.time()

                log.debug("Updated cache with %d protobuf parameters", len(params))
        except Exception:
            analytics.mqtt_message_errors_total.labels(client_type="mqtt").inc()
            log.exception("Error processing protobuf message")

    def _check_idle(self) -> None:
        """Check for idle connection and reconnect if needed."""
        if not self._mqtt:
            return

        if (
            self._mqtt.last_message_time
            and time.time() - self._mqtt.last_message_time > MQTT_TIMEOUT
        ):
            log.warning("No MQTT messages for %d seconds, reconnecting...", MQTT_TIMEOUT)
            self._reconnect()

    def _reconnect(self) -> None:
        """Reconnect to MQTT broker with timeout protection and exponential backoff."""
        mqtt_conn = self._mqtt
        if not mqtt_conn:
            return

        analytics = get_analytics()
        analytics.mqtt_reconnections_total.labels(client_type="mqtt").inc()

        # Use thread with timeout for reconnection
        def do_reconnect():
            try:
                mqtt_conn.connect()
            except Exception as e:
                log.error("MQTT reconnection error: %s", e)

        reconnect_thread = Thread(target=do_reconnect, daemon=True)
        reconnect_thread.start()
        reconnect_thread.join(timeout=30)

        if reconnect_thread.is_alive():
            log.error("MQTT reconnection timed out")
            self._apply_backoff()
        elif mqtt_conn.is_connected():
            log.info("MQTT reconnection successful")
            mqtt_conn.last_message_time = time.time()
            self._reconnect_delay = IDLE_CHECK_INTERVAL  # Reset backoff
        else:
            log.error("MQTT reconnection failed")
            self._apply_backoff()

    def _apply_backoff(self) -> None:
        """Apply exponential backoff for reconnection failures."""
        if self._mqtt:
            self._mqtt.last_message_time = time.time()  # Prevent immediate retry
        self._reconnect_delay = min(self._reconnect_delay * 2, MAX_RECONNECT_DELAY)
        log.info("Next reconnect attempt in %d seconds", self._reconnect_delay)
