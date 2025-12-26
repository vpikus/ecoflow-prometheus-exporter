from dataclasses import dataclass


class EcoflowApiException(Exception):
    """Base exception for EcoFlow API errors."""


@dataclass
class DeviceInfo:
    """Device information from EcoFlow API."""

    sn: str
    name: str
    product_name: str
    online: bool
