"""Tests for ecoflow/api/__init__.py - API client factory."""

import os
from unittest.mock import patch

import pytest

from ecoflow.api import (
    CredentialsConflictError,
    DeviceApiClient,
    MqttApiClient,
    RestApiClient,
    create_client,
)


@pytest.fixture
def clean_env():
    """Clean environment variables related to EcoFlow API."""
    env_vars = [
        "ECOFLOW_ACCESS_KEY",
        "ECOFLOW_SECRET_KEY",
        "ECOFLOW_ACCOUNT_USER",
        "ECOFLOW_ACCOUNT_PASSWORD",
        "ECOFLOW_API_TYPE",
    ]
    original = {k: os.environ.get(k) for k in env_vars}
    for var in env_vars:
        if var in os.environ:
            del os.environ[var]
    yield
    for var, val in original.items():
        if val is not None:
            os.environ[var] = val
        elif var in os.environ:
            del os.environ[var]


class TestCreateClientRestApi:
    """Tests for create_client() with REST API credentials."""

    def test_create_rest_client(self, clean_env):
        """Test creating REST API client with developer tokens."""
        os.environ["ECOFLOW_ACCESS_KEY"] = "test_access_key"
        os.environ["ECOFLOW_SECRET_KEY"] = "test_secret_key"

        client = create_client()

        assert isinstance(client, RestApiClient)

    def test_rest_client_does_not_require_device_sn(self, clean_env):
        """Test that REST client doesn't require device_sn."""
        os.environ["ECOFLOW_ACCESS_KEY"] = "test_access_key"
        os.environ["ECOFLOW_SECRET_KEY"] = "test_secret_key"

        # Should not raise even without device_sn
        client = create_client(device_sn=None)

        assert isinstance(client, RestApiClient)

    def test_rest_client_ignores_device_sn(self, clean_env):
        """Test that REST client ignores device_sn parameter."""
        os.environ["ECOFLOW_ACCESS_KEY"] = "test_access_key"
        os.environ["ECOFLOW_SECRET_KEY"] = "test_secret_key"

        client = create_client(device_sn="DEV123")

        assert isinstance(client, RestApiClient)


class TestCreateClientMqttApi:
    """Tests for create_client() with MQTT API credentials."""

    @patch("ecoflow.api.mqtt.MqttAuthentication")
    @patch("ecoflow.proto.decoder.get_decoder")
    def test_create_mqtt_client_default(self, mock_decoder, mock_auth, clean_env):
        """Test creating MQTT client (default when api_type not set)."""
        os.environ["ECOFLOW_ACCOUNT_USER"] = "test@example.com"
        os.environ["ECOFLOW_ACCOUNT_PASSWORD"] = "password123"

        client = create_client(device_sn="DEV123")

        assert isinstance(client, MqttApiClient)

    @patch("ecoflow.api.mqtt.MqttAuthentication")
    @patch("ecoflow.proto.decoder.get_decoder")
    def test_create_mqtt_client_explicit(self, mock_decoder, mock_auth, clean_env):
        """Test creating MQTT client with explicit api_type."""
        os.environ["ECOFLOW_ACCOUNT_USER"] = "test@example.com"
        os.environ["ECOFLOW_ACCOUNT_PASSWORD"] = "password123"
        os.environ["ECOFLOW_API_TYPE"] = "mqtt"

        client = create_client(device_sn="DEV123")

        assert isinstance(client, MqttApiClient)

    @patch("ecoflow.api.mqtt.MqttAuthentication")
    @patch("ecoflow.proto.decoder.get_decoder")
    def test_create_mqtt_client_case_insensitive(self, mock_decoder, mock_auth, clean_env):
        """Test that api_type is case insensitive."""
        os.environ["ECOFLOW_ACCOUNT_USER"] = "test@example.com"
        os.environ["ECOFLOW_ACCOUNT_PASSWORD"] = "password123"
        os.environ["ECOFLOW_API_TYPE"] = "MQTT"

        client = create_client(device_sn="DEV123")

        assert isinstance(client, MqttApiClient)

    def test_mqtt_requires_device_sn(self, clean_env):
        """Test that MQTT client requires device_sn."""
        os.environ["ECOFLOW_ACCOUNT_USER"] = "test@example.com"
        os.environ["ECOFLOW_ACCOUNT_PASSWORD"] = "password123"

        with pytest.raises(ValueError) as exc_info:
            create_client(device_sn=None)

        assert "ECOFLOW_DEVICE_SN is required" in str(exc_info.value)


class TestCreateClientDeviceApi:
    """Tests for create_client() with Device API credentials."""

    @patch("ecoflow.api.device.MqttAuthentication")
    @patch("ecoflow.proto.decoder.get_decoder")
    def test_create_device_client(self, mock_decoder, mock_auth, clean_env):
        """Test creating Device API client."""
        os.environ["ECOFLOW_ACCOUNT_USER"] = "test@example.com"
        os.environ["ECOFLOW_ACCOUNT_PASSWORD"] = "password123"
        os.environ["ECOFLOW_API_TYPE"] = "device"

        client = create_client(device_sn="DEV123")

        assert isinstance(client, DeviceApiClient)

    @patch("ecoflow.api.device.MqttAuthentication")
    @patch("ecoflow.proto.decoder.get_decoder")
    def test_create_device_client_case_insensitive(self, mock_decoder, mock_auth, clean_env):
        """Test that api_type is case insensitive for device."""
        os.environ["ECOFLOW_ACCOUNT_USER"] = "test@example.com"
        os.environ["ECOFLOW_ACCOUNT_PASSWORD"] = "password123"
        os.environ["ECOFLOW_API_TYPE"] = "DEVICE"

        client = create_client(device_sn="DEV123")

        assert isinstance(client, DeviceApiClient)

    def test_device_requires_device_sn(self, clean_env):
        """Test that Device client requires device_sn."""
        os.environ["ECOFLOW_ACCOUNT_USER"] = "test@example.com"
        os.environ["ECOFLOW_ACCOUNT_PASSWORD"] = "password123"
        os.environ["ECOFLOW_API_TYPE"] = "device"

        with pytest.raises(ValueError) as exc_info:
            create_client(device_sn=None)

        assert "ECOFLOW_DEVICE_SN is required" in str(exc_info.value)


class TestCreateClientErrors:
    """Tests for create_client() error handling."""

    def test_conflict_both_credentials(self, clean_env):
        """Test error when both REST and user credentials provided."""
        os.environ["ECOFLOW_ACCESS_KEY"] = "access_key"
        os.environ["ECOFLOW_SECRET_KEY"] = "secret_key"
        os.environ["ECOFLOW_ACCOUNT_USER"] = "test@example.com"
        os.environ["ECOFLOW_ACCOUNT_PASSWORD"] = "password"

        with pytest.raises(CredentialsConflictError) as exc_info:
            create_client()

        assert "Both REST API and user credentials" in str(exc_info.value)

    def test_no_credentials(self, clean_env):
        """Test error when no credentials provided."""
        with pytest.raises(ValueError) as exc_info:
            create_client()

        assert "Missing credentials" in str(exc_info.value)

    def test_partial_rest_credentials_access_key_only(self, clean_env):
        """Test error when only access_key is provided."""
        os.environ["ECOFLOW_ACCESS_KEY"] = "access_key"

        with pytest.raises(ValueError) as exc_info:
            create_client()

        assert "Missing credentials" in str(exc_info.value)

    def test_partial_rest_credentials_secret_key_only(self, clean_env):
        """Test error when only secret_key is provided."""
        os.environ["ECOFLOW_SECRET_KEY"] = "secret_key"

        with pytest.raises(ValueError) as exc_info:
            create_client()

        assert "Missing credentials" in str(exc_info.value)

    def test_partial_user_credentials_user_only(self, clean_env):
        """Test error when only account_user is provided."""
        os.environ["ECOFLOW_ACCOUNT_USER"] = "test@example.com"

        with pytest.raises(ValueError) as exc_info:
            create_client()

        assert "Missing credentials" in str(exc_info.value)

    def test_partial_user_credentials_password_only(self, clean_env):
        """Test error when only account_password is provided."""
        os.environ["ECOFLOW_ACCOUNT_PASSWORD"] = "password"

        with pytest.raises(ValueError) as exc_info:
            create_client()

        assert "Missing credentials" in str(exc_info.value)

    def test_invalid_api_type(self, clean_env):
        """Test error when invalid api_type is provided."""
        os.environ["ECOFLOW_ACCOUNT_USER"] = "test@example.com"
        os.environ["ECOFLOW_ACCOUNT_PASSWORD"] = "password"
        os.environ["ECOFLOW_API_TYPE"] = "invalid"

        with pytest.raises(ValueError) as exc_info:
            create_client(device_sn="DEV123")

        assert "Invalid ECOFLOW_API_TYPE" in str(exc_info.value)
        assert "'invalid'" in str(exc_info.value)


class TestCredentialsConflictError:
    """Tests for CredentialsConflictError exception."""

    def test_is_value_error_subclass(self):
        """Test that CredentialsConflictError is a ValueError subclass."""
        assert issubclass(CredentialsConflictError, ValueError)

    def test_can_be_raised_and_caught(self):
        """Test that CredentialsConflictError can be raised and caught."""
        with pytest.raises(CredentialsConflictError):
            raise CredentialsConflictError("Test error")

    def test_message_preserved(self):
        """Test that error message is preserved."""
        try:
            raise CredentialsConflictError("Custom message")
        except CredentialsConflictError as e:
            assert str(e) == "Custom message"
