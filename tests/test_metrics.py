"""Tests for ecoflow/metrics/prometheus.py - Prometheus metrics wrapper."""

import pytest
from prometheus_client import REGISTRY, Counter, Gauge, Histogram

from ecoflow.metrics.prometheus import EcoflowMetric


@pytest.fixture(autouse=True)
def clear_metrics_pool():
    """Clear metrics pool before each test to avoid conflicts."""
    EcoflowMetric.METRICS_POOL.clear()
    # Unregister any test metrics from prometheus registry
    collectors = list(REGISTRY._collector_to_names.keys())
    for collector in collectors:
        try:
            REGISTRY.unregister(collector)
        except Exception:
            pass
    yield


class TestToSnakeCase:
    """Tests for _to_snake_case() method."""

    def test_camel_case_conversion(self):
        """Test converting camelCase to snake_case."""
        metric = EcoflowMetric(Gauge, "test", "Test", labelnames=EcoflowMetric.LABEL_NAMES)

        assert metric._to_snake_case("bmsMasterSoc") == "bms_master_soc"
        assert metric._to_snake_case("invInputWatts") == "inv_input_watts"
        assert metric._to_snake_case("singleValue") == "single_value"

    def test_already_snake_case(self):
        """Test that snake_case is preserved."""
        metric = EcoflowMetric(Gauge, "test2", "Test", labelnames=EcoflowMetric.LABEL_NAMES)

        assert metric._to_snake_case("already_snake") == "already_snake"
        assert metric._to_snake_case("simple") == "simple"

    def test_dots_replaced(self):
        """Test that dots are replaced with underscores."""
        metric = EcoflowMetric(Gauge, "test3", "Test", labelnames=EcoflowMetric.LABEL_NAMES)

        assert metric._to_snake_case("pd.watts") == "pd_watts"
        assert metric._to_snake_case("bms.master.soc") == "bms_master_soc"

    def test_brackets_replaced(self):
        """Test that brackets are replaced."""
        metric = EcoflowMetric(Gauge, "test4", "Test", labelnames=EcoflowMetric.LABEL_NAMES)

        # Note: brackets are first extracted as indexes, this tests remaining handling
        assert metric._to_snake_case("array[]") == "array"

    def test_multiple_underscores_collapsed(self):
        """Test that multiple underscores are collapsed."""
        metric = EcoflowMetric(Gauge, "test5", "Test", labelnames=EcoflowMetric.LABEL_NAMES)

        assert metric._to_snake_case("test__multiple___underscores") == "test_multiple_underscores"


class TestExtractIndexes:
    """Tests for _extract_indexes() method."""

    def test_single_index(self):
        """Test extracting single array index."""
        metric = EcoflowMetric(Gauge, "testidx1", "Test", labelnames=EcoflowMetric.LABEL_NAMES)

        name, labels = metric._extract_indexes("array[0]")

        assert name == "array"
        assert labels == {"index_0": "0"}

    def test_multiple_indexes(self):
        """Test extracting multiple array indexes."""
        metric = EcoflowMetric(Gauge, "testidx2", "Test", labelnames=EcoflowMetric.LABEL_NAMES)

        name, labels = metric._extract_indexes("matrix[1][2]")

        assert name == "matrix"
        assert labels == {"index_0": "1", "index_1": "2"}

    def test_no_indexes(self):
        """Test name without indexes."""
        metric = EcoflowMetric(Gauge, "testidx3", "Test", labelnames=EcoflowMetric.LABEL_NAMES)

        name, labels = metric._extract_indexes("simple_name")

        assert name == "simple_name"
        assert labels == {}

    def test_nested_index(self):
        """Test extracting index from nested path."""
        metric = EcoflowMetric(Gauge, "testidx4", "Test", labelnames=EcoflowMetric.LABEL_NAMES)

        name, labels = metric._extract_indexes("bms.cells[5].voltage")

        assert name == "bms.cells.voltage"
        assert labels == {"index_0": "5"}


class TestMetricCreation:
    """Tests for metric creation and pooling."""

    def test_create_gauge_metric(self):
        """Test creating a Gauge metric."""
        metric = EcoflowMetric(
            Gauge,
            "battery_soc",
            "Battery state of charge",
            labelnames=EcoflowMetric.LABEL_NAMES,
            device="TEST123",
            device_name="Test Device",
            product_name="Test Product",
            device_general_key="test_key",
        )

        assert "battery_soc" in EcoflowMetric.METRICS_POOL
        assert isinstance(metric.metric, Gauge)

    def test_create_counter_metric(self):
        """Test creating a Counter metric."""
        metric = EcoflowMetric(
            Counter,
            "test_counter_metric",
            "Test counter",
            labelnames=EcoflowMetric.LABEL_NAMES,
            device="TEST123",
            device_name="Test Device",
            product_name="Test Product",
            device_general_key="test_key",
        )

        assert "test_counter_metric" in EcoflowMetric.METRICS_POOL
        assert isinstance(metric.metric, Counter)

    def test_create_histogram_metric(self):
        """Test creating a Histogram metric."""
        metric = EcoflowMetric(
            Histogram,
            "request_duration",
            "Request duration in seconds",
            labelnames=EcoflowMetric.LABEL_NAMES,
            buckets=(0.1, 0.5, 1.0, 5.0),
            device="TEST123",
            device_name="Test Device",
            product_name="Test Product",
            device_general_key="test_key",
        )

        assert "request_duration" in EcoflowMetric.METRICS_POOL
        assert isinstance(metric.metric, Histogram)

    def test_create_histogram_metric_without_buckets(self):
        """Test creating a Histogram metric without custom buckets."""
        metric = EcoflowMetric(
            Histogram,
            "default_duration",
            "Duration with default buckets",
            labelnames=EcoflowMetric.LABEL_NAMES,
            device="TEST123",
            device_name="Test Device",
            product_name="Test Product",
            device_general_key="test_key",
        )

        assert "default_duration" in EcoflowMetric.METRICS_POOL
        assert isinstance(metric.metric, Histogram)

    def test_metric_pooling_reuses_existing(self):
        """Test that same metric name reuses existing metric."""
        metric1 = EcoflowMetric(
            Gauge,
            "shared_metric",
            "First description",
            labelnames=EcoflowMetric.LABEL_NAMES,
            device="DEV1",
            device_name="Device 1",
            product_name="Product",
            device_general_key="key",
        )

        metric2 = EcoflowMetric(
            Gauge,
            "shared_metric",
            "Second description",  # Different description, but same name
            labelnames=EcoflowMetric.LABEL_NAMES,
            device="DEV2",
            device_name="Device 2",
            product_name="Product",
            device_general_key="key",
        )

        assert metric1.metric is metric2.metric
        assert len(EcoflowMetric.METRICS_POOL) == 1

    def test_metric_with_index_labels(self):
        """Test creating metric with array index labels."""
        metric = EcoflowMetric(
            Gauge,
            "cells[0].voltage",
            "Cell voltage",
            labelnames=EcoflowMetric.LABEL_NAMES,
            device="TEST123",
            device_name="Test",
            product_name="Product",
            device_general_key="key",
        )

        assert "cells.voltage" in EcoflowMetric.METRICS_POOL
        assert metric.labels["index_0"] == "0"


class TestMetricOperations:
    """Tests for metric operations (set, inc, info, clear)."""

    def test_gauge_set(self):
        """Test setting gauge value."""
        metric = EcoflowMetric(
            Gauge,
            "test_gauge",
            "Test gauge",
            labelnames=EcoflowMetric.LABEL_NAMES,
            device="TEST",
            device_name="Test",
            product_name="Product",
            device_general_key="key",
        )

        # Should not raise
        metric.set(42.5)

    def test_counter_inc(self):
        """Test incrementing counter."""
        metric = EcoflowMetric(
            Counter,
            "test_counter",
            "Test counter",
            labelnames=EcoflowMetric.LABEL_NAMES,
            device="TEST",
            device_name="Test",
            product_name="Product",
            device_general_key="key",
        )

        # Should not raise
        metric.inc()
        metric.inc(5)

    def test_histogram_observe(self):
        """Test observing a value in histogram."""
        metric = EcoflowMetric(
            Histogram,
            "test_histogram",
            "Test histogram",
            labelnames=EcoflowMetric.LABEL_NAMES,
            buckets=(0.1, 0.5, 1.0),
            device="TEST",
            device_name="Test",
            product_name="Product",
            device_general_key="key",
        )

        # Should not raise
        metric.observe(0.25)
        metric.observe(0.75)

    def test_gauge_clear(self):
        """Test clearing gauge labels."""
        metric = EcoflowMetric(
            Gauge,
            "test_clear",
            "Test clear",
            labelnames=EcoflowMetric.LABEL_NAMES,
            device="TEST",
            device_name="Test",
            product_name="Product",
            device_general_key="key",
        )

        metric.set(100)
        # Should not raise
        metric.clear()


class TestLabelNames:
    """Tests for LABEL_NAMES constant."""

    def test_label_names_includes_all_required(self):
        """Test that LABEL_NAMES includes all required labels."""
        assert "device" in EcoflowMetric.LABEL_NAMES
        assert "device_name" in EcoflowMetric.LABEL_NAMES
        assert "product_name" in EcoflowMetric.LABEL_NAMES
        assert "device_general_key" in EcoflowMetric.LABEL_NAMES

    def test_label_names_order(self):
        """Test label names order for consistency."""
        expected = ["device", "device_name", "product_name", "device_general_key"]
        assert EcoflowMetric.LABEL_NAMES == expected
