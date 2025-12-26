# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Prometheus metrics exporter for EcoFlow devices. Supports REST API with developer tokens (access_key/secret_key). Architecture designed to support future MQTT backend with user credentials.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run locally
export ECOFLOW_DEVICE_SN="your-device-sn"
export ECOFLOW_ACCESS_KEY="your-access-key"
export ECOFLOW_SECRET_KEY="your-secret-key"
python ecoflow_prometheus.py

# Run with Docker
docker build -t ecoflow-exporter .
docker run -e ECOFLOW_DEVICE_SN=... -e ECOFLOW_ACCESS_KEY=... -e ECOFLOW_SECRET_KEY=... -p 9090:9090 ecoflow-exporter

# Development with docker-compose
cd dev && docker-compose up
```

## Architecture

```
ecoflow-prometheus-exporter/
├── ecoflow_prometheus.py      # Entry point
└── ecoflow/
    ├── api/
    │   ├── __init__.py        # Factory: create_client()
    │   ├── base.py            # EcoflowApiClient (ABC)
    │   ├── models.py          # DeviceInfo, EcoflowApiException
    │   └── rest.py            # RestApiClient implementation
    ├── metrics/
    │   └── prometheus.py      # EcoflowMetric wrapper
    └── worker.py              # Worker (polling loop)
```

### Key Components

1. **EcoflowApiClient** (`ecoflow/api/base.py`): Abstract interface for API backends
   - `connect()`: Establish connection
   - `get_devices()`: List all devices
   - `get_device(sn)`: Get device by serial number
   - `get_device_quota(sn)`: Get device metrics

2. **RestApiClient** (`ecoflow/api/rest.py`): REST API implementation
   - Uses HMAC-SHA256 authentication with access_key/secret_key
   - Endpoints: `api.ecoflow.com/iot-open/sign/device/...`

3. **Worker** (`ecoflow/worker.py`): Polling loop that collects metrics
   - Depends on abstract `EcoflowApiClient`
   - Dynamically creates Prometheus metrics from device data

4. **EcoflowMetric** (`ecoflow/metrics/prometheus.py`): Prometheus metric wrapper
   - Converts camelCase to snake_case
   - Handles nested structures and array indices as labels

### Adding MQTT Support (Future)

Create `ecoflow/api/mqtt.py` implementing `EcoflowApiClient`:
- Authenticate with email/password via `api.ecoflow.com/auth/login`
- Connect to `mqtt.ecoflow.com:8883` (TLS)
- Subscribe to `/app/device/property/{DEVICE_SN}`
- Cache device metrics from MQTT messages
- Update `create_client()` factory to detect MQTT credentials

## Environment Variables

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| ECOFLOW_DEVICE_SN | - | Yes | Device serial number |
| ECOFLOW_ACCESS_KEY | - | Yes* | REST API access key |
| ECOFLOW_SECRET_KEY | - | Yes* | REST API secret key |
| EXPORTER_PORT | 9090 | No | Prometheus metrics port |
| COLLECTING_INTERVAL | 10 | No | Seconds between collections |
| RETRY_TIMEOUT | 30 | No | Retry delay on errors |
| ESTABLISH_ATTEMPTS | 5 | No | Max connection attempts |
| METRICS_PREFIX | ecoflow | No | Metric name prefix |
| LOG_LEVEL | INFO | No | DEBUG/INFO/WARNING/ERROR |
| ECOFLOW_DEVICE_NAME | - | No | Override device name |

*Required for REST API. Future MQTT will use ECOFLOW_USERNAME/PASSWORD instead.
