import logging as log
import os
import time
from typing import Any

from prometheus_client import Counter, Gauge

from .api import DeviceInfo, EcoflowApiClient, EcoflowApiException
from .metrics import EcoflowMetric

COLLECTING_INTERVAL = int(os.getenv("COLLECTING_INTERVAL", "10"))
RETRY_TIMEOUT = int(os.getenv("RETRY_TIMEOUT", "30"))


class Worker:
    """Main worker that collects metrics from EcoFlow API and exports to Prometheus."""

    def __init__(
        self,
        client: EcoflowApiClient,
        device_sn: str,
        device_name: str,
        product_name: str,
        device_general_key: str,
    ):
        self.client = client
        self.device_sn = device_sn
        self.device_name = device_name
        self.product_name = product_name
        self.device_general_key = device_general_key

        self.labels = {
            "device": device_sn,
            "device_name": device_name,
            "product_name": product_name,
            "device_general_key": device_general_key,
        }

        self.online = EcoflowMetric(
            Gauge,
            "online",
            "1 if device is online",
            labelnames=EcoflowMetric.LABEL_NAMES,
            **self.labels,
        )
        self.metrics: dict[str, EcoflowMetric] = {}
        self.connection_errors = EcoflowMetric(
            Counter,
            "connection_errors",
            "Connection errors count to Ecoflow IOT API",
            labelnames=EcoflowMetric.LABEL_NAMES,
            **self.labels,
        )

    def run(self) -> None:
        """Main loop that collects data at regular intervals."""
        while True:
            try:
                self._collect_data()
                log.debug("Sleeping for %s seconds", COLLECTING_INTERVAL)
                time.sleep(COLLECTING_INTERVAL)
            except EcoflowApiException as e:
                log.error("API error: %s", e)
                log.error("Retrying in %s seconds", RETRY_TIMEOUT)
                self.connection_errors.inc()
                time.sleep(RETRY_TIMEOUT)

    def _collect_data(self) -> None:
        """Collect device data and update metrics."""
        log.debug("Collecting data for device %s", self.device_sn)

        device = self.client.get_device(self.device_sn)
        if not device:
            log.warning("Device %s not found", self.device_sn)
            return

        self._update_device_status(device)

        if not device.online:
            log.info("Device %s is offline", self.device_sn)
            self._reset_metrics()
            return

        statistics = self.client.get_device_quota(self.device_sn)
        self._update_metrics(statistics)

    def _update_device_status(self, device: DeviceInfo) -> None:
        """Update online status metric."""
        self.online.set(1 if device.online else 0)

    def _update_metrics(self, statistics: dict[str, Any]) -> None:
        """Update all metrics from device statistics."""
        for key, value in statistics.items():
            self._update_metric(key, value)

    def _update_metric(self, key: str, value: Any) -> None:
        """Update single metric, handling nested structures."""
        if isinstance(value, (int, float)):
            if key not in self.metrics:
                self.metrics[key] = EcoflowMetric(
                    Gauge,
                    key,
                    f"Device metric {key}",
                    labelnames=EcoflowMetric.LABEL_NAMES,
                    **self.labels,
                )
            self.metrics[key].set(value)
        elif isinstance(value, list):
            for i, sub_value in enumerate(value):
                self._update_metric(f"{key}[{i}]", sub_value)
        elif isinstance(value, dict):
            for sub_key, sub_value in value.items():
                self._update_metric(f"{key}.{sub_key}", sub_value)
        else:
            log.debug("Skipping metric '%s' with value '%s'", key, value)

    def _reset_metrics(self) -> None:
        """Clear all metric values when device goes offline."""
        for metric in self.metrics.values():
            metric.clear()
