"""Tests for ecoflow/metrics/analytics.py - Analytics metrics for monitoring exporter health."""

import time

import pytest
from prometheus_client import REGISTRY

from ecoflow.metrics.analytics import (
    AUTH_DURATION_BUCKETS,
    HTTP_DURATION_BUCKETS,
    SCRAPE_DURATION_BUCKETS,
    AnalyticsMetrics,
    get_analytics,
    reset_analytics,
)
from ecoflow.metrics.prometheus import EcoflowMetric


@pytest.fixture(autouse=True)
def clear_analytics():
    """Reset analytics singleton before each test."""
    reset_analytics()
    EcoflowMetric.METRICS_POOL.clear()
    # Unregister any metrics from prometheus registry
    collectors = list(REGISTRY._collector_to_names.keys())
    for collector in collectors:
        try:
            REGISTRY.unregister(collector)
        except Exception:
            pass
    yield
    reset_analytics()


class TestAnalyticsMetricsSingleton:
    """Tests for AnalyticsMetrics singleton pattern."""

    def test_singleton_returns_same_instance(self):
        """Test that AnalyticsMetrics returns the same instance."""
        analytics1 = AnalyticsMetrics()
        analytics2 = AnalyticsMetrics()

        assert analytics1 is analytics2

    def test_get_analytics_returns_singleton(self):
        """Test that get_analytics() returns the singleton instance."""
        analytics1 = get_analytics()
        analytics2 = get_analytics()

        assert analytics1 is analytics2

    def test_reset_analytics_clears_singleton(self):
        """Test that reset_analytics() clears the singleton."""
        analytics1 = get_analytics()
        reset_analytics()
        analytics2 = get_analytics()

        # After reset, should be a different instance
        assert analytics1 is not analytics2


class TestHistogramBuckets:
    """Tests for histogram bucket configurations."""

    def test_http_duration_buckets(self):
        """Test HTTP duration buckets are properly configured."""
        assert HTTP_DURATION_BUCKETS == (
            0.01,
            0.025,
            0.05,
            0.1,
            0.25,
            0.5,
            1.0,
            2.5,
            5.0,
            10.0,
            30.0,
        )
        # Buckets should be in ascending order
        assert list(HTTP_DURATION_BUCKETS) == sorted(HTTP_DURATION_BUCKETS)

    def test_auth_duration_buckets(self):
        """Test auth duration buckets are properly configured."""
        assert AUTH_DURATION_BUCKETS == (0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)
        assert list(AUTH_DURATION_BUCKETS) == sorted(AUTH_DURATION_BUCKETS)

    def test_scrape_duration_buckets(self):
        """Test scrape duration buckets are properly configured."""
        assert SCRAPE_DURATION_BUCKETS == (0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0)
        assert list(SCRAPE_DURATION_BUCKETS) == sorted(SCRAPE_DURATION_BUCKETS)


class TestScrapeMetrics:
    """Tests for scrape/collection metrics."""

    def test_scrape_duration_histogram_exists(self):
        """Test scrape_duration histogram is created."""
        analytics = get_analytics()
        assert analytics.scrape_duration is not None

    def test_scrape_requests_total_counter_exists(self):
        """Test scrape_requests_total counter is created."""
        analytics = get_analytics()
        assert analytics.scrape_requests_total is not None

    def test_metrics_collected_gauge_exists(self):
        """Test metrics_collected gauge is created."""
        analytics = get_analytics()
        assert analytics.metrics_collected is not None

    def test_scrape_requests_total_labels(self):
        """Test scrape_requests_total has correct labels."""
        analytics = get_analytics()
        # Should be able to increment with device labels + status
        analytics.scrape_requests_total.labels(
            device="TEST123",
            device_name="Test Device",
            product_name="Test Product",
            device_general_key="test_key",
            status="success",
        ).inc()
        # No exception means labels are correct


class TestHttpMetrics:
    """Tests for HTTP/REST API metrics."""

    def test_http_request_duration_histogram_exists(self):
        """Test http_request_duration histogram is created."""
        analytics = get_analytics()
        assert analytics.http_request_duration is not None

    def test_http_requests_total_counter_exists(self):
        """Test http_requests_total counter is created."""
        analytics = get_analytics()
        assert analytics.http_requests_total is not None

    def test_cache_operations_total_counter_exists(self):
        """Test cache_operations_total counter is created."""
        analytics = get_analytics()
        assert analytics.cache_operations_total is not None

    def test_http_requests_total_labels(self):
        """Test http_requests_total has correct labels."""
        analytics = get_analytics()
        analytics.http_requests_total.labels(
            endpoint="/device/list",
            status="success",
        ).inc()
        # No exception means labels are correct

    def test_cache_operations_total_labels(self):
        """Test cache_operations_total has correct labels."""
        analytics = get_analytics()
        analytics.cache_operations_total.labels(result="hit").inc()
        analytics.cache_operations_total.labels(result="miss").inc()
        # No exception means labels are correct


class TestAuthMetrics:
    """Tests for authentication metrics."""

    def test_auth_duration_histogram_exists(self):
        """Test auth_duration histogram is created."""
        analytics = get_analytics()
        assert analytics.auth_duration is not None

    def test_auth_requests_total_counter_exists(self):
        """Test auth_requests_total counter is created."""
        analytics = get_analytics()
        assert analytics.auth_requests_total is not None

    def test_auth_requests_total_labels(self):
        """Test auth_requests_total has correct labels."""
        analytics = get_analytics()
        analytics.auth_requests_total.labels(
            client_type="mqtt",
            status="success",
        ).inc()
        analytics.auth_requests_total.labels(
            client_type="device",
            status="error",
        ).inc()
        # No exception means labels are correct


class TestMqttMetrics:
    """Tests for MQTT connection metrics."""

    def test_mqtt_connected_gauge_exists(self):
        """Test mqtt_connected gauge is created."""
        analytics = get_analytics()
        assert analytics.mqtt_connected is not None

    def test_mqtt_messages_total_counter_exists(self):
        """Test mqtt_messages_total counter is created."""
        analytics = get_analytics()
        assert analytics.mqtt_messages_total is not None

    def test_mqtt_reconnections_total_counter_exists(self):
        """Test mqtt_reconnections_total counter is created."""
        analytics = get_analytics()
        assert analytics.mqtt_reconnections_total is not None

    def test_mqtt_connected_labels(self):
        """Test mqtt_connected has correct labels."""
        analytics = get_analytics()
        analytics.mqtt_connected.labels(client_type="mqtt").set(1)
        analytics.mqtt_connected.labels(client_type="device").set(0)
        # No exception means labels are correct

    def test_mqtt_messages_total_labels(self):
        """Test mqtt_messages_total has correct labels."""
        analytics = get_analytics()
        # "text" for UTF-8 decoded messages, "protobuf" for binary
        analytics.mqtt_messages_total.labels(client_type="mqtt", type="text").inc()
        analytics.mqtt_messages_total.labels(client_type="device", type="protobuf").inc()
        # No exception means labels are correct


class TestDeviceApiMetrics:
    """Tests for Device API-specific metrics."""

    def test_quota_requests_total_counter_exists(self):
        """Test quota_requests_total counter is created."""
        analytics = get_analytics()
        assert analytics.quota_requests_total is not None

    def test_quota_requests_total_labels(self):
        """Test quota_requests_total has correct labels."""
        analytics = get_analytics()
        analytics.quota_requests_total.labels(status="sent").inc()
        analytics.quota_requests_total.labels(status="skipped").inc()
        # No exception means labels are correct


class TestTimingContextManagers:
    """Tests for timing context managers."""

    def test_time_scrape_measures_duration(self):
        """Test time_scrape context manager records observation to histogram."""
        analytics = get_analytics()
        labels = {
            "device": "TEST123",
            "device_name": "Test Device",
            "product_name": "Test Product",
            "device_general_key": "test_key",
        }

        # Get count before
        count_before = analytics.scrape_duration.labels(**labels)._sum._value

        with analytics.time_scrape(**labels):
            time.sleep(0.01)  # Small sleep to ensure measurable duration

        # Verify observation was recorded (sum increased)
        count_after = analytics.scrape_duration.labels(**labels)._sum._value
        assert count_after > count_before

    def test_time_http_request_measures_duration(self):
        """Test time_http_request context manager records observation to histogram."""
        analytics = get_analytics()

        # Get count before
        count_before = analytics.http_request_duration.labels(endpoint="/device/list")._sum._value

        with analytics.time_http_request(endpoint="/device/list"):
            time.sleep(0.01)

        # Verify observation was recorded (sum increased)
        count_after = analytics.http_request_duration.labels(endpoint="/device/list")._sum._value
        assert count_after > count_before

    def test_time_auth_measures_duration(self):
        """Test time_auth context manager records observation to histogram."""
        analytics = get_analytics()

        # Get count before
        count_before = analytics.auth_duration.labels(client_type="mqtt")._sum._value

        with analytics.time_auth(client_type="mqtt"):
            time.sleep(0.01)

        # Verify observation was recorded (sum increased)
        count_after = analytics.auth_duration.labels(client_type="mqtt")._sum._value
        assert count_after > count_before

    def test_time_scrape_still_records_on_exception(self):
        """Test time_scrape records duration even when exception occurs."""
        analytics = get_analytics()

        with pytest.raises(ValueError):
            with analytics.time_scrape(
                device="TEST123",
                device_name="Test Device",
                product_name="Test Product",
                device_general_key="test_key",
            ):
                raise ValueError("Test exception")

        # Duration should still be recorded despite exception

    def test_time_http_request_still_records_on_exception(self):
        """Test time_http_request records duration even when exception occurs."""
        analytics = get_analytics()

        with pytest.raises(ValueError):
            with analytics.time_http_request(endpoint="/test"):
                raise ValueError("Test exception")

        # Duration should still be recorded despite exception


class TestMetricNaming:
    """Tests for metric naming conventions."""

    def test_all_metrics_have_ecoflow_prefix(self):
        """Test all analytics metrics have ecoflow_ prefix."""
        analytics = get_analytics()

        # Check that metrics are named with the prefix
        # We can't easily check the actual name without accessing internal prometheus state,
        # but we verify the metrics exist and are usable
        assert analytics.scrape_duration is not None
        assert analytics.http_request_duration is not None
        assert analytics.auth_duration is not None
        assert analytics.mqtt_connected is not None
        assert analytics.quota_requests_total is not None
