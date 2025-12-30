import logging as log
import os
import time
from typing import Any

from prometheus_client import Gauge

from .api import DeviceInfo, EcoflowApiClient
from .metrics import EcoflowMetric, get_analytics

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
            **self.labels,  # type: ignore[arg-type]
        )
        self.metrics: dict[str, EcoflowMetric] = {}
        self._analytics = get_analytics()

    def run(self) -> None:
        """Main loop that collects data at regular intervals."""
        while True:
            try:
                self._collect_data()
                log.debug("Sleeping for %s seconds", COLLECTING_INTERVAL)
                time.sleep(COLLECTING_INTERVAL)
            except Exception as e:
                # Error already logged in _collect_data(), just handle retry timing
                log.info("Retrying in %s seconds after %s", RETRY_TIMEOUT, type(e).__name__)
                time.sleep(RETRY_TIMEOUT)

    def _collect_data(self) -> None:
        """Collect device data and update metrics.

        All errors are handled internally with appropriate metrics tracking.
        This ensures consistent timing and status recording regardless of outcome.
        """
        log.debug("Collecting data for device %s", self.device_sn)

        with self._analytics.time_scrape(**self.labels):
            try:
                device = self.client.get_device(self.device_sn)
                if not device:
                    log.warning("Device %s not found", self.device_sn)
                    self.online.set(0)  # Clear online status when device not found
                    self._analytics.scrape_requests_total.labels(
                        **self.labels, status="not_found"
                    ).inc()
                    self._analytics.metrics_collected.labels(**self.labels).set(0)
                    return

                self._update_device_status(device)

                if not device.online:
                    log.info("Device %s is offline", self.device_sn)
                    self._reset_metrics()
                    self._analytics.scrape_requests_total.labels(
                        **self.labels, status="offline"
                    ).inc()
                    self._analytics.metrics_collected.labels(**self.labels).set(0)
                    return

                statistics = self.client.get_device_quota(self.device_sn)
                metrics_count = self._update_metrics(statistics)

                # Track successful scrape
                self._analytics.scrape_requests_total.labels(**self.labels, status="success").inc()
                self._analytics.metrics_collected.labels(**self.labels).set(metrics_count)

            except Exception:
                # Track all errors (API exceptions, type errors, etc.)
                log.exception("Error collecting data for device %s", self.device_sn)
                self.online.set(0)  # Mark device as offline on error
                self._reset_metrics()  # Clear stale metric values
                self._analytics.scrape_requests_total.labels(**self.labels, status="error").inc()
                self._analytics.metrics_collected.labels(**self.labels).set(0)
                raise  # Re-raise so run() can handle retry timing

    def _update_device_status(self, device: DeviceInfo) -> None:
        """Update online status metric."""
        self.online.set(1 if device.online else 0)

    def _update_metrics(self, statistics: dict[str, Any]) -> int:
        """Update all metrics from device statistics.

        Returns:
            Number of metrics actually updated in this call.
        """
        count = 0
        for key, value in statistics.items():
            count += self._update_metric(key, value)
        return count

    def _update_metric(self, key: str, value: Any) -> int:
        """Update single metric, handling nested structures.

        Returns:
            Number of metrics updated (0 or 1 for scalars, sum for nested).
        """
        if isinstance(value, (int, float)):
            if key not in self.metrics:
                self.metrics[key] = EcoflowMetric(
                    Gauge,
                    key,
                    f"Device metric {key}",
                    labelnames=EcoflowMetric.LABEL_NAMES,
                    **self.labels,  # type: ignore[arg-type]
                )
            self.metrics[key].set(value)
            return 1
        elif isinstance(value, list):
            count = 0
            for i, sub_value in enumerate(value):
                count += self._update_metric(f"{key}[{i}]", sub_value)
            return count
        elif isinstance(value, dict):
            count = 0
            for sub_key, sub_value in value.items():
                count += self._update_metric(f"{key}.{sub_key}", sub_value)
            return count
        else:
            log.debug("Skipping metric '%s' with value '%s'", key, value)
            return 0

    def _reset_metrics(self) -> None:
        """Clear all metric values when device goes offline."""
        for metric in self.metrics.values():
            metric.clear()
