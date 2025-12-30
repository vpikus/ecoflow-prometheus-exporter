"""Analytics metrics for EcoFlow Prometheus Exporter.

This module provides centralized analytics metrics for monitoring
the exporter's operational health and performance across all API backends.

Singleton Pattern:
    This module uses a dual-singleton pattern for robustness:
    1. Class-level: AnalyticsMetrics.__new__ ensures the class always returns
       the same instance, making direct instantiation safe.
    2. Module-level: get_analytics() provides a convenient accessor function
       with its own caching to avoid repeated __new__ overhead.

    The dual pattern ensures correct behavior regardless of how callers
    access the singleton (via class or function). Both are thread-safe
    via double-checked locking.

Lock Ordering:
    When acquiring multiple locks, always acquire in this order to prevent
    deadlocks: _analytics_lock -> AnalyticsMetrics._lock
    This ordering is enforced in reset_analytics().
"""

import threading
import time
from collections.abc import Generator
from contextlib import contextmanager

from prometheus_client import Counter, Gauge, Histogram

from .prometheus import METRICS_PREFIX

# Histogram bucket configurations
HTTP_DURATION_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)
AUTH_DURATION_BUCKETS = (0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)
SCRAPE_DURATION_BUCKETS = (0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0)

# Label definitions
DEVICE_LABELS = ["device", "device_name", "product_name", "device_general_key"]
CLIENT_TYPE_LABELS = ["client_type"]
HTTP_LABELS = ["endpoint"]
STATUS_LABELS = ["status"]


class AnalyticsMetrics:
    """Centralized analytics metrics registry.

    This singleton class provides all operational metrics for monitoring
    the EcoFlow Prometheus Exporter's health and performance. Thread-safe
    initialization is ensured via double-checked locking.

    Usage:
        metrics = AnalyticsMetrics()
        metrics.http_requests_total.labels(endpoint="/device/list", status="success").inc()
    """

    _instance: "AnalyticsMetrics | None" = None
    _lock = threading.Lock()

    def __new__(cls) -> "AnalyticsMetrics":
        if cls._instance is None:
            with cls._lock:
                # Double-checked locking for thread safety
                if cls._instance is None:
                    # Create and fully initialize before assigning to class variable
                    # to prevent other threads seeing a partially initialized instance
                    instance = super().__new__(cls)
                    instance._init_metrics()
                    cls._instance = instance
        return cls._instance

    def _init_metrics(self) -> None:
        """Initialize all analytics metrics."""
        # Scrape metrics (device labels + status)
        self.scrape_duration = Histogram(
            f"{METRICS_PREFIX}_scrape_duration_seconds",
            "Time spent collecting device data",
            labelnames=DEVICE_LABELS,
            buckets=SCRAPE_DURATION_BUCKETS,
        )
        self.scrape_requests_total = Counter(
            f"{METRICS_PREFIX}_scrape_requests_total",
            "Total number of scrape attempts",
            labelnames=DEVICE_LABELS + STATUS_LABELS,
        )
        self.metrics_collected = Gauge(
            f"{METRICS_PREFIX}_metrics_collected",
            "Number of metrics collected in last scrape",
            labelnames=DEVICE_LABELS,
        )

        # HTTP/REST API metrics
        self.http_request_duration = Histogram(
            f"{METRICS_PREFIX}_http_request_duration_seconds",
            "HTTP request latency in seconds",
            labelnames=HTTP_LABELS,
            buckets=HTTP_DURATION_BUCKETS,
        )
        self.http_requests_total = Counter(
            f"{METRICS_PREFIX}_http_requests_total",
            "Total number of HTTP requests",
            labelnames=HTTP_LABELS + STATUS_LABELS,
        )
        self.cache_operations_total = Counter(
            f"{METRICS_PREFIX}_cache_operations_total",
            "Device list cache operations",
            labelnames=["result"],  # hit or miss
        )

        # Authentication metrics (MQTT + Device API)
        self.auth_duration = Histogram(
            f"{METRICS_PREFIX}_auth_duration_seconds",
            "Authentication duration (login + credentials retrieval)",
            labelnames=CLIENT_TYPE_LABELS,
            buckets=AUTH_DURATION_BUCKETS,
        )
        self.auth_requests_total = Counter(
            f"{METRICS_PREFIX}_auth_requests_total",
            "Total number of authentication attempts",
            labelnames=CLIENT_TYPE_LABELS + STATUS_LABELS,
        )

        # MQTT connection metrics (shared by MQTT + Device API)
        self.mqtt_connected = Gauge(
            f"{METRICS_PREFIX}_mqtt_connected",
            "MQTT connection status (1=connected, 0=disconnected)",
            labelnames=CLIENT_TYPE_LABELS,
        )
        self.mqtt_messages_total = Counter(
            f"{METRICS_PREFIX}_mqtt_messages_total",
            "Total number of MQTT messages received",
            labelnames=CLIENT_TYPE_LABELS + ["type"],  # text or protobuf (encoding type)
        )
        self.mqtt_reconnections_total = Counter(
            f"{METRICS_PREFIX}_mqtt_reconnections_total",
            "Total number of MQTT reconnection attempts",
            labelnames=CLIENT_TYPE_LABELS,
        )
        self.mqtt_message_errors_total = Counter(
            f"{METRICS_PREFIX}_mqtt_message_errors_total",
            "Total number of MQTT message processing errors",
            labelnames=CLIENT_TYPE_LABELS,
        )

        # Device API specific metrics
        self.quota_requests_total = Counter(
            f"{METRICS_PREFIX}_quota_requests_total",
            "Total number of quota request operations",
            labelnames=STATUS_LABELS,  # sent or skipped
        )

    @contextmanager
    def time_scrape(
        self,
        device: str,
        device_name: str,
        product_name: str,
        device_general_key: str,
    ) -> Generator[None, None, None]:
        """Context manager to time scrape duration.

        Args:
            device: Device serial number
            device_name: Device name
            product_name: Product name
            device_general_key: Device general key

        Yields:
            None

        Example:
            with metrics.time_scrape("SN123", "MyDevice", "Delta Pro", "deltaProUltra"):
                # collect data
        """
        labels = {
            "device": device,
            "device_name": device_name,
            "product_name": product_name,
            "device_general_key": device_general_key,
        }
        start_time = time.perf_counter()
        try:
            yield
        finally:
            duration = time.perf_counter() - start_time
            self.scrape_duration.labels(**labels).observe(duration)

    @contextmanager
    def time_http_request(self, endpoint: str) -> Generator[None, None, None]:
        """Context manager to time HTTP request duration.

        Args:
            endpoint: API endpoint being called

        Yields:
            None

        Example:
            with metrics.time_http_request("/device/list"):
                response = session.get(url)
        """
        start_time = time.perf_counter()
        try:
            yield
        finally:
            duration = time.perf_counter() - start_time
            self.http_request_duration.labels(endpoint=endpoint).observe(duration)

    @contextmanager
    def time_auth(self, client_type: str) -> Generator[None, None, None]:
        """Context manager to time authentication duration.

        Args:
            client_type: Type of client (mqtt or device)

        Yields:
            None

        Example:
            with metrics.time_auth("mqtt"):
                auth.authorize()
        """
        start_time = time.perf_counter()
        try:
            yield
        finally:
            duration = time.perf_counter() - start_time
            self.auth_duration.labels(client_type=client_type).observe(duration)


# Module-level singleton instance
_analytics: AnalyticsMetrics | None = None
_analytics_lock = threading.Lock()


def get_analytics() -> AnalyticsMetrics:
    """Get the singleton AnalyticsMetrics instance.

    Thread-safe via double-checked locking.

    Returns:
        The singleton AnalyticsMetrics instance.
    """
    global _analytics
    if _analytics is None:
        with _analytics_lock:
            if _analytics is None:
                _analytics = AnalyticsMetrics()
    return _analytics


def reset_analytics() -> None:
    """Reset the analytics singleton (for testing purposes).

    This function unregisters all analytics metrics from the Prometheus
    registry and resets the singleton instance. It should only be used
    in tests.

    Thread Safety:
        Acquires locks in order: _analytics_lock -> AnalyticsMetrics._lock
        This ordering must be maintained to prevent deadlocks with other
        code paths that may acquire these locks.
    """
    from prometheus_client import REGISTRY

    global _analytics
    with _analytics_lock:
        with AnalyticsMetrics._lock:
            if _analytics is not None:
                # Unregister all metrics from the registry
                metrics_to_unregister = [
                    _analytics.scrape_duration,
                    _analytics.scrape_requests_total,
                    _analytics.metrics_collected,
                    _analytics.http_request_duration,
                    _analytics.http_requests_total,
                    _analytics.cache_operations_total,
                    _analytics.auth_duration,
                    _analytics.auth_requests_total,
                    _analytics.mqtt_connected,
                    _analytics.mqtt_messages_total,
                    _analytics.mqtt_reconnections_total,
                    _analytics.mqtt_message_errors_total,
                    _analytics.quota_requests_total,
                ]
                for metric in metrics_to_unregister:
                    try:
                        REGISTRY.unregister(metric)
                    except Exception:
                        pass
            # Atomically reset both references while holding both locks
            _analytics = None
            AnalyticsMetrics._instance = None
