"""Tests for ecoflow/api/device.py - Device API client."""

import json
import time
from unittest.mock import MagicMock, patch

import pytest

from ecoflow.api.device import DeviceApiClient, _gen_request_id
from ecoflow.api.models import EcoflowApiException


class TestGenRequestId:
    """Tests for _gen_request_id() function."""

    def test_returns_integer(self):
        """Test that request ID is an integer."""
        request_id = _gen_request_id()
        assert isinstance(request_id, int)

    def test_in_expected_range(self):
        """Test that request ID is in expected range."""
        for _ in range(100):
            request_id = _gen_request_id()
            assert 999910000 <= request_id < 1000000000

    def test_randomness(self):
        """Test that request IDs are random."""
        ids = [_gen_request_id() for _ in range(100)]
        # Should have mostly unique IDs
        unique_ids = set(ids)
        assert len(unique_ids) > 90  # Allow some collisions


class TestDeviceApiClient:
    """Tests for DeviceApiClient class."""

    @pytest.fixture
    def mock_auth(self):
        """Mock MQTT authentication."""
        with patch('ecoflow.api.device.MqttAuthentication') as mock:
            auth = MagicMock()
            auth.mqtt_url = "mqtt.test.com"
            auth.mqtt_port = 8883
            auth.mqtt_username = "test_user"
            auth.mqtt_password = "test_pass"
            auth.mqtt_client_id = "test_client"
            auth.user_id = "user123"
            mock.return_value = auth
            yield auth

    @pytest.fixture
    def mock_mqtt_client(self):
        """Mock MQTT client."""
        with patch('paho.mqtt.client.Client') as mock:
            client = MagicMock()
            mock.return_value = client
            yield client

    @pytest.fixture
    def mock_proto_decoder(self):
        """Mock protobuf decoder."""
        with patch('ecoflow.proto.decoder.get_decoder') as mock:
            decoder = MagicMock()
            decoder.decode.return_value = {}
            mock.return_value = decoder
            yield decoder

    def test_init(self, mock_auth, mock_proto_decoder):
        """Test client initialization."""
        client = DeviceApiClient("test@example.com", "password", "DEV123")

        assert client.device_sn == "DEV123"
        assert client._quota_cache == {}

    @patch('ecoflow.api.device.RepeatTimer')
    def test_connect_success(self, mock_timer, mock_auth, mock_mqtt_client, mock_proto_decoder):
        """Test successful connection."""
        client = DeviceApiClient("test@example.com", "password", "DEV123")

        # Simulate successful connection
        def trigger_connect(*args, **kwargs):
            client._connected.set()
            client._subscribed.set()

        mock_mqtt_client.connect.side_effect = trigger_connect

        client.connect()

        mock_auth.authorize.assert_called_once()
        mock_mqtt_client.connect.assert_called_once()
        assert client._data_topic == "/app/device/property/DEV123"
        assert client._get_topic == "/app/user123/DEV123/thing/property/get"

    @patch('ecoflow.api.device.RepeatTimer')
    def test_connect_timeout(self, mock_timer, mock_auth, mock_mqtt_client, mock_proto_decoder):
        """Test connection timeout."""
        client = DeviceApiClient("test@example.com", "password", "DEV123")

        # Don't set connected event (timeout)

        with pytest.raises(EcoflowApiException) as exc_info:
            client.connect()

        assert "Failed to connect" in str(exc_info.value)

    @patch('ecoflow.api.device.RepeatTimer')
    def test_disconnect(self, mock_timer, mock_auth, mock_mqtt_client, mock_proto_decoder):
        """Test disconnection."""
        client = DeviceApiClient("test@example.com", "password", "DEV123")

        def trigger_connect(*args, **kwargs):
            client._connected.set()
            client._subscribed.set()

        mock_mqtt_client.connect.side_effect = trigger_connect

        client.connect()
        client.disconnect()

        mock_mqtt_client.loop_stop.assert_called()
        mock_mqtt_client.disconnect.assert_called()
        assert not client._connected.is_set()

    def test_get_devices(self, mock_auth, mock_proto_decoder):
        """Test getting device list."""
        client = DeviceApiClient("test@example.com", "password", "DEV123")

        devices = client.get_devices()

        assert len(devices) == 1
        assert devices[0].sn == "DEV123"

    def test_get_device_found(self, mock_auth, mock_proto_decoder):
        """Test getting existing device."""
        client = DeviceApiClient("test@example.com", "password", "DEV123")

        device = client.get_device("DEV123")

        assert device is not None
        assert device.sn == "DEV123"

    def test_get_device_not_found(self, mock_auth, mock_proto_decoder):
        """Test getting non-existent device."""
        client = DeviceApiClient("test@example.com", "password", "DEV123")

        device = client.get_device("DIFFERENT")

        assert device is None

    def test_get_device_quota(self, mock_auth, mock_proto_decoder):
        """Test getting device quota."""
        client = DeviceApiClient("test@example.com", "password", "DEV123")
        client._quota_cache = {"soc": 85, "watts": 100}

        quota = client.get_device_quota("DEV123")

        assert quota["soc"] == 85
        assert quota["watts"] == 100

    def test_get_device_quota_wrong_sn(self, mock_auth, mock_proto_decoder):
        """Test getting quota for wrong device."""
        client = DeviceApiClient("test@example.com", "password", "DEV123")
        client._quota_cache = {"soc": 85}

        quota = client.get_device_quota("DIFFERENT")

        assert quota == {}

    def test_get_device_info_online(self, mock_auth, mock_proto_decoder):
        """Test device info when online."""
        client = DeviceApiClient("test@example.com", "password", "DEV123")
        client._connected.set()
        client._last_update = time.time()

        device = client._get_device_info()

        assert device.sn == "DEV123"
        assert device.online is True

    def test_get_device_info_offline_no_update(self, mock_auth, mock_proto_decoder):
        """Test device info when no recent update."""
        client = DeviceApiClient("test@example.com", "password", "DEV123")
        client._connected.set()
        client._last_update = time.time() - 120  # 2 minutes ago

        device = client._get_device_info()

        assert device.online is False

    def test_get_device_info_disconnected(self, mock_auth, mock_proto_decoder):
        """Test device info when disconnected."""
        client = DeviceApiClient("test@example.com", "password", "DEV123")
        client._last_update = time.time()

        device = client._get_device_info()

        assert device.online is False

    def test_device_info_product_name_none(self, mock_auth, mock_proto_decoder):
        """Test that device info has product_name as None."""
        client = DeviceApiClient("test@example.com", "password", "DEV123")

        device = client._get_device_info()

        assert device.product_name is None

    def test_handle_quota_reply_online(self, mock_auth, mock_proto_decoder):
        """Test handling quota reply when device is online."""
        client = DeviceApiClient("test@example.com", "password", "DEV123")

        payload = json.dumps({
            "operateType": "latestQuotas",
            "data": {
                "online": 1,
                "quotaMap": {"soc": 75, "watts": 200}
            }
        })

        client._handle_quota_reply(payload)

        assert client._quota_cache["soc"] == 75
        assert client._quota_cache["watts"] == 200

    def test_handle_quota_reply_offline(self, mock_auth, mock_proto_decoder):
        """Test handling quota reply when device is offline."""
        client = DeviceApiClient("test@example.com", "password", "DEV123")

        payload = json.dumps({
            "operateType": "latestQuotas",
            "data": {
                "online": 0,
                "quotaMap": {}
            }
        })

        client._handle_quota_reply(payload)

        # Cache should not be updated
        assert client._quota_cache == {}

    def test_handle_quota_reply_invalid_json(self, mock_auth, mock_proto_decoder):
        """Test handling invalid JSON in quota reply."""
        client = DeviceApiClient("test@example.com", "password", "DEV123")

        # Should not raise
        client._handle_quota_reply("{invalid}")

        assert client._quota_cache == {}

    def test_handle_data_message(self, mock_auth, mock_proto_decoder):
        """Test handling push data message."""
        client = DeviceApiClient("test@example.com", "password", "DEV123")

        payload = json.dumps({
            "params": {"soc": 80, "temp": 25}
        })

        client._handle_data_message(payload)

        assert client._quota_cache["soc"] == 80
        assert client._quota_cache["temp"] == 25
        assert client._last_push_data_time is not None

    def test_handle_data_message_invalid_json(self, mock_auth, mock_proto_decoder):
        """Test handling invalid JSON in data message."""
        client = DeviceApiClient("test@example.com", "password", "DEV123")

        # Should not raise
        client._handle_data_message("{invalid}")

        assert client._quota_cache == {}

    @patch('ecoflow.api.device.RepeatTimer')
    def test_request_quota_not_connected(self, mock_timer, mock_auth, mock_mqtt_client, mock_proto_decoder):
        """Test quota request when not connected."""
        client = DeviceApiClient("test@example.com", "password", "DEV123")

        # Should not raise, just skip
        client._request_quota()

        # Should not have published
        mock_mqtt_client.publish.assert_not_called()

    @patch('ecoflow.api.device.RepeatTimer')
    def test_request_quota_skip_recent_push(self, mock_timer, mock_auth, mock_mqtt_client, mock_proto_decoder):
        """Test quota request skipped when recent push data received."""
        client = DeviceApiClient("test@example.com", "password", "DEV123")
        client._connected.set()
        client._client = mock_mqtt_client
        client._get_topic = "/app/user123/DEV123/thing/property/get"
        client._last_push_data_time = time.time()  # Just now

        client._request_quota()

        # Should not have published (recent push data)
        mock_mqtt_client.publish.assert_not_called()

    @patch('ecoflow.api.device.RepeatTimer')
    def test_request_quota_sends_request(self, mock_timer, mock_auth, mock_mqtt_client, mock_proto_decoder):
        """Test quota request is sent when needed."""
        client = DeviceApiClient("test@example.com", "password", "DEV123")
        client._connected.set()
        client._client = mock_mqtt_client
        client._get_topic = "/app/user123/DEV123/thing/property/get"
        client._last_push_data_time = None  # No recent push

        client._request_quota()

        mock_mqtt_client.publish.assert_called_once()
        call_args = mock_mqtt_client.publish.call_args
        assert call_args[0][0] == "/app/user123/DEV123/thing/property/get"

    def test_handle_binary_message(self, mock_auth, mock_proto_decoder):
        """Test handling binary protobuf message."""
        client = DeviceApiClient("test@example.com", "password", "DEV123")
        mock_proto_decoder.decode.return_value = {"soc": 90, "temp": 30}

        client._handle_binary_message(b'\x00\x01\x02')

        assert client._quota_cache["soc"] == 90
        assert client._quota_cache["temp"] == 30

    def test_handle_binary_message_empty(self, mock_auth, mock_proto_decoder):
        """Test handling binary message with no decoded params."""
        client = DeviceApiClient("test@example.com", "password", "DEV123")
        mock_proto_decoder.decode.return_value = {}

        client._handle_binary_message(b'\x00\x01\x02')

        assert client._quota_cache == {}

    def test_handle_binary_message_error(self, mock_auth, mock_proto_decoder):
        """Test handling binary message decode error."""
        client = DeviceApiClient("test@example.com", "password", "DEV123")
        mock_proto_decoder.decode.side_effect = Exception("Decode error")

        # Should not raise
        client._handle_binary_message(b'\x00\x01\x02')

        assert client._quota_cache == {}

    def test_check_idle_no_reconnect_needed(self, mock_auth, mock_proto_decoder):
        """Test idle check when no reconnect needed."""
        client = DeviceApiClient("test@example.com", "password", "DEV123")
        client._last_message_time = time.time()  # Recent message

        # Should not reconnect
        with patch.object(client, '_reconnect') as mock_reconnect:
            client._check_idle()
            mock_reconnect.assert_not_called()

    def test_check_idle_reconnect_needed(self, mock_auth, mock_proto_decoder):
        """Test idle check when reconnect is needed."""
        client = DeviceApiClient("test@example.com", "password", "DEV123")
        client._last_message_time = time.time() - 120  # 2 minutes ago

        with patch.object(client, '_reconnect') as mock_reconnect:
            client._check_idle()
            mock_reconnect.assert_called_once()

    def test_apply_backoff(self, mock_auth, mock_proto_decoder):
        """Test exponential backoff application."""
        client = DeviceApiClient("test@example.com", "password", "DEV123")
        initial_delay = client._reconnect_delay

        client._apply_backoff()

        assert client._reconnect_delay == initial_delay * 2
        assert client._last_message_time is not None

    def test_apply_backoff_capped(self, mock_auth, mock_proto_decoder):
        """Test that backoff is capped at max delay."""
        client = DeviceApiClient("test@example.com", "password", "DEV123")
        client._reconnect_delay = 200  # Close to max

        client._apply_backoff()

        assert client._reconnect_delay <= 300  # MAX_RECONNECT_DELAY
