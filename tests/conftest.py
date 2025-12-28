"""Common test fixtures and configuration."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def sample_devices_data():
    """Sample devices.json data for testing."""
    return [
        {
            "generalKey": "ecoflow_rapid_pro_charging_dock",
            "name": "RAPID Pro Desktop Charger",
            "sn": "P521"
        },
        {
            "generalKey": "ecoflow_ps_river_256",
            "name": "RIVER 2",
            "sn": "R601"
        },
        {
            "generalKey": "ecoflow_ps_delta_pro_3600",
            "name": "DELTA Pro",
            "sn": "DCA"
        },
        {
            "generalKey": "ecoflow_ps_river_max_512",
            "name": "RIVER 2 Max",
            "sn": "R611"
        }
    ]


@pytest.fixture
def temp_devices_file(sample_devices_data):
    """Create a temporary devices.json file."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(sample_devices_data, f)
        temp_path = f.name
    yield temp_path
    os.unlink(temp_path)


@pytest.fixture
def empty_devices_file():
    """Create a temporary empty devices.json file."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump([], f)
        temp_path = f.name
    yield temp_path
    os.unlink(temp_path)


@pytest.fixture
def invalid_json_file():
    """Create a temporary file with invalid JSON."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        f.write("{ invalid json }")
        temp_path = f.name
    yield temp_path
    os.unlink(temp_path)


@pytest.fixture
def clean_env():
    """Clean environment variables related to EcoFlow."""
    env_vars = [
        'ECOFLOW_DEVICE_GENERAL_KEY',
        'ECOFLOW_DEVICE_NAME',
        'ECOFLOW_PRODUCT_NAME',
        'ECOFLOW_DEVICES_JSON',
    ]
    original = {k: os.environ.get(k) for k in env_vars}
    for var in env_vars:
        if var in os.environ:
            del os.environ[var]
    yield
    for var, val in original.items():
        if val is not None:
            os.environ[var] = val
        elif var in os.environ:
            del os.environ[var]


@pytest.fixture
def mock_mqtt_client():
    """Mock MQTT client for testing."""
    with patch('paho.mqtt.client.Client') as mock:
        client = MagicMock()
        mock.return_value = client
        yield client


@pytest.fixture
def mock_requests_session():
    """Mock requests session for testing."""
    with patch('requests.Session') as mock:
        session = MagicMock()
        mock.return_value = session
        yield session
