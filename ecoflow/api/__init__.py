import os

from .base import EcoflowApiClient
from .models import DeviceInfo, EcoflowApiException
from .rest import RestApiClient

__all__ = [
    "EcoflowApiClient",
    "DeviceInfo",
    "EcoflowApiException",
    "RestApiClient",
    "create_client",
]


def create_client() -> EcoflowApiClient:
    """Create appropriate API client based on environment variables.

    Currently supports REST API with developer tokens.
    Future: Will support MQTT with user credentials.

    Environment variables:
        ECOFLOW_ACCESS_KEY: Developer access key (REST API)
        ECOFLOW_SECRET_KEY: Developer secret key (REST API)

    Returns:
        Configured EcoflowApiClient instance.

    Raises:
        ValueError: If required credentials are not provided.
    """
    access_key = os.getenv("ECOFLOW_ACCESS_KEY")
    secret_key = os.getenv("ECOFLOW_SECRET_KEY")

    if access_key and secret_key:
        return RestApiClient(access_key, secret_key)

    # Future: Check for MQTT credentials
    # username = os.getenv("ECOFLOW_USERNAME")
    # password = os.getenv("ECOFLOW_PASSWORD")
    # if username and password:
    #     return MqttApiClient(username, password)

    raise ValueError(
        "Missing credentials. Set ECOFLOW_ACCESS_KEY and ECOFLOW_SECRET_KEY "
        "for REST API access."
    )
