# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Prometheus metrics exporter for EcoFlow devices. Supports two authentication methods:
- **REST API**: Developer tokens (access_key/secret_key) - polling-based
- **MQTT**: User credentials (email/password) - push-based, real-time

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run with REST API (developer tokens)
export ECOFLOW_DEVICE_SN="your-device-sn"
export ECOFLOW_ACCESS_KEY="your-access-key"
export ECOFLOW_SECRET_KEY="your-secret-key"
python ecoflow_prometheus.py

# Run with MQTT (user credentials)
export ECOFLOW_DEVICE_SN="your-device-sn"
export ECOFLOW_ACCOUNT_USER="your-email"
export ECOFLOW_ACCOUNT_PASSWORD="your-password"
python ecoflow_prometheus.py

# Docker
docker build -t ecoflow-exporter .
docker run -e ECOFLOW_DEVICE_SN=... -e ECOFLOW_ACCESS_KEY=... -e ECOFLOW_SECRET_KEY=... -p 9090:9090 ecoflow-exporter
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
    │   ├── rest.py            # RestApiClient (polling)
    │   └── mqtt.py            # MqttApiClient (push-based)
    ├── metrics/
    │   └── prometheus.py      # EcoflowMetric wrapper
    └── worker.py              # Worker (collection loop)
```

### Key Components

1. **EcoflowApiClient** (`ecoflow/api/base.py`): Abstract interface for API backends
   - `connect()`: Establish connection
   - `get_devices()`: List all devices
   - `get_device(sn)`: Get device by serial number
   - `get_device_quota(sn)`: Get device metrics

2. **RestApiClient** (`ecoflow/api/rest.py`): REST API implementation
   - Uses HMAC-SHA256 authentication with access_key/secret_key
   - Polling-based: fetches data on each `get_device_quota()` call
   - Endpoints: `api.ecoflow.com/iot-open/sign/device/...`

3. **MqttApiClient** (`ecoflow/api/mqtt.py`): MQTT implementation
   - Authenticates with email/password via REST, then connects to MQTT
   - Push-based: caches metrics as they arrive via MQTT
   - Broker: `mqtt.ecoflow.com:8883` (TLS)
   - Topic: `/app/device/property/{DEVICE_SN}`

4. **Worker** (`ecoflow/worker.py`): Polling loop that collects metrics
   - Depends on abstract `EcoflowApiClient`
   - Dynamically creates Prometheus metrics from device data

5. **create_client()** (`ecoflow/api/__init__.py`): Factory function
   - Detects credentials from environment variables
   - Raises `CredentialsConflictError` if both REST and MQTT credentials provided

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| ECOFLOW_DEVICE_SN | - | Device serial number (required) |
| ECOFLOW_ACCESS_KEY | - | REST API access key |
| ECOFLOW_SECRET_KEY | - | REST API secret key |
| ECOFLOW_ACCOUNT_USER | - | MQTT: EcoFlow account email |
| ECOFLOW_ACCOUNT_PASSWORD | - | MQTT: EcoFlow account password |
| ECOFLOW_DEVICE_NAME | - | Override device name in metrics |
| ECOFLOW_API_HOST | api.ecoflow.com | API host (both REST and MQTT auth) |
| EXPORTER_PORT | 9090 | Prometheus metrics port |
| COLLECTING_INTERVAL | 10 | Seconds between collections |
| RETRY_TIMEOUT | 30 | Retry delay on errors |
| ESTABLISH_ATTEMPTS | 5 | Max connection attempts |
| MQTT_TIMEOUT | 60 | MQTT idle timeout before reconnect |
| METRICS_PREFIX | ecoflow | Metric name prefix |
| LOG_LEVEL | INFO | DEBUG/INFO/WARNING/ERROR |

**Note**: Provide either REST credentials (ACCESS_KEY + SECRET_KEY) or MQTT credentials (ACCOUNT_USER + ACCOUNT_PASSWORD), not both.

## MQTT vs REST Comparison

| Feature | REST API | MQTT |
|---------|----------|------|
| Auth | Developer tokens | User email/password |
| Data flow | Polling | Push (real-time) |
| Device discovery | Yes | No (configured device only) |
| Latency | Higher (poll interval) | Lower (instant updates) |
| Rate limits | API rate limits apply | No rate limits |
