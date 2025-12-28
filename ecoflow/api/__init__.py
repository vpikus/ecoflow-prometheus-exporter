import os

from .base import EcoflowApiClient
from .device import DeviceApiClient
from .models import DeviceInfo, EcoflowApiException
from .mqtt import MqttApiClient
from .rest import RestApiClient

__all__ = [
    "EcoflowApiClient",
    "DeviceInfo",
    "EcoflowApiException",
    "RestApiClient",
    "MqttApiClient",
    "DeviceApiClient",
    "CredentialsConflictError",
    "create_client",
]


class CredentialsConflictError(ValueError):
    """Raised when both REST and user credentials are provided."""


def create_client(device_sn: str | None = None) -> EcoflowApiClient:
    """Create appropriate API client based on environment variables.

    Supports three API backends:
    - REST API: Developer tokens, polling-based
    - MQTT: User credentials, push-based (passive)
    - Device API: User credentials, request/reply pattern (active)

    Args:
        device_sn: Device serial number (required for MQTT/Device API).

    Environment variables:
        ECOFLOW_ACCESS_KEY: Developer access key (REST API)
        ECOFLOW_SECRET_KEY: Developer secret key (REST API)
        ECOFLOW_ACCOUNT_USER: EcoFlow account email (MQTT/Device API)
        ECOFLOW_ACCOUNT_PASSWORD: EcoFlow account password (MQTT/Device API)
        ECOFLOW_API_TYPE: API type when using user credentials:
                          "mqtt" (default) or "device"

    Returns:
        Configured EcoflowApiClient instance.

    Raises:
        CredentialsConflictError: If both REST and user credentials are provided.
        ValueError: If no valid credentials or invalid API type.
    """
    # REST API credentials
    access_key = os.getenv("ECOFLOW_ACCESS_KEY")
    secret_key = os.getenv("ECOFLOW_SECRET_KEY")
    has_rest_creds = bool(access_key and secret_key)

    # User credentials (for MQTT or Device API)
    account_user = os.getenv("ECOFLOW_ACCOUNT_USER")
    account_password = os.getenv("ECOFLOW_ACCOUNT_PASSWORD")
    has_user_creds = bool(account_user and account_password)

    # API type switch (mqtt or device)
    api_type = os.getenv("ECOFLOW_API_TYPE", "mqtt").lower()

    # Check for conflicting credentials
    if has_rest_creds and has_user_creds:
        raise CredentialsConflictError(
            "Both REST API and user credentials provided. "
            "Use either ECOFLOW_ACCESS_KEY/ECOFLOW_SECRET_KEY (REST) "
            "or ECOFLOW_ACCOUNT_USER/ECOFLOW_ACCOUNT_PASSWORD (MQTT/Device), not both."
        )

    # Create REST API client
    if has_rest_creds:
        assert access_key is not None and secret_key is not None
        return RestApiClient(access_key, secret_key)

    # Create MQTT or Device API client
    if has_user_creds:
        assert account_user is not None and account_password is not None
        if not device_sn:
            raise ValueError("ECOFLOW_DEVICE_SN is required when using user credentials.")

        if api_type == "mqtt":
            return MqttApiClient(account_user, account_password, device_sn)
        elif api_type == "device":
            return DeviceApiClient(account_user, account_password, device_sn)
        else:
            raise ValueError(f"Invalid ECOFLOW_API_TYPE: '{api_type}'. Must be 'mqtt' or 'device'.")

    raise ValueError(
        "Missing credentials. Provide either:\n"
        "  - ECOFLOW_ACCESS_KEY and ECOFLOW_SECRET_KEY (REST API), or\n"
        "  - ECOFLOW_ACCOUNT_USER and ECOFLOW_ACCOUNT_PASSWORD (MQTT/Device API)"
    )
