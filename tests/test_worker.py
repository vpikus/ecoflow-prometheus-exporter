"""Tests for ecoflow/worker.py - Main worker for metrics collection."""

from unittest.mock import MagicMock, patch

import pytest
from prometheus_client import REGISTRY

from ecoflow.api.models import DeviceInfo, EcoflowApiException
from ecoflow.metrics.prometheus import EcoflowMetric
from ecoflow.worker import Worker


@pytest.fixture(autouse=True)
def clear_metrics():
    """Clear metrics pool before each test."""
    EcoflowMetric.METRICS_POOL.clear()
    collectors = list(REGISTRY._collector_to_names.keys())
    for collector in collectors:
        try:
            REGISTRY.unregister(collector)
        except Exception:
            pass
    yield


class TestWorkerInit:
    """Tests for Worker initialization."""

    def test_init(self):
        """Test worker initialization."""
        client = MagicMock()
        worker = Worker(
            client=client,
            device_sn="DEV123",
            device_name="Test Device",
            product_name="Delta Pro",
            device_general_key="test_key",
        )

        assert worker.device_sn == "DEV123"
        assert worker.device_name == "Test Device"
        assert worker.product_name == "Delta Pro"
        assert worker.device_general_key == "test_key"
        assert worker.labels == {
            "device": "DEV123",
            "device_name": "Test Device",
            "product_name": "Delta Pro",
            "device_general_key": "test_key",
        }

    def test_init_creates_online_metric(self):
        """Test that online metric is created on init."""
        client = MagicMock()
        worker = Worker(
            client=client,
            device_sn="DEV123",
            device_name="Test",
            product_name="Product",
            device_general_key="key",
        )

        assert worker.online is not None
        assert "online" in EcoflowMetric.METRICS_POOL

    def test_init_creates_connection_errors_metric(self):
        """Test that connection_errors metric is created on init."""
        client = MagicMock()
        worker = Worker(
            client=client,
            device_sn="DEV123",
            device_name="Test",
            product_name="Product",
            device_general_key="key",
        )

        assert worker.connection_errors is not None
        assert "connection_errors" in EcoflowMetric.METRICS_POOL


class TestCollectData:
    """Tests for _collect_data() method."""

    @pytest.fixture
    def worker(self):
        """Create worker for testing."""
        client = MagicMock()
        return Worker(
            client=client,
            device_sn="DEV123",
            device_name="Test",
            product_name="Product",
            device_general_key="key",
        )

    def test_collect_data_device_not_found(self, worker):
        """Test data collection when device not found."""
        worker.client.get_device.return_value = None

        worker._collect_data()

        worker.client.get_device_quota.assert_not_called()

    def test_collect_data_device_offline(self, worker):
        """Test data collection when device is offline."""
        device = DeviceInfo(sn="DEV123", name="Test", product_name="Product", online=False)
        worker.client.get_device.return_value = device

        with patch.object(worker, "_reset_metrics") as mock_reset:
            worker._collect_data()
            mock_reset.assert_called_once()

        worker.client.get_device_quota.assert_not_called()

    def test_collect_data_device_online(self, worker):
        """Test data collection when device is online."""
        device = DeviceInfo(sn="DEV123", name="Test", product_name="Product", online=True)
        worker.client.get_device.return_value = device
        worker.client.get_device_quota.return_value = {"soc": 85}

        with patch.object(worker, "_update_metrics") as mock_update:
            worker._collect_data()
            mock_update.assert_called_once_with({"soc": 85})


class TestUpdateDeviceStatus:
    """Tests for _update_device_status() method."""

    @pytest.fixture
    def worker(self):
        """Create worker for testing."""
        client = MagicMock()
        return Worker(
            client=client,
            device_sn="DEV123",
            device_name="Test",
            product_name="Product",
            device_general_key="key",
        )

    def test_update_device_status_online(self, worker):
        """Test updating status when device is online."""
        device = DeviceInfo(sn="DEV123", name="Test", product_name="Product", online=True)

        with patch.object(worker.online, "set") as mock_set:
            worker._update_device_status(device)
            mock_set.assert_called_once_with(1)

    def test_update_device_status_offline(self, worker):
        """Test updating status when device is offline."""
        device = DeviceInfo(sn="DEV123", name="Test", product_name="Product", online=False)

        with patch.object(worker.online, "set") as mock_set:
            worker._update_device_status(device)
            mock_set.assert_called_once_with(0)


class TestUpdateMetric:
    """Tests for _update_metric() method."""

    @pytest.fixture
    def worker(self):
        """Create worker for testing."""
        client = MagicMock()
        return Worker(
            client=client,
            device_sn="DEV123",
            device_name="Test",
            product_name="Product",
            device_general_key="key",
        )

    def test_update_metric_integer(self, worker):
        """Test updating metric with integer value."""
        worker._update_metric("soc", 85)

        assert "soc" in worker.metrics

    def test_update_metric_float(self, worker):
        """Test updating metric with float value."""
        worker._update_metric("voltage", 12.5)

        assert "voltage" in worker.metrics

    def test_update_metric_reuses_existing(self, worker):
        """Test that existing metric is reused."""
        worker._update_metric("soc", 85)
        metric1 = worker.metrics["soc"]

        worker._update_metric("soc", 90)
        metric2 = worker.metrics["soc"]

        assert metric1 is metric2

    def test_update_metric_list(self, worker):
        """Test updating metric with list value."""
        worker._update_metric("cells", [3.7, 3.8, 3.6])

        assert "cells[0]" in worker.metrics
        assert "cells[1]" in worker.metrics
        assert "cells[2]" in worker.metrics

    def test_update_metric_dict(self, worker):
        """Test updating metric with dict value."""
        worker._update_metric("bms", {"soc": 85, "temp": 25})

        assert "bms.soc" in worker.metrics
        assert "bms.temp" in worker.metrics

    def test_update_metric_nested(self, worker):
        """Test updating metric with nested structure."""
        worker._update_metric("data", {"bms": {"cells": [3.7, 3.8]}})

        assert "data.bms.cells[0]" in worker.metrics
        assert "data.bms.cells[1]" in worker.metrics

    def test_update_metric_string_skipped(self, worker):
        """Test that string values are skipped."""
        worker._update_metric("status", "active")

        assert "status" not in worker.metrics

    def test_update_metric_none_skipped(self, worker):
        """Test that None values are skipped."""
        worker._update_metric("value", None)

        assert "value" not in worker.metrics

    def test_update_metric_bool_as_int(self, worker):
        """Test that boolean values are treated as integers."""
        # In Python, bool is a subclass of int
        worker._update_metric("enabled", True)

        assert "enabled" in worker.metrics


class TestUpdateMetrics:
    """Tests for _update_metrics() method."""

    @pytest.fixture
    def worker(self):
        """Create worker for testing."""
        client = MagicMock()
        return Worker(
            client=client,
            device_sn="DEV123",
            device_name="Test",
            product_name="Product",
            device_general_key="key",
        )

    def test_update_metrics_multiple(self, worker):
        """Test updating multiple metrics."""
        statistics = {
            "soc": 85,
            "wattsIn": 120,
            "wattsOut": 450,
        }

        worker._update_metrics(statistics)

        assert "soc" in worker.metrics
        assert "wattsIn" in worker.metrics
        assert "wattsOut" in worker.metrics

    def test_update_metrics_empty(self, worker):
        """Test updating with empty statistics."""
        worker._update_metrics({})

        assert len(worker.metrics) == 0

    def test_update_metrics_mixed_types(self, worker):
        """Test updating with mixed value types."""
        statistics = {
            "soc": 85,
            "status": "active",  # Should be skipped
            "bms": {"temp": 25},
        }

        worker._update_metrics(statistics)

        assert "soc" in worker.metrics
        assert "status" not in worker.metrics
        assert "bms.temp" in worker.metrics


class TestResetMetrics:
    """Tests for _reset_metrics() method."""

    @pytest.fixture
    def worker(self):
        """Create worker for testing."""
        client = MagicMock()
        return Worker(
            client=client,
            device_sn="DEV123",
            device_name="Test",
            product_name="Product",
            device_general_key="key",
        )

    def test_reset_metrics_clears_all(self, worker):
        """Test that all metrics are cleared."""
        # Create some metrics
        worker._update_metric("soc", 85)
        worker._update_metric("watts", 100)

        # Mock clear method
        for metric in worker.metrics.values():
            metric.clear = MagicMock()

        worker._reset_metrics()

        for metric in worker.metrics.values():
            metric.clear.assert_called_once()

    def test_reset_metrics_empty(self, worker):
        """Test resetting when no metrics exist."""
        # Should not raise
        worker._reset_metrics()


class TestRunLoop:
    """Tests for run() method."""

    @pytest.fixture
    def worker(self):
        """Create worker for testing."""
        client = MagicMock()
        return Worker(
            client=client,
            device_sn="DEV123",
            device_name="Test",
            product_name="Product",
            device_general_key="key",
        )

    def test_run_handles_api_exception(self, worker):
        """Test that run handles API exceptions."""
        call_count = 0

        def side_effect():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise EcoflowApiException("Test error")
            raise KeyboardInterrupt  # Stop the loop

        with patch.object(worker, "_collect_data", side_effect=side_effect):
            with patch("time.sleep"):
                with patch.object(worker.connection_errors, "inc") as mock_inc:
                    try:
                        worker.run()
                    except KeyboardInterrupt:
                        pass

                    mock_inc.assert_called_once()

    def test_run_collects_data(self, worker):
        """Test that run calls collect_data."""
        call_count = 0

        def side_effect():
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise KeyboardInterrupt

        with patch.object(worker, "_collect_data", side_effect=side_effect):
            with patch("time.sleep"):
                try:
                    worker.run()
                except KeyboardInterrupt:
                    pass

        assert call_count == 2
