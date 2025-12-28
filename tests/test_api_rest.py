"""Tests for ecoflow/api/rest.py - REST API client."""

import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from ecoflow.api.models import DeviceInfo, EcoflowApiException
from ecoflow.api.rest import RestApiAuthentication, RestApiClient


class TestRestApiAuthentication:
    """Tests for RestApiAuthentication class."""

    def test_build_signature(self):
        """Test HMAC-SHA256 signature generation."""
        auth = RestApiAuthentication("access_key", "secret_key")

        signature = auth.build_signature("test_message")

        # Should return a hex string
        assert isinstance(signature, str)
        assert len(signature) == 64  # SHA256 produces 64 hex chars

    def test_signature_consistency(self):
        """Test that same input produces same signature."""
        auth = RestApiAuthentication("access_key", "secret_key")

        sig1 = auth.build_signature("same_message")
        sig2 = auth.build_signature("same_message")

        assert sig1 == sig2

    def test_signature_different_for_different_input(self):
        """Test that different input produces different signature."""
        auth = RestApiAuthentication("access_key", "secret_key")

        sig1 = auth.build_signature("message1")
        sig2 = auth.build_signature("message2")

        assert sig1 != sig2

    def test_signature_different_for_different_keys(self):
        """Test that different keys produce different signatures."""
        auth1 = RestApiAuthentication("access_key", "secret1")
        auth2 = RestApiAuthentication("access_key", "secret2")

        sig1 = auth1.build_signature("same_message")
        sig2 = auth2.build_signature("same_message")

        assert sig1 != sig2


class TestRestApiClient:
    """Tests for RestApiClient class."""

    @pytest.fixture
    def client(self):
        """Create a REST API client for testing."""
        return RestApiClient("test_access_key", "test_secret_key")

    @pytest.fixture
    def mock_session(self):
        """Mock requests session."""
        with patch("ecoflow.api.rest._create_session") as mock:
            session = MagicMock()
            mock.return_value = session
            yield session

    def test_connect_success(self, client, mock_session):
        """Test successful connection."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "code": "0",
            "message": "Success",
            "data": [
                {
                    "sn": "TEST123",
                    "deviceName": "My Device",
                    "productName": "Delta Pro",
                    "online": 1,
                }
            ],
        }
        mock_session.request.return_value = mock_response

        client.connect()

        assert client._session is not None
        mock_session.request.assert_called_once()

    def test_connect_api_error(self, client, mock_session):
        """Test connection with API error response."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"code": "1001", "message": "Invalid signature"}
        mock_session.request.return_value = mock_response

        with pytest.raises(EcoflowApiException) as exc_info:
            client.connect()

        assert "Invalid signature" in str(exc_info.value)

    def test_connect_http_error(self, client, mock_session):
        """Test connection with HTTP error."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_session.request.return_value = mock_response

        with pytest.raises(EcoflowApiException) as exc_info:
            client.connect()

        assert "HTTP 500" in str(exc_info.value)

    def test_connect_timeout(self, client, mock_session):
        """Test connection timeout."""
        mock_session.request.side_effect = requests.Timeout()

        with pytest.raises(EcoflowApiException) as exc_info:
            client.connect()

        assert "timed out" in str(exc_info.value)

    def test_connect_request_exception(self, client, mock_session):
        """Test connection with request exception."""
        mock_session.request.side_effect = requests.RequestException("Network error")

        with pytest.raises(EcoflowApiException) as exc_info:
            client.connect()

        assert "Request failed" in str(exc_info.value)

    def test_disconnect(self, client, mock_session):
        """Test disconnection."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"code": "0", "data": []}
        mock_session.request.return_value = mock_response

        client.connect()
        client.disconnect()

        mock_session.close.assert_called_once()
        assert client._session is None

    def test_get_devices(self, client, mock_session):
        """Test getting device list."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "code": "0",
            "data": [
                {"sn": "DEV1", "deviceName": "Device 1", "productName": "Delta", "online": 1},
                {"sn": "DEV2", "deviceName": "Device 2", "productName": "River", "online": 0},
            ],
        }
        mock_session.request.return_value = mock_response

        client.connect()
        devices = client.get_devices()

        assert len(devices) == 2
        assert devices[0].sn == "DEV1"
        assert devices[0].name == "Device 1"
        assert devices[0].online is True
        assert devices[1].online is False

    def test_get_device_found(self, client, mock_session):
        """Test getting specific device that exists."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "code": "0",
            "data": [
                {"sn": "DEV1", "deviceName": "Device 1", "productName": "Delta", "online": 1},
            ],
        }
        mock_session.request.return_value = mock_response

        client.connect()
        device = client.get_device("DEV1")

        assert device is not None
        assert device.sn == "DEV1"

    def test_get_device_not_found(self, client, mock_session):
        """Test getting specific device that doesn't exist."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "code": "0",
            "data": [
                {"sn": "DEV1", "deviceName": "Device 1", "productName": "Delta", "online": 1},
            ],
        }
        mock_session.request.return_value = mock_response

        client.connect()
        device = client.get_device("NONEXISTENT")

        assert device is None

    def test_get_device_quota(self, client, mock_session):
        """Test getting device quota."""
        # First call for connect (get_devices)
        devices_response = MagicMock()
        devices_response.status_code = 200
        devices_response.json.return_value = {"code": "0", "data": []}

        # Second call for quota
        quota_response = MagicMock()
        quota_response.status_code = 200
        quota_response.json.return_value = {
            "code": "0",
            "data": {"soc": 85, "wattsIn": 120, "wattsOut": 450},
        }

        mock_session.request.side_effect = [devices_response, quota_response]

        client.connect()
        quota = client.get_device_quota("DEV1")

        assert quota["soc"] == 85
        assert quota["wattsIn"] == 120

    def test_unwrap_response_success(self, client):
        """Test unwrapping successful response."""
        response = {"code": "0", "data": {"key": "value"}}

        result = client._unwrap_response(response)

        assert result == {"key": "value"}

    def test_unwrap_response_error(self, client):
        """Test unwrapping error response."""
        response = {"code": "1001", "message": "Error occurred"}

        with pytest.raises(EcoflowApiException) as exc_info:
            client._unwrap_response(response)

        assert "code=1001" in str(exc_info.value)
        assert "Error occurred" in str(exc_info.value)

    def test_unwrap_response_no_data(self, client):
        """Test unwrapping response without data field."""
        response = {"code": "0"}

        result = client._unwrap_response(response)

        assert result == {}

    def test_parse_device(self, client):
        """Test parsing device data."""
        data = {"sn": "TEST123", "deviceName": "My Device", "productName": "Delta Pro", "online": 1}

        device = client._parse_device(data)

        assert isinstance(device, DeviceInfo)
        assert device.sn == "TEST123"
        assert device.name == "My Device"
        assert device.product_name == "Delta Pro"
        assert device.online is True

    def test_parse_device_offline(self, client):
        """Test parsing offline device."""
        data = {"sn": "TEST123", "deviceName": "My Device", "productName": "Delta Pro", "online": 0}

        device = client._parse_device(data)

        assert device.online is False

    def test_parse_device_missing_fields(self, client):
        """Test parsing device with missing fields."""
        data = {"sn": "TEST123"}

        device = client._parse_device(data)

        assert device.sn == "TEST123"
        assert device.name == ""
        assert device.product_name == ""
        assert device.online is False

    def test_invalid_json_response(self, client, mock_session):
        """Test handling invalid JSON response."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = json.JSONDecodeError("Invalid", "", 0)
        mock_session.request.return_value = mock_response

        with pytest.raises(EcoflowApiException) as exc_info:
            client.connect()

        assert "Invalid JSON" in str(exc_info.value)
