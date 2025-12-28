"""Tests for ecoflow/api/mqtt.py - MQTT API client."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from ecoflow.api.models import EcoflowApiException
from ecoflow.api.mqtt import MqttApiClient, MqttAuthentication, MqttConnection


class TestMqttAuthentication:
    """Tests for MqttAuthentication class."""

    @pytest.fixture
    def auth(self):
        """Create MqttAuthentication instance."""
        return MqttAuthentication("test@example.com", "password123")

    def test_init(self, auth):
        """Test initialization."""
        assert auth.username == "test@example.com"
        assert auth.password == "password123"
        assert auth.mqtt_url == "mqtt.ecoflow.com"
        assert auth.mqtt_port == 8883

    @patch("requests.post")
    def test_login_success(self, mock_post, auth):
        """Test successful login."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "code": "0",
            "message": "Success",
            "data": {"token": "test_token", "user": {"userId": "user123", "name": "Test User"}},
        }
        mock_post.return_value = mock_response

        token, user_id, user_name = auth._login()

        assert token == "test_token"
        assert user_id == "user123"
        assert user_name == "Test User"

    @patch("requests.post")
    def test_login_timeout(self, mock_post, auth):
        """Test login timeout."""
        mock_post.side_effect = requests.Timeout()

        with pytest.raises(EcoflowApiException) as exc_info:
            auth._login()

        assert "timed out" in str(exc_info.value)

    @patch("requests.post")
    def test_login_http_error(self, mock_post, auth):
        """Test login with HTTP error."""
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"
        mock_post.return_value = mock_response

        with pytest.raises(EcoflowApiException) as exc_info:
            auth._login()

        assert "HTTP 401" in str(exc_info.value)

    @patch("requests.post")
    def test_login_missing_token(self, mock_post, auth):
        """Test login with missing token in response."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "code": "0",
            "message": "Success",
            "data": {},  # Missing token
        }
        mock_post.return_value = mock_response

        with pytest.raises(EcoflowApiException) as exc_info:
            auth._login()

        assert "Missing key" in str(exc_info.value)

    @patch("requests.get")
    @patch("requests.post")
    def test_authorize_success(self, mock_post, mock_get, auth):
        """Test full authorization flow."""
        # Login response
        login_response = MagicMock()
        login_response.status_code = 200
        login_response.json.return_value = {
            "code": "0",
            "data": {"token": "test_token", "user": {"userId": "user123", "name": "Test User"}},
        }
        mock_post.return_value = login_response

        # MQTT credentials response
        mqtt_response = MagicMock()
        mqtt_response.status_code = 200
        mqtt_response.json.return_value = {
            "code": "0",
            "data": {
                "url": "mqtt.test.com",
                "port": "8883",
                "certificateAccount": "mqtt_user",
                "certificatePassword": "mqtt_pass",
            },
        }
        mock_get.return_value = mqtt_response

        auth.authorize()

        assert auth.user_id == "user123"
        assert auth.mqtt_url == "mqtt.test.com"
        assert auth.mqtt_username == "mqtt_user"
        assert auth.mqtt_password == "mqtt_pass"

    def test_parse_response_success_code_0(self, auth):
        """Test parsing response with code 0."""
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"code": "0", "data": {"key": "value"}}

        result = auth._parse_response(response)

        assert result["data"]["key"] == "value"

    def test_parse_response_success_message(self, auth):
        """Test parsing response with Success message."""
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"message": "Success", "data": {"key": "value"}}

        result = auth._parse_response(response)

        assert result["data"]["key"] == "value"

    def test_parse_response_error(self, auth):
        """Test parsing error response."""
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"code": "1001", "message": "Invalid credentials"}

        with pytest.raises(EcoflowApiException) as exc_info:
            auth._parse_response(response)

        assert "code=1001" in str(exc_info.value)


class TestMqttConnection:
    """Tests for MqttConnection class."""

    @pytest.fixture
    def auth(self):
        """Create mock authentication."""
        auth = MagicMock()
        auth.mqtt_url = "mqtt.test.com"
        auth.mqtt_port = 8883
        auth.mqtt_username = "test_user"
        auth.mqtt_password = "test_pass"
        auth.mqtt_client_id = "test_client_id"
        return auth

    @pytest.fixture
    def message_callback(self):
        """Create message callback."""
        return MagicMock()

    @patch("paho.mqtt.client.Client")
    def test_connect(self, mock_client_class, auth, message_callback):
        """Test MQTT connection."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        conn = MqttConnection("DEV123", auth, message_callback)
        conn.connect()

        mock_client.username_pw_set.assert_called_once()
        mock_client.tls_set.assert_called_once()
        mock_client.connect.assert_called_once_with("mqtt.test.com", 8883, keepalive=60)
        mock_client.loop_start.assert_called_once()

    @patch("paho.mqtt.client.Client")
    def test_disconnect(self, mock_client_class, auth, message_callback):
        """Test MQTT disconnection."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        conn = MqttConnection("DEV123", auth, message_callback)
        conn.connect()
        conn.disconnect()

        mock_client.loop_stop.assert_called()
        mock_client.disconnect.assert_called()

    @patch("paho.mqtt.client.Client")
    def test_on_connect_success(self, mock_client_class, auth, message_callback):
        """Test successful connection callback."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        conn = MqttConnection("DEV123", auth, message_callback)
        conn.connect()

        # Simulate successful connection
        conn._on_connect(mock_client, None, None, MagicMock(__str__=lambda x: "Success"), None)

        assert conn.is_connected()
        mock_client.subscribe.assert_called()

    @patch("paho.mqtt.client.Client")
    def test_on_connect_failure(self, mock_client_class, auth, message_callback):
        """Test failed connection callback."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        conn = MqttConnection("DEV123", auth, message_callback)
        conn.connect()

        # Simulate failed connection
        conn._on_connect(
            mock_client, None, None, MagicMock(__str__=lambda x: "Connection refused"), None
        )

        assert not conn.is_connected()

    @patch("paho.mqtt.client.Client")
    def test_on_message_json(self, mock_client_class, auth, message_callback):
        """Test receiving JSON message."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        conn = MqttConnection("DEV123", auth, message_callback)
        conn.connect()

        # Simulate message
        message = MagicMock()
        message.payload = b'{"params": {"soc": 85}}'
        conn._on_message(mock_client, None, message)

        message_callback.assert_called_once()

    @patch("paho.mqtt.client.Client")
    def test_on_message_binary(self, mock_client_class, auth, message_callback):
        """Test receiving binary message."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        binary_callback = MagicMock()

        conn = MqttConnection("DEV123", auth, message_callback, binary_callback=binary_callback)
        conn.connect()

        # Simulate binary message with invalid UTF-8 bytes that trigger UnicodeDecodeError
        message = MagicMock()
        message.payload = b"\x80\x81\x82\x83"  # Invalid UTF-8 sequence
        conn._on_message(mock_client, None, message)

        binary_callback.assert_called_once_with(b"\x80\x81\x82\x83")


class TestMqttApiClient:
    """Tests for MqttApiClient class."""

    @pytest.fixture
    def mock_auth(self):
        """Mock authentication."""
        with patch.object(MqttAuthentication, "authorize"):
            yield

    @pytest.fixture
    def mock_connection(self):
        """Mock MQTT connection."""
        with patch("ecoflow.api.mqtt.MqttConnection") as mock:
            conn = MagicMock()
            conn.is_connected.return_value = True
            conn.wait_connected.return_value = True
            conn.wait_subscribed.return_value = True
            mock.return_value = conn
            yield conn

    @patch("ecoflow.api.mqtt.MqttAuthentication")
    @patch("ecoflow.api.mqtt.MqttConnection")
    def test_connect_success(self, mock_conn_class, mock_auth_class):
        """Test successful connection."""
        mock_auth = MagicMock()
        mock_auth_class.return_value = mock_auth

        mock_conn = MagicMock()
        mock_conn.wait_connected.return_value = True
        mock_conn.wait_subscribed.return_value = True
        mock_conn_class.return_value = mock_conn

        client = MqttApiClient("test@example.com", "password", "DEV123")
        client.connect()

        mock_auth.authorize.assert_called_once()
        mock_conn.connect.assert_called_once()

    @patch("ecoflow.api.mqtt.MqttAuthentication")
    @patch("ecoflow.api.mqtt.MqttConnection")
    def test_connect_timeout(self, mock_conn_class, mock_auth_class):
        """Test connection timeout."""
        mock_auth = MagicMock()
        mock_auth_class.return_value = mock_auth

        mock_conn = MagicMock()
        mock_conn.wait_connected.return_value = False  # Timeout
        mock_conn_class.return_value = mock_conn

        client = MqttApiClient("test@example.com", "password", "DEV123")

        with pytest.raises(EcoflowApiException) as exc_info:
            client.connect()

        assert "Failed to connect" in str(exc_info.value)

    @patch("ecoflow.api.mqtt.MqttAuthentication")
    @patch("ecoflow.api.mqtt.MqttConnection")
    def test_get_devices(self, mock_conn_class, mock_auth_class):
        """Test getting device list."""
        mock_auth = MagicMock()
        mock_auth_class.return_value = mock_auth

        mock_conn = MagicMock()
        mock_conn.wait_connected.return_value = True
        mock_conn.wait_subscribed.return_value = True
        mock_conn.is_connected.return_value = True
        mock_conn_class.return_value = mock_conn

        client = MqttApiClient("test@example.com", "password", "DEV123")
        client.connect()
        devices = client.get_devices()

        assert len(devices) == 1
        assert devices[0].sn == "DEV123"

    @patch("ecoflow.api.mqtt.MqttAuthentication")
    @patch("ecoflow.api.mqtt.MqttConnection")
    def test_get_device_found(self, mock_conn_class, mock_auth_class):
        """Test getting specific device."""
        mock_auth = MagicMock()
        mock_auth_class.return_value = mock_auth

        mock_conn = MagicMock()
        mock_conn.wait_connected.return_value = True
        mock_conn.wait_subscribed.return_value = True
        mock_conn.is_connected.return_value = True
        mock_conn_class.return_value = mock_conn

        client = MqttApiClient("test@example.com", "password", "DEV123")
        client.connect()
        device = client.get_device("DEV123")

        assert device is not None
        assert device.sn == "DEV123"

    @patch("ecoflow.api.mqtt.MqttAuthentication")
    @patch("ecoflow.api.mqtt.MqttConnection")
    def test_get_device_not_found(self, mock_conn_class, mock_auth_class):
        """Test getting non-existent device."""
        mock_auth = MagicMock()
        mock_auth_class.return_value = mock_auth

        mock_conn = MagicMock()
        mock_conn.wait_connected.return_value = True
        mock_conn.wait_subscribed.return_value = True
        mock_conn_class.return_value = mock_conn

        client = MqttApiClient("test@example.com", "password", "DEV123")
        client.connect()
        device = client.get_device("DIFFERENT")

        assert device is None

    @patch("ecoflow.api.mqtt.MqttAuthentication")
    @patch("ecoflow.api.mqtt.MqttConnection")
    def test_get_device_quota_cached(self, mock_conn_class, mock_auth_class):
        """Test getting cached quota data."""
        mock_auth = MagicMock()
        mock_auth_class.return_value = mock_auth

        mock_conn = MagicMock()
        mock_conn.wait_connected.return_value = True
        mock_conn.wait_subscribed.return_value = True
        mock_conn_class.return_value = mock_conn

        client = MqttApiClient("test@example.com", "password", "DEV123")
        client.connect()

        # Simulate cached data
        client._quota_cache = {"soc": 85, "watts": 100}

        quota = client.get_device_quota("DEV123")

        assert quota["soc"] == 85
        assert quota["watts"] == 100

    @patch("ecoflow.api.mqtt.MqttAuthentication")
    @patch("ecoflow.api.mqtt.MqttConnection")
    def test_get_device_quota_wrong_sn(self, mock_conn_class, mock_auth_class):
        """Test getting quota for wrong device SN."""
        mock_auth = MagicMock()
        mock_auth_class.return_value = mock_auth

        mock_conn = MagicMock()
        mock_conn.wait_connected.return_value = True
        mock_conn.wait_subscribed.return_value = True
        mock_conn_class.return_value = mock_conn

        client = MqttApiClient("test@example.com", "password", "DEV123")
        client.connect()
        client._quota_cache = {"soc": 85}

        quota = client.get_device_quota("DIFFERENT")

        assert quota == {}

    @patch("ecoflow.api.mqtt.MqttAuthentication")
    @patch("ecoflow.api.mqtt.MqttConnection")
    def test_handle_message(self, mock_conn_class, mock_auth_class):
        """Test handling incoming message."""
        mock_auth = MagicMock()
        mock_auth_class.return_value = mock_auth

        mock_conn = MagicMock()
        mock_conn.wait_connected.return_value = True
        mock_conn.wait_subscribed.return_value = True
        mock_conn_class.return_value = mock_conn

        client = MqttApiClient("test@example.com", "password", "DEV123")
        client.connect()

        # Simulate message handling
        payload = '{"params": {"soc": 75, "wattsIn": 200}}'
        client._handle_message(payload)

        assert client._quota_cache["soc"] == 75
        assert client._quota_cache["wattsIn"] == 200

    @patch("ecoflow.api.mqtt.MqttAuthentication")
    @patch("ecoflow.api.mqtt.MqttConnection")
    def test_handle_message_invalid_json(self, mock_conn_class, mock_auth_class):
        """Test handling invalid JSON message."""
        mock_auth = MagicMock()
        mock_auth_class.return_value = mock_auth

        mock_conn = MagicMock()
        mock_conn.wait_connected.return_value = True
        mock_conn.wait_subscribed.return_value = True
        mock_conn_class.return_value = mock_conn

        client = MqttApiClient("test@example.com", "password", "DEV123")
        client.connect()

        # Should not raise, just log error
        client._handle_message("{invalid json}")

        # Cache should remain empty
        assert client._quota_cache == {}

    @patch("ecoflow.api.mqtt.MqttAuthentication")
    @patch("ecoflow.api.mqtt.MqttConnection")
    def test_device_info_product_name_none(self, mock_conn_class, mock_auth_class):
        """Test that device info has product_name as None (not 'Unknown')."""
        mock_auth = MagicMock()
        mock_auth_class.return_value = mock_auth

        mock_conn = MagicMock()
        mock_conn.wait_connected.return_value = True
        mock_conn.wait_subscribed.return_value = True
        mock_conn.is_connected.return_value = True
        mock_conn_class.return_value = mock_conn

        client = MqttApiClient("test@example.com", "password", "DEV123")
        client.connect()

        device = client._get_device_info()

        assert device.product_name is None

    @patch("ecoflow.api.mqtt.MqttAuthentication")
    @patch("ecoflow.api.mqtt.MqttConnection")
    @patch("ecoflow.api.mqtt.RepeatTimer")
    def test_disconnect(self, mock_timer_class, mock_conn_class, mock_auth_class):
        """Test disconnecting from MQTT broker."""
        mock_auth = MagicMock()
        mock_auth_class.return_value = mock_auth

        mock_conn = MagicMock()
        mock_conn.wait_connected.return_value = True
        mock_conn.wait_subscribed.return_value = True
        mock_conn_class.return_value = mock_conn

        mock_timer = MagicMock()
        mock_timer_class.return_value = mock_timer

        client = MqttApiClient("test@example.com", "password", "DEV123")
        client.connect()
        client.disconnect()

        mock_timer.cancel.assert_called_once()
        mock_conn.disconnect.assert_called_once()
        assert client._mqtt is None
        assert client._idle_timer is None

    @patch("ecoflow.api.mqtt.MqttAuthentication")
    @patch("ecoflow.api.mqtt.MqttConnection")
    def test_device_info_offline_no_recent_update(self, mock_conn_class, mock_auth_class):
        """Test device info when no recent update received."""
        import time

        mock_auth = MagicMock()
        mock_auth_class.return_value = mock_auth

        mock_conn = MagicMock()
        mock_conn.wait_connected.return_value = True
        mock_conn.wait_subscribed.return_value = True
        mock_conn.is_connected.return_value = True
        mock_conn_class.return_value = mock_conn

        client = MqttApiClient("test@example.com", "password", "DEV123")
        client.connect()

        # Set last update to long ago (beyond MQTT_TIMEOUT)
        client._last_update = time.time() - 120

        device = client._get_device_info()

        assert device.online is False

    @patch("ecoflow.api.mqtt.MqttAuthentication")
    @patch("ecoflow.api.mqtt.MqttConnection")
    def test_handle_binary_message_success(self, mock_conn_class, mock_auth_class):
        """Test handling binary protobuf message."""
        mock_auth = MagicMock()
        mock_auth_class.return_value = mock_auth

        mock_conn = MagicMock()
        mock_conn.wait_connected.return_value = True
        mock_conn.wait_subscribed.return_value = True
        mock_conn_class.return_value = mock_conn

        client = MqttApiClient("test@example.com", "password", "DEV123")
        client.connect()

        # Mock the decoder
        client._proto_decoder.decode = MagicMock(return_value={"soc": 85, "temp": 25})

        client._handle_binary_message(b"\x00\x01\x02")

        assert client._quota_cache["soc"] == 85
        assert client._quota_cache["temp"] == 25

    @patch("ecoflow.api.mqtt.MqttAuthentication")
    @patch("ecoflow.api.mqtt.MqttConnection")
    def test_handle_binary_message_empty(self, mock_conn_class, mock_auth_class):
        """Test handling binary message with empty decode result."""
        mock_auth = MagicMock()
        mock_auth_class.return_value = mock_auth

        mock_conn = MagicMock()
        mock_conn.wait_connected.return_value = True
        mock_conn.wait_subscribed.return_value = True
        mock_conn_class.return_value = mock_conn

        client = MqttApiClient("test@example.com", "password", "DEV123")
        client.connect()

        # Mock decoder returning empty dict
        client._proto_decoder.decode = MagicMock(return_value={})

        client._handle_binary_message(b"\x00\x01\x02")

        assert client._quota_cache == {}

    @patch("ecoflow.api.mqtt.MqttAuthentication")
    @patch("ecoflow.api.mqtt.MqttConnection")
    def test_handle_binary_message_error(self, mock_conn_class, mock_auth_class):
        """Test handling binary message decode error."""
        mock_auth = MagicMock()
        mock_auth_class.return_value = mock_auth

        mock_conn = MagicMock()
        mock_conn.wait_connected.return_value = True
        mock_conn.wait_subscribed.return_value = True
        mock_conn_class.return_value = mock_conn

        client = MqttApiClient("test@example.com", "password", "DEV123")
        client.connect()

        # Mock decoder raising exception
        client._proto_decoder.decode = MagicMock(side_effect=Exception("Decode error"))

        # Should not raise
        client._handle_binary_message(b"\x00\x01\x02")

        assert client._quota_cache == {}

    @patch("ecoflow.api.mqtt.MqttAuthentication")
    @patch("ecoflow.api.mqtt.MqttConnection")
    def test_check_idle_no_mqtt(self, mock_conn_class, mock_auth_class):
        """Test check_idle when mqtt is None."""
        mock_auth = MagicMock()
        mock_auth_class.return_value = mock_auth

        client = MqttApiClient("test@example.com", "password", "DEV123")
        client._mqtt = None

        # Should not raise
        client._check_idle()

    @patch("ecoflow.api.mqtt.MqttAuthentication")
    @patch("ecoflow.api.mqtt.MqttConnection")
    def test_check_idle_recent_message(self, mock_conn_class, mock_auth_class):
        """Test check_idle when message was recent."""
        import time

        mock_auth = MagicMock()
        mock_auth_class.return_value = mock_auth

        mock_conn = MagicMock()
        mock_conn.wait_connected.return_value = True
        mock_conn.wait_subscribed.return_value = True
        mock_conn.last_message_time = time.time()  # Recent
        mock_conn_class.return_value = mock_conn

        client = MqttApiClient("test@example.com", "password", "DEV123")
        client.connect()

        with patch.object(client, "_reconnect") as mock_reconnect:
            client._check_idle()
            mock_reconnect.assert_not_called()

    @patch("ecoflow.api.mqtt.MqttAuthentication")
    @patch("ecoflow.api.mqtt.MqttConnection")
    def test_check_idle_triggers_reconnect(self, mock_conn_class, mock_auth_class):
        """Test check_idle triggers reconnect when idle too long."""
        import time

        mock_auth = MagicMock()
        mock_auth_class.return_value = mock_auth

        mock_conn = MagicMock()
        mock_conn.wait_connected.return_value = True
        mock_conn.wait_subscribed.return_value = True
        mock_conn.last_message_time = time.time() - 120  # 2 minutes ago
        mock_conn_class.return_value = mock_conn

        client = MqttApiClient("test@example.com", "password", "DEV123")
        client.connect()

        with patch.object(client, "_reconnect") as mock_reconnect:
            client._check_idle()
            mock_reconnect.assert_called_once()

    @patch("ecoflow.api.mqtt.MqttAuthentication")
    @patch("ecoflow.api.mqtt.MqttConnection")
    def test_reconnect_no_mqtt(self, mock_conn_class, mock_auth_class):
        """Test reconnect when mqtt is None."""
        mock_auth = MagicMock()
        mock_auth_class.return_value = mock_auth

        client = MqttApiClient("test@example.com", "password", "DEV123")
        client._mqtt = None

        # Should not raise
        client._reconnect()

    @patch("ecoflow.api.mqtt.MqttAuthentication")
    @patch("ecoflow.api.mqtt.MqttConnection")
    def test_reconnect_success(self, mock_conn_class, mock_auth_class):
        """Test successful reconnection."""
        mock_auth = MagicMock()
        mock_auth_class.return_value = mock_auth

        mock_conn = MagicMock()
        mock_conn.wait_connected.return_value = True
        mock_conn.wait_subscribed.return_value = True
        mock_conn.is_connected.return_value = True
        mock_conn_class.return_value = mock_conn

        client = MqttApiClient("test@example.com", "password", "DEV123")
        client.connect()
        client._reconnect_delay = 60  # Simulate previous backoff

        client._reconnect()

        # Should reset delay on success
        assert client._reconnect_delay == 30  # IDLE_CHECK_INTERVAL

    @patch("ecoflow.api.mqtt.MqttAuthentication")
    @patch("ecoflow.api.mqtt.MqttConnection")
    def test_reconnect_failure(self, mock_conn_class, mock_auth_class):
        """Test failed reconnection applies backoff."""
        mock_auth = MagicMock()
        mock_auth_class.return_value = mock_auth

        mock_conn = MagicMock()
        mock_conn.wait_connected.return_value = True
        mock_conn.wait_subscribed.return_value = True
        mock_conn.is_connected.return_value = False  # Reconnect fails
        mock_conn_class.return_value = mock_conn

        client = MqttApiClient("test@example.com", "password", "DEV123")
        client.connect()
        initial_delay = client._reconnect_delay

        client._reconnect()

        # Should apply backoff
        assert client._reconnect_delay == initial_delay * 2

    @patch("ecoflow.api.mqtt.MqttAuthentication")
    @patch("ecoflow.api.mqtt.MqttConnection")
    def test_apply_backoff(self, mock_conn_class, mock_auth_class):
        """Test exponential backoff application."""
        mock_auth = MagicMock()
        mock_auth_class.return_value = mock_auth

        mock_conn = MagicMock()
        mock_conn.wait_connected.return_value = True
        mock_conn.wait_subscribed.return_value = True
        mock_conn_class.return_value = mock_conn

        client = MqttApiClient("test@example.com", "password", "DEV123")
        client.connect()
        initial_delay = client._reconnect_delay

        client._apply_backoff()

        assert client._reconnect_delay == initial_delay * 2
        assert client._mqtt.last_message_time is not None

    @patch("ecoflow.api.mqtt.MqttAuthentication")
    @patch("ecoflow.api.mqtt.MqttConnection")
    def test_apply_backoff_capped(self, mock_conn_class, mock_auth_class):
        """Test that backoff is capped at max delay."""
        mock_auth = MagicMock()
        mock_auth_class.return_value = mock_auth

        mock_conn = MagicMock()
        mock_conn.wait_connected.return_value = True
        mock_conn.wait_subscribed.return_value = True
        mock_conn_class.return_value = mock_conn

        client = MqttApiClient("test@example.com", "password", "DEV123")
        client.connect()
        client._reconnect_delay = 200  # Close to max

        client._apply_backoff()

        assert client._reconnect_delay <= 300  # MAX_RECONNECT_DELAY

    @patch("ecoflow.api.mqtt.MqttAuthentication")
    @patch("ecoflow.api.mqtt.MqttConnection")
    def test_handle_message_exception(self, mock_conn_class, mock_auth_class):
        """Test handling message with unexpected exception."""
        mock_auth = MagicMock()
        mock_auth_class.return_value = mock_auth

        mock_conn = MagicMock()
        mock_conn.wait_connected.return_value = True
        mock_conn.wait_subscribed.return_value = True
        mock_conn_class.return_value = mock_conn

        client = MqttApiClient("test@example.com", "password", "DEV123")
        client.connect()

        # Replace quota cache with a mock that raises exception on update
        mock_cache = MagicMock()
        mock_cache.update.side_effect = Exception("Cache update error")
        client._quota_cache = mock_cache

        # Should not raise, just log error
        client._handle_message('{"params": {"soc": 75}}')
