"""Device API client using private MQTT protocol.

This client uses the private EcoFlow MQTT API which allows actively requesting
device data via a get/reply topic pattern. It works with all EcoFlow devices,
including those not supported by the public REST or MQTT APIs.

Authentication: Email/password (same as MQTT API)
Data flow: Request/reply pattern - actively requests quota data
Topics:
  - /app/device/property/{device_sn} - receives push data
  - /app/{user_id}/{device_sn}/thing/property/get - sends quota requests
  - /app/{user_id}/{device_sn}/thing/property/get_reply - receives quota responses
"""

import json
import logging as log
import os
import secrets
import ssl
import time
from threading import Event, Lock
from typing import Any

import paho.mqtt.client as mqtt

from .base import EcoflowApiClient
from .models import DeviceInfo, EcoflowApiException
from .mqtt import MqttAuthentication, RepeatTimer

# Configuration via environment variables
MQTT_TIMEOUT = int(os.getenv("MQTT_TIMEOUT", "60"))
QUOTA_REQUEST_INTERVAL = int(os.getenv("QUOTA_REQUEST_INTERVAL", "30"))
IDLE_CHECK_INTERVAL = int(os.getenv("IDLE_CHECK_INTERVAL", "30"))
MQTT_KEEPALIVE = int(os.getenv("MQTT_KEEPALIVE", "60"))
MAX_RECONNECT_DELAY = int(os.getenv("MAX_RECONNECT_DELAY", "300"))


def _gen_request_id() -> int:
    """Generate random request ID for MQTT messages."""
    return 999900000 + secrets.randbelow(90000) + 10000


class DeviceApiClient(EcoflowApiClient):
    """Device API client using private MQTT protocol.

    Unlike the public MQTT API which only receives push data, the Device API
    can actively request quota data from devices using a request/reply pattern.
    This provides more reliable data collection and works with all EcoFlow devices.
    Supports both JSON and protobuf message formats.

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
        self._client: mqtt.Client | None = None
        self._connected = Event()
        self._idle_timer: RepeatTimer | None = None
        self._quota_timer: RepeatTimer | None = None
        self._last_message_time: float | None = None
        self._last_push_data_time: float | None = None  # Track push data separately
        self._reconnect_delay: int = IDLE_CHECK_INTERVAL  # Exponential backoff
        self._subscribed = Event()  # Track subscription confirmation

        # Initialize generic protobuf decoder for all devices
        from ..proto.decoder import get_decoder
        self._proto_decoder = get_decoder()
        log.info("Protobuf decoder enabled")

        # Topics
        self._data_topic: str = ""
        self._get_topic: str = ""
        self._get_reply_topic: str = ""

    def connect(self) -> None:
        """Authenticate and connect to MQTT broker."""
        self.auth.authorize()

        # Set up topics using user_id
        user_id = self.auth.user_id
        self._data_topic = f"/app/device/property/{self.device_sn}"
        self._get_topic = f"/app/{user_id}/{self.device_sn}/thing/property/get"
        self._get_reply_topic = f"/app/{user_id}/{self.device_sn}/thing/property/get_reply"

        self._connect_mqtt()

        # Wait for initial connection using Event (efficient, no busy-wait)
        if not self._connected.wait(timeout=10):
            raise EcoflowApiException("Failed to connect to MQTT broker")

        # Wait for subscription confirmation (replaces sleep(1))
        if not self._subscribed.wait(timeout=5):
            log.warning("Subscription confirmation not received, proceeding anyway")

        # Start idle reconnection timer (check every 30s, not 10s)
        self._idle_timer = RepeatTimer(IDLE_CHECK_INTERVAL, self._check_idle)
        self._idle_timer.daemon = True
        self._idle_timer.start()

        # Start quota request timer
        self._quota_timer = RepeatTimer(QUOTA_REQUEST_INTERVAL, self._request_quota)
        self._quota_timer.daemon = True
        self._quota_timer.start()

        # Request initial quota (subscription confirmed, no sleep needed)
        self._request_quota()

        # Reset reconnect delay on successful connection
        self._reconnect_delay = IDLE_CHECK_INTERVAL

        log.info("Connected to EcoFlow Device API (private MQTT)")

    def disconnect(self) -> None:
        """Disconnect from MQTT broker and stop timers."""
        if self._quota_timer:
            self._quota_timer.cancel()
            self._quota_timer = None
        if self._idle_timer:
            self._idle_timer.cancel()
            self._idle_timer = None
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()
            self._client = None
        self._connected.clear()
        self._subscribed.clear()

    def get_devices(self) -> list[DeviceInfo]:
        """Get list of devices (returns configured device only)."""
        return [self._get_device_info()]

    def get_device(self, device_sn: str) -> DeviceInfo | None:
        """Get device info by serial number."""
        if device_sn == self.device_sn:
            return self._get_device_info()
        return None

    def get_device_quota(self, device_sn: str) -> dict[str, Any]:
        """Get cached device metrics."""
        if device_sn != self.device_sn:
            return {}

        with self._cache_lock:
            return dict(self._quota_cache)

    def _get_device_info(self) -> DeviceInfo:
        """Build DeviceInfo from available data."""
        online = self._connected.is_set()
        if self._last_update:
            age = time.time() - self._last_update
            online = online and age < MQTT_TIMEOUT

        return DeviceInfo(
            sn=self.device_sn,
            name=os.getenv("ECOFLOW_DEVICE_NAME", self.device_sn),
            product_name="Unknown",
            online=online,
        )

    def _connect_mqtt(self) -> None:
        """Establish MQTT connection."""
        # Clear state before connecting
        self._connected.clear()
        self._subscribed.clear()

        if self._client:
            self._client.loop_stop()
            self._client.disconnect()

        client_id = self.auth.mqtt_client_id
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id)
        self._client.username_pw_set(self.auth.mqtt_username, self.auth.mqtt_password)
        self._client.tls_set(certfile=None, keyfile=None, cert_reqs=ssl.CERT_REQUIRED)
        self._client.tls_insecure_set(False)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        self._client.on_subscribe = self._on_subscribe

        # Enable automatic reconnection with backoff
        self._client.reconnect_delay_set(min_delay=1, max_delay=MAX_RECONNECT_DELAY)

        log.info(
            "Connecting to MQTT broker %s:%d (Device API)",
            self.auth.mqtt_url,
            self.auth.mqtt_port,
        )
        self._client.connect(self.auth.mqtt_url, self.auth.mqtt_port, keepalive=MQTT_KEEPALIVE)
        self._client.loop_start()

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        """Handle MQTT connection callback."""
        self._last_message_time = time.time()

        if str(reason_code) == "Success":
            self._connected.set()
            # Subscribe to both data topic and get_reply topic
            topics = [
                (self._data_topic, 1),
                (self._get_reply_topic, 1),
            ]
            self._client.subscribe(topics)
            log.info("Subscribed to Device API topics: %s", [t[0] for t in topics])
        else:
            self._connected.clear()
            log.error("MQTT connection failed: %s", reason_code)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties) -> None:
        """Handle MQTT disconnection callback."""
        self._connected.clear()
        self._subscribed.clear()
        if reason_code != 0:
            log.error("Unexpected MQTT disconnection: %s", reason_code)

    def _on_subscribe(self, client, userdata, mid, reason_codes, properties) -> None:
        """Handle MQTT subscription callback."""
        self._subscribed.set()
        log.debug("Subscription confirmed (mid=%s)", mid)

    def _on_message(self, client, userdata, message) -> None:
        """Handle incoming MQTT message."""
        self._last_message_time = time.time()

        try:
            payload = message.payload.decode("utf-8")
            topic = message.topic

            if topic == self._get_reply_topic:
                self._handle_quota_reply(payload)
            elif topic == self._data_topic:
                self._handle_data_message(payload)
            else:
                log.debug("Message on unknown topic: %s", topic)

        except UnicodeDecodeError:
            # Binary payload (protobuf)
            self._handle_binary_message(message.payload)
        except Exception as e:
            log.error("Error processing MQTT message: %s", e)

    def _handle_binary_message(self, payload: bytes) -> None:
        """Process incoming binary (protobuf) MQTT message."""
        try:
            params = self._proto_decoder.decode(payload)

            if params:
                with self._cache_lock:
                    self._quota_cache.update(params)
                    self._last_update = time.time()

                log.debug("Updated cache with %d protobuf parameters", len(params))
        except Exception as e:
            log.error("Error processing protobuf message: %s", e)

    def _handle_quota_reply(self, payload: str) -> None:
        """Process quota reply message (latestQuotas response)."""
        try:
            data = json.loads(payload)

            if data.get("operateType") == "latestQuotas":
                message_data = data.get("data", {})
                online = int(message_data.get("online", 0))

                if online == 1:
                    quota_map = message_data.get("quotaMap", {})
                    with self._cache_lock:
                        self._quota_cache.update(quota_map)
                        self._last_update = time.time()
                    log.debug("Received quota data with %d parameters", len(quota_map))
                else:
                    log.info("Device is offline (from quota reply)")
            else:
                log.debug("Quota reply with operateType: %s", data.get("operateType"))

        except json.JSONDecodeError as e:
            log.error("Failed to parse quota reply: %s", e)

    def _handle_data_message(self, payload: str) -> None:
        """Process push data message (same as public MQTT)."""
        try:
            data = json.loads(payload)
            params = data.get("params", {})

            with self._cache_lock:
                self._quota_cache.update(params)
                self._last_update = time.time()
                self._last_push_data_time = time.time()  # Track push data separately

            log.debug("Received push data with %d parameters", len(params))

        except json.JSONDecodeError as e:
            log.error("Failed to parse data message: %s", e)

    def _request_quota(self) -> None:
        """Send quota request to device.

        Only sends request if no push data received recently, to avoid
        redundant server requests when device is actively pushing data.
        """
        if not self._connected.is_set() or not self._client:
            log.debug("Not connected, skipping quota request")
            return

        # Skip if we received push data recently (within quota interval)
        if self._last_push_data_time:
            time_since_push = time.time() - self._last_push_data_time
            if time_since_push < QUOTA_REQUEST_INTERVAL:
                log.debug(
                    "Skipping quota request, received push data %.1fs ago",
                    time_since_push
                )
                return

        message = {
            "from": "PrometheusExporter",
            "id": str(_gen_request_id()),
            "version": "1.0",
            "moduleType": 0,
            "operateType": "latestQuotas",
            "params": {},
        }

        try:
            payload = json.dumps(message)
            self._client.publish(self._get_topic, payload, qos=1)
            log.debug("Sent quota request to %s", self._get_topic)
        except Exception as e:
            log.error("Failed to send quota request: %s", e)

    def _check_idle(self) -> None:
        """Check for idle connection and reconnect if needed."""
        if (
            self._last_message_time
            and time.time() - self._last_message_time > MQTT_TIMEOUT
        ):
            log.warning("No MQTT messages for %d seconds, reconnecting...", MQTT_TIMEOUT)
            self._connect_mqtt()

            # Wait briefly for connection
            if self._connected.wait(timeout=10):
                log.info("Reconnection successful")
                self._last_message_time = time.time()
                self._reconnect_delay = IDLE_CHECK_INTERVAL  # Reset backoff
            else:
                # Exponential backoff on failure
                log.error(
                    "Reconnection failed, next attempt in %d seconds",
                    self._reconnect_delay
                )
                self._last_message_time = time.time()  # Prevent immediate retry
                self._reconnect_delay = min(
                    self._reconnect_delay * 2,
                    MAX_RECONNECT_DELAY
                )
