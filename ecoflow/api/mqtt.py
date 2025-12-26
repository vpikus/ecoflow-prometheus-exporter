import base64
import json
import logging as log
import os
import ssl
import time
import uuid
from multiprocessing import Process
from queue import Empty, Queue
from threading import Lock, Timer
from typing import Any, Callable

import paho.mqtt.client as mqtt
import requests

from .base import EcoflowApiClient
from .models import DeviceInfo, EcoflowApiException

ECOFLOW_API_HOST = os.getenv("ECOFLOW_API_HOST", "api.ecoflow.com")
MQTT_TIMEOUT = int(os.getenv("MQTT_TIMEOUT", "60"))


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

    def authorize(self) -> None:
        """Login to EcoFlow API and retrieve MQTT credentials."""
        token, user_id, user_name = self._login()
        self.user_id = user_id
        self.user_name = user_name
        self._get_mqtt_credentials(token, user_id)

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
        response = requests.post(url, json=data, headers=headers)
        json_response = self._parse_response(response)

        try:
            token = json_response["data"]["token"]
            user_id = json_response["data"]["user"]["userId"]
            user_name = json_response["data"]["user"]["name"]
        except KeyError as key:
            raise EcoflowApiException(f"Missing key {key} in login response")

        log.info("Successfully logged in as: %s", user_name)
        return token, user_id, user_name

    def _get_mqtt_credentials(self, token: str, user_id: str) -> None:
        """Retrieve MQTT credentials using auth token."""
        url = f"https://{self.api_host}/iot-auth/app/certification"
        headers = {"lang": "en_US", "authorization": f"Bearer {token}"}
        params = {"userId": user_id}

        log.info("Requesting MQTT credentials from %s", url)
        response = requests.get(url, params=params, headers=headers)
        json_response = self._parse_response(response)

        try:
            self.mqtt_url = json_response["data"]["url"]
            self.mqtt_port = int(json_response["data"]["port"])
            self.mqtt_username = json_response["data"]["certificateAccount"]
            self.mqtt_password = json_response["data"]["certificatePassword"]
            self.mqtt_client_id = f"ANDROID_{str(uuid.uuid4()).upper()}_{user_id}"
        except KeyError as key:
            raise EcoflowApiException(f"Missing key {key} in MQTT credentials response")

        log.info("MQTT credentials obtained for account: %s", self.mqtt_username)

    def _parse_response(self, response: requests.Response) -> dict[str, Any]:
        """Parse and validate API response."""
        if response.status_code != 200:
            raise EcoflowApiException(
                f"HTTP {response.status_code}: {response.text}"
            )

        try:
            json_data = response.json()
        except json.JSONDecodeError as e:
            raise EcoflowApiException(f"Invalid JSON response: {e}")

        message = json_data.get("message", "")
        if message.lower() != "success":
            raise EcoflowApiException(f"API error: {message}")

        return json_data


class MqttConnection:
    """Manages MQTT connection and message handling."""

    def __init__(
        self,
        device_sn: str,
        auth: MqttAuthentication,
        message_callback: Callable[[str], None],
        timeout_seconds: int = MQTT_TIMEOUT,
        binary_callback: Callable[[bytes], None] | None = None,
    ):
        self.device_sn = device_sn
        self.auth = auth
        self.message_callback = message_callback
        self.binary_callback = binary_callback
        self.timeout_seconds = timeout_seconds

        self.topic = f"/app/device/property/{device_sn}"
        self.last_message_time: float | None = None
        self.client: mqtt.Client | None = None
        self._connected = False

    def connect(self) -> None:
        """Establish MQTT connection."""
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()

        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2, self.auth.mqtt_client_id
        )
        self.client.username_pw_set(self.auth.mqtt_username, self.auth.mqtt_password)
        self.client.tls_set(certfile=None, keyfile=None, cert_reqs=ssl.CERT_REQUIRED)
        self.client.tls_insecure_set(False)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

        log.info(
            "Connecting to MQTT broker %s:%d",
            self.auth.mqtt_url,
            self.auth.mqtt_port,
        )
        self.client.connect(self.auth.mqtt_url, self.auth.mqtt_port)
        self.client.loop_start()

    def disconnect(self) -> None:
        """Disconnect from MQTT broker."""
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()
            self._connected = False

    def is_connected(self) -> bool:
        """Check if MQTT is connected."""
        return self._connected

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        """Handle MQTT connection callback."""
        self.last_message_time = time.time()

        if str(reason_code) == "Success":
            self.client.subscribe(self.topic)
            self._connected = True
            log.info("Subscribed to MQTT topic %s", self.topic)
        else:
            self._connected = False
            log.error("MQTT connection failed: %s", reason_code)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties) -> None:
        """Handle MQTT disconnection callback."""
        self._connected = False
        if reason_code != 0:
            log.error("Unexpected MQTT disconnection: %s", reason_code)

    def _on_message(self, client, userdata, message) -> None:
        """Handle incoming MQTT message."""
        self.last_message_time = time.time()
        try:
            payload = message.payload.decode("utf-8")
            self.message_callback(payload)
        except UnicodeDecodeError:
            # Binary payload (protobuf)
            if self.binary_callback:
                self.binary_callback(message.payload)
            else:
                log.warning("Received binary MQTT message but no binary handler configured")


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

        # Start idle reconnection timer
        self._idle_timer = RepeatTimer(10, self._check_idle)
        self._idle_timer.daemon = True
        self._idle_timer.start()

        # Wait for initial connection
        timeout = 10
        start = time.time()
        while not self._mqtt.is_connected() and time.time() - start < timeout:
            time.sleep(0.1)

        if not self._mqtt.is_connected():
            raise EcoflowApiException("Failed to connect to MQTT broker")

        log.info("Connected to EcoFlow MQTT broker")

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
            product_name="Unknown",  # MQTT doesn't provide this
            online=online,
        )

    def _handle_message(self, payload: str) -> None:
        """Process incoming MQTT message and update cache."""
        try:
            data = json.loads(payload)
            params = data.get("params", {})

            with self._cache_lock:
                self._quota_cache.update(params)
                self._last_update = time.time()

            log.debug("Updated cache with %d parameters", len(params))
        except json.JSONDecodeError as e:
            log.error("Failed to parse MQTT payload: %s", e)
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

    def _check_idle(self) -> None:
        """Check for idle connection and reconnect if needed."""
        if not self._mqtt:
            return

        if (
            self._mqtt.last_message_time
            and time.time() - self._mqtt.last_message_time > MQTT_TIMEOUT
        ):
            log.warning(
                "No MQTT messages for %d seconds, reconnecting...", MQTT_TIMEOUT
            )
            self._reconnect()

    def _reconnect(self) -> None:
        """Reconnect to MQTT broker with timeout protection."""
        # Use subprocess to prevent hanging
        connect_process = Process(target=self._mqtt.connect)
        connect_process.start()
        connect_process.join(timeout=60)
        connect_process.terminate()

        if connect_process.exitcode == 0:
            log.info("MQTT reconnection successful")
            if self._mqtt:
                self._mqtt.last_message_time = time.time()
        else:
            log.error("MQTT reconnection failed or timed out")
