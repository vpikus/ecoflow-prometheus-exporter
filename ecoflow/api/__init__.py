import os

from .base import EcoflowApiClient
from .models import DeviceInfo, EcoflowApiException
from .mqtt import MqttApiClient
from .rest import RestApiClient

__all__ = [
    "EcoflowApiClient",
    "DeviceInfo",
    "EcoflowApiException",
    "RestApiClient",
    "MqttApiClient",
    "CredentialsConflictError",
    "create_client",
]


class CredentialsConflictError(ValueError):
    """Raised when both REST and MQTT credentials are provided."""


def create_client(device_sn: str | None = None) -> EcoflowApiClient:
    """Create appropriate API client based on environment variables.

    Supports two authentication methods:
    - REST API: Developer tokens (ECOFLOW_ACCESS_KEY, ECOFLOW_SECRET_KEY)
    - MQTT: User credentials (ECOFLOW_ACCOUNT_USER, ECOFLOW_ACCOUNT_PASSWORD)

    Args:
        device_sn: Device serial number (required for MQTT, optional for REST).

    Environment variables:
        ECOFLOW_ACCESS_KEY: Developer access key (REST API)
        ECOFLOW_SECRET_KEY: Developer secret key (REST API)
        ECOFLOW_ACCOUNT_USER: EcoFlow account email (MQTT)
        ECOFLOW_ACCOUNT_PASSWORD: EcoFlow account password (MQTT)

    Returns:
        Configured EcoflowApiClient instance.

    Raises:
        CredentialsConflictError: If both REST and MQTT credentials are provided.
        ValueError: If no valid credentials are provided.
    """
    # REST API credentials
    access_key = os.getenv("ECOFLOW_ACCESS_KEY")
    secret_key = os.getenv("ECOFLOW_SECRET_KEY")
    has_rest_creds = bool(access_key and secret_key)

    # MQTT credentials
    account_user = os.getenv("ECOFLOW_ACCOUNT_USER")
    account_password = os.getenv("ECOFLOW_ACCOUNT_PASSWORD")
    has_mqtt_creds = bool(account_user and account_password)

    # Check for conflicting credentials
    if has_rest_creds and has_mqtt_creds:
        raise CredentialsConflictError(
            "Both REST API and MQTT credentials provided. "
            "Use either ECOFLOW_ACCESS_KEY/ECOFLOW_SECRET_KEY (REST) "
            "or ECOFLOW_ACCOUNT_USER/ECOFLOW_ACCOUNT_PASSWORD (MQTT), not both."
        )

    # Create REST API client
    if has_rest_creds:
        return RestApiClient(access_key, secret_key)

    # Create MQTT client
    if has_mqtt_creds:
        if not device_sn:
            raise ValueError(
                "ECOFLOW_DEVICE_SN is required when using MQTT authentication."
            )
        return MqttApiClient(account_user, account_password, device_sn)

    raise ValueError(
        "Missing credentials. Provide either:\n"
        "  - ECOFLOW_ACCESS_KEY and ECOFLOW_SECRET_KEY (REST API), or\n"
        "  - ECOFLOW_ACCOUNT_USER and ECOFLOW_ACCOUNT_PASSWORD (MQTT)"
    )
