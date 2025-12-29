# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Prometheus metrics exporter for EcoFlow devices. Supports three API backends:
- **REST API**: Developer tokens (access_key/secret_key) - polling-based
- **MQTT**: User credentials (email/password) - push-based, passive
- **Device API**: User credentials (email/password) - request/reply, active (works with all devices)

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run with REST API (developer tokens)
export ECOFLOW_DEVICE_SN="your-device-sn"
export ECOFLOW_ACCESS_KEY="your-access-key"
export ECOFLOW_SECRET_KEY="your-secret-key"
python ecoflow_prometheus.py

# Run with MQTT (user credentials, passive)
export ECOFLOW_DEVICE_SN="your-device-sn"
export ECOFLOW_ACCOUNT_USER="your-email"
export ECOFLOW_ACCOUNT_PASSWORD="your-password"
export ECOFLOW_API_TYPE="mqtt"  # optional, default
python ecoflow_prometheus.py

# Run with Device API (user credentials, active - recommended)
export ECOFLOW_DEVICE_SN="your-device-sn"
export ECOFLOW_ACCOUNT_USER="your-email"
export ECOFLOW_ACCOUNT_PASSWORD="your-password"
export ECOFLOW_API_TYPE="device"
python ecoflow_prometheus.py

# Docker
docker build -t ecoflow-exporter .
docker run -e ECOFLOW_DEVICE_SN=... -e ECOFLOW_ACCESS_KEY=... -e ECOFLOW_SECRET_KEY=... -p 9090:9090 ecoflow-exporter
```

## Architecture

```
ecoflow-prometheus-exporter/
├── ecoflow_prometheus.py      # Entry point
├── devices.json               # Device definitions (SN prefix -> generalKey)
└── ecoflow/
    ├── devices.py             # Device discovery and general key resolution
    ├── api/
    │   ├── __init__.py        # Factory: create_client()
    │   ├── base.py            # EcoflowApiClient (ABC)
    │   ├── models.py          # DeviceInfo, EcoflowApiException
    │   ├── rest.py            # RestApiClient (polling)
    │   ├── mqtt.py            # MqttApiClient (push-based)
    │   └── device.py          # DeviceApiClient (request/reply)
    ├── proto/
    │   ├── decoder.py         # Generic protobuf decoder
    │   ├── common.proto       # Common header messages
    │   ├── device_common.proto # Device status messages
    │   └── *_pb2.py           # Generated protobuf modules
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
   - Connection pooling with `requests.Session` for efficiency
   - Automatic retry with exponential backoff on transient failures
   - Device list cache with TTL for online status refresh (default 60s)
   - Endpoints: `api.ecoflow.com/iot-open/sign/device/...`

3. **MqttApiClient** (`ecoflow/api/mqtt.py`): Public MQTT implementation
   - Authenticates with email/password via REST, then connects to MQTT
   - Push-based: caches metrics as they arrive via MQTT
   - Broker: `mqtt.ecoflow.com:8883` (TLS)
   - Topic: `/app/device/property/{DEVICE_SN}`

4. **DeviceApiClient** (`ecoflow/api/device.py`): Private MQTT implementation
   - Same auth as MQTT, but uses request/reply pattern
   - Actively requests quota data (works with all EcoFlow devices)
   - Smart quota requests: skips if push data received recently (reduces server load)
   - Exponential backoff on reconnection failures
   - Topics:
     - `/app/device/property/{device_sn}` - receives push data
     - `/app/{user_id}/{device_sn}/thing/property/get` - sends requests
     - `/app/{user_id}/{device_sn}/thing/property/get_reply` - receives responses

5. **create_client()** (`ecoflow/api/__init__.py`): Factory function
   - Detects credentials from environment variables
   - Uses ECOFLOW_API_TYPE to choose between MQTT and Device API
   - Raises `CredentialsConflictError` if both REST and user credentials provided

6. **Device Discovery** (`ecoflow/devices.py`): Device type and name resolution
   - `get_device_general_key(device_sn)`: Resolves device general key from SN prefix
     - Priority: ECOFLOW_DEVICE_GENERAL_KEY env var > devices.json match > "unknown"
   - `build_device_name(device_sn, api_name)`: Builds friendly device name
     - Priority: ECOFLOW_DEVICE_NAME env var > API name (if differs from SN) > devices.json name + SN suffix > SN
     - If API name equals SN, builds: `<name from devices.json>-<last 4 chars of SN>`

## Environment Variables

### Required

| Variable | Description |
|----------|-------------|
| ECOFLOW_DEVICE_SN | Device serial number |

### Authentication (choose one set)

| Variable | Description |
|----------|-------------|
| ECOFLOW_ACCESS_KEY | REST API access key (developer tokens) |
| ECOFLOW_SECRET_KEY | REST API secret key (developer tokens) |
| ECOFLOW_ACCOUNT_USER | MQTT/Device API: EcoFlow account email |
| ECOFLOW_ACCOUNT_PASSWORD | MQTT/Device API: EcoFlow account password |

### General Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| ECOFLOW_API_TYPE | mqtt | API type: "mqtt" or "device" |
| ECOFLOW_DEVICE_NAME | - | Override device name in metrics |
| ECOFLOW_PRODUCT_NAME | - | Override product name in metrics |
| ECOFLOW_DEVICE_GENERAL_KEY | - | Override device general key (auto-detected from devices.json) |
| ECOFLOW_DEVICES_JSON | devices.json | Path to device definitions file |
| ECOFLOW_API_HOST | api.ecoflow.com | API host for authentication |
| EXPORTER_PORT | 9090 | Prometheus metrics port |
| METRICS_PREFIX | ecoflow | Metric name prefix |
| LOG_LEVEL | INFO | DEBUG/INFO/WARNING/ERROR |

### Timing Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| COLLECTING_INTERVAL | 10 | Seconds between Worker collections |
| QUOTA_REQUEST_INTERVAL | 30 | Device API: seconds between quota requests (skipped if push data received) |
| RETRY_TIMEOUT | 30 | Retry delay on Worker errors |
| ESTABLISH_ATTEMPTS | 5 | Max connection attempts on startup |

### Network Timeouts

| Variable | Default | Description |
|----------|---------|-------------|
| HTTP_TIMEOUT | 30 | HTTP request timeout in seconds |
| HTTP_RETRIES | 3 | Number of HTTP retry attempts (REST API) |
| HTTP_BACKOFF_FACTOR | 0.5 | Exponential backoff multiplier for retries |
| DEVICE_LIST_CACHE_TTL | 60 | REST API: seconds before device list cache expires (for online status refresh) |
| MQTT_TIMEOUT | 60 | MQTT idle timeout before reconnect |
| MQTT_KEEPALIVE | 60 | MQTT keepalive interval in seconds |
| IDLE_CHECK_INTERVAL | 30 | Seconds between idle connection checks |
| MAX_RECONNECT_DELAY | 300 | Maximum reconnect delay (exponential backoff cap) |

## API Comparison

| Feature | REST API | MQTT | Device API |
|---------|----------|------|------------|
| Auth | Developer tokens | User email/password | User email/password |
| Data flow | Polling | Push (passive) | Request/reply (active) |
| Device discovery | Yes | No | No |
| Device support | Limited | Limited | All devices |
| Latency | Poll interval | Instant | Request interval |
| Rate limits | API limits | None | None |
| Reliability | High | Depends on push | High (active requests) |

**Recommendation**: Use Device API (`ECOFLOW_API_TYPE=device`) for best compatibility with all EcoFlow devices.

## Protobuf Support

The exporter automatically handles both JSON and binary protobuf messages from EcoFlow devices. No configuration is required - the generic protobuf decoder works with all EcoFlow devices.

The decoder processes `DisplayPropertyUpload` messages (cmd_func=254, cmd_id=21) which contain device status and metrics. Other message types are logged for debugging purposes.

Proto definitions are in `ecoflow/proto/`:
- `common.proto`: Header message format for MQTT communication
- `device_common.proto`: Device status and metric message definitions
