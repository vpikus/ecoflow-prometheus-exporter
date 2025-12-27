from abc import ABC, abstractmethod
from typing import Any

from .models import DeviceInfo


class EcoflowApiClient(ABC):
    """Abstract interface for EcoFlow API backends.

    This interface defines the contract for interacting with EcoFlow services.
    Implementations may use REST API (developer tokens) or MQTT (user credentials).
    """

    @abstractmethod
    def connect(self) -> None:
        """Establish connection to EcoFlow service.

        For REST API: validates credentials by fetching device list.
        For MQTT: connects to broker and subscribes to device topics.

        Raises:
            EcoflowApiException: If connection fails.
        """
        pass

    @abstractmethod
    def get_devices(self) -> list[DeviceInfo]:
        """Get list of registered devices.

        Returns:
            List of DeviceInfo objects for all registered devices.

        Raises:
            EcoflowApiException: If request fails.
        """
        pass

    @abstractmethod
    def get_device(self, device_sn: str) -> DeviceInfo | None:
        """Get specific device info by serial number.

        Args:
            device_sn: Device serial number.

        Returns:
            DeviceInfo if found, None otherwise.

        Raises:
            EcoflowApiException: If request fails.
        """
        pass

    @abstractmethod
    def get_device_quota(self, device_sn: str) -> dict[str, Any]:
        """Get device statistics/metrics.

        Args:
            device_sn: Device serial number.

        Returns:
            Dictionary with device metrics (keys vary by device type).

        Raises:
            EcoflowApiException: If request fails.
        """
        pass

    def disconnect(self) -> None:
        """Disconnect from EcoFlow service and release resources.

        Default implementation does nothing (for stateless clients like REST).
        MQTT-based clients should override to stop timers and close connections.
        """
        pass
