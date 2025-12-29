# EcoFlow Prometheus Exporter

Prometheus metrics exporter for EcoFlow portable power stations and solar generators.

> ⚠️ **Disclaimer:** This is a personal, open-source project created for learning and experimentation. It is not intended to support the full range of EcoFlow features.
> The application works in read-only mode and does not send, modify, or push any configuration or data to the EcoFlow API.
> This project is not affiliated with or endorsed by EcoFlow in any way. It is provided as-is, with no guarantees or warranties.

## Features

- Exports device metrics to Prometheus format
- Supports three API backends:
  - **REST API** - Developer tokens (polling-based)
  - **MQTT** - User credentials (push-based, passive)
  - **Device API** - User credentials (request/reply, works with all devices) - **Recommended**
- Automatic retry with exponential backoff
- Connection pooling for REST API
- Supports both JSON and Protobuf message formats
- Multi-platform Docker images (amd64, arm64)

## Requirements

- Python 3.12+
- EcoFlow account with registered devices
- Either:
  - Developer API credentials (accessKey/secretKey) from [EcoFlow IoT Platform](https://developer.ecoflow.com/)
  - Or EcoFlow app account credentials (email/password)

## Installation

### Using pip

```bash
pip install -r requirements.txt
```

For development (includes testing and linting tools):

```bash
pip install -r requirements-dev.txt
```

### Using Docker

Pre-built images are available from GitHub Container Registry:

```bash
docker pull ghcr.io/vpikus/ecoflow-prometheus-exporter:latest
```

Or build locally:

```bash
docker build -t ecoflow-exporter .
```

## Quick Start

### Option 1: Device API (Recommended)

Works with all EcoFlow devices using your app account:

```bash
export ECOFLOW_DEVICE_SN="YOUR_DEVICE_SERIAL_NUMBER"
export ECOFLOW_ACCOUNT_USER="your-email@example.com"
export ECOFLOW_ACCOUNT_PASSWORD="your-password"
export ECOFLOW_API_TYPE="device"

python ecoflow_prometheus.py
```

### Option 2: MQTT API (Passive)

Push-based data collection using your app account:

```bash
export ECOFLOW_DEVICE_SN="YOUR_DEVICE_SERIAL_NUMBER"
export ECOFLOW_ACCOUNT_USER="your-email@example.com"
export ECOFLOW_ACCOUNT_PASSWORD="your-password"
export ECOFLOW_API_TYPE="mqtt"

python ecoflow_prometheus.py
```

### Option 3: REST API (Developer)

Requires developer API credentials:

```bash
export ECOFLOW_DEVICE_SN="YOUR_DEVICE_SERIAL_NUMBER"
export ECOFLOW_ACCESS_KEY="your-access-key"
export ECOFLOW_SECRET_KEY="your-secret-key"

python ecoflow_prometheus.py
```

### Using Docker

```bash
docker run -d \
  -p 9090:9090 \
  -e ECOFLOW_DEVICE_SN="YOUR_DEVICE_SN" \
  -e ECOFLOW_ACCOUNT_USER="your-email@example.com" \
  -e ECOFLOW_ACCOUNT_PASSWORD="your-password" \
  -e ECOFLOW_API_TYPE="device" \
  ghcr.io/vpikus/ecoflow-prometheus-exporter:latest
```

### Using Docker Compose

Create a `.env` file:

```bash
ECOFLOW_DEVICE_SN=YOUR_DEVICE_SERIAL_NUMBER
ECOFLOW_ACCOUNT_USER=your-email@example.com
ECOFLOW_ACCOUNT_PASSWORD=your-password
```

Create `docker-compose.yml`:

```yaml
services:
  ecoflow_exporter:
    image: ghcr.io/vpikus/ecoflow-prometheus-exporter:latest
    ports:
      - "9090:9090"
    restart: unless-stopped
    environment:
      ECOFLOW_DEVICE_SN: ${ECOFLOW_DEVICE_SN}
      ECOFLOW_ACCOUNT_USER: ${ECOFLOW_ACCOUNT_USER}
      ECOFLOW_ACCOUNT_PASSWORD: ${ECOFLOW_ACCOUNT_PASSWORD}
      ECOFLOW_API_TYPE: device
```

Run:

```bash
docker-compose up -d
```

## Configuration

### Required Variables

| Variable               | Description                                    |
|------------------------|------------------------------------------------|
| `ECOFLOW_DEVICE_SN`    | Device serial number (found in EcoFlow app)    |

### Authentication (choose one)

**Developer API:**

| Variable                | Description                  |
|-------------------------|------------------------------|
| `ECOFLOW_ACCESS_KEY`    | Developer API access key     |
| `ECOFLOW_SECRET_KEY`    | Developer API secret key     |

**User API (MQTT/Device):**

| Variable                      | Description                  |
|-------------------------------|------------------------------|
| `ECOFLOW_ACCOUNT_USER`        | EcoFlow account email        |
| `ECOFLOW_ACCOUNT_PASSWORD`    | EcoFlow account password     |

### General Configuration

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `ECOFLOW_API_TYPE` | `mqtt` | API type: `mqtt` or `device` |
| `ECOFLOW_DEVICE_NAME` | — | Override device name in metrics |
| `ECOFLOW_PRODUCT_NAME` | — | Override product name in metrics |
| `ECOFLOW_DEVICE_GENERAL_KEY` | — | Override device general key (auto-detected from `devices.json`) |
| `ECOFLOW_DEVICES_JSON` | `devices.json` | Path to device definitions file |
| `ECOFLOW_API_HOST` | `api-e.ecoflow.com` | API host |
| `EXPORTER_PORT` | `9090` | Prometheus metrics port |
| `METRICS_PREFIX` | `ecoflow` | Metric name prefix |
| `LOG_LEVEL` | `INFO` | Log level: `DEBUG`, `INFO`, `WARNING`, `ERROR` |

### Timing Configuration

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `COLLECTING_INTERVAL` | `10` | Seconds between metric collections |
| `QUOTA_REQUEST_INTERVAL` | `30` | Device API: seconds between quota requests |
| `RETRY_TIMEOUT` | `30` | Retry delay on errors |
| `ESTABLISH_ATTEMPTS` | `5` | Max connection attempts on startup |

### Network Timeouts

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `HTTP_TIMEOUT` | `30` | HTTP request timeout (seconds) |
| `HTTP_RETRIES` | `3` | HTTP retry attempts (REST API) |
| `HTTP_BACKOFF_FACTOR` | `0.5` | Exponential backoff multiplier |
| `DEVICE_LIST_CACHE_TTL` | `60` | REST API: device list cache TTL for online status refresh |
| `MQTT_TIMEOUT` | `60` | MQTT idle timeout before reconnect |
| `MQTT_KEEPALIVE` | `60` | MQTT keepalive interval |
| `IDLE_CHECK_INTERVAL` | `30` | Idle connection check frequency |
| `MAX_RECONNECT_DELAY` | `300` | Max reconnect delay (backoff cap) |

### Device General Key

The `device_general_key` label identifies the device type and is used for grouping metrics across devices of the same model. It is resolved in the following order:

1. `ECOFLOW_DEVICE_GENERAL_KEY` environment variable (highest priority)
2. Matching device SN prefix in `devices.json`
3. Falls back to `unknown` if no match found

The `devices.json` file contains device definitions:

```json
[
  {
    "generalKey": "ecoflow_ps_delta_pro_3600",
    "name": "EcoFlow DELTA Pro",
    "sn": "DCA"
  }
]
```

If your device serial number starts with `DCA`, it will be matched to `ecoflow_ps_delta_pro_3600`.

### Device Name Resolution

The device name is resolved in the following order:

1. `ECOFLOW_DEVICE_NAME` environment variable (highest priority)
2. Device name from API (if different from serial number)
3. Friendly name built from `devices.json`: `<name>-<last 4 chars of SN>`
4. Falls back to device serial number

For example, if your device SN is `P521ZE1B3H6J0717` and the API returns the same value as the name, the exporter will look up `devices.json`, find the entry with `"sn": "P521"`, and build the name as `EcoFlow RAPID Pro Desktop Charger-0717`.

## API Comparison

| Feature | REST API | MQTT | Device API |
| ------- | -------- | ---- | ---------- |
| Auth | Developer tokens | User credentials | User credentials |
| Data flow | Polling | Push (passive) | Request/reply |
| Device discovery | Yes | No | No |
| Device support | Limited | Limited | **All devices** |
| Rate limits | API limits | None | None |

**Recommendation:** Use Device API (`ECOFLOW_API_TYPE=device`) for best compatibility.

## Docker Image

The Docker image is built with security and efficiency in mind:

- **Multi-stage build** - Minimal runtime image size
- **Non-root user** - Runs as `ecoflow` user (UID 1000)
- **Health check** - Built-in health monitoring via `/metrics` endpoint
- **Multi-platform** - Supports `linux/amd64` and `linux/arm64`

Available tags:

- `latest` - Latest stable release
- `X.Y.Z` - Specific version (e.g., `1.0.0`)
- `X.Y` - Minor version (e.g., `1.0`)
- `sha-XXXXXX` - Specific commit

## Prometheus Configuration

Add to your `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: 'ecoflow'
    static_configs:
      - targets: ['localhost:9090']
```

## Metrics

Metrics are exported with the prefix `ecoflow_` (configurable via `METRICS_PREFIX`).

All metrics include the following labels:

- `device` - Device serial number
- `device_name` - Device name (see [Device Name Resolution](#device-name-resolution))
- `product_name` - Product name (from API or `devices.json`)
- `device_general_key` - Device type identifier (auto-detected from `devices.json` or `ECOFLOW_DEVICE_GENERAL_KEY`)

Example metrics:

```text
# Device status
ecoflow_online{device="DCA12345678",device_name="EcoFlow DELTA Pro-5678",product_name="Delta Pro",device_general_key="ecoflow_ps_delta_pro_3600"} 1

# Battery
ecoflow_bms_master_soc{device="DCA12345678",...} 85
ecoflow_bms_master_temp{device="DCA12345678",...} 28

# Power
ecoflow_inv_input_watts{device="DCA12345678",...} 120
ecoflow_inv_output_watts{device="DCA12345678",...} 450

# And many more device-specific metrics...
```

## Grafana Dashboard

Import metrics into Grafana to visualize:

- Battery state of charge
- Input/output power
- Temperature
- Charging status
- Solar input (if applicable)

## Development

### Setup

```bash
# Clone the repository
git clone https://github.com/vpikus/ecoflow-prometheus-exporter.git
cd ecoflow-prometheus-exporter

# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install development dependencies
pip install -r requirements-dev.txt
```

### Running Tests

```bash
pytest --cov=ecoflow --cov-report=term-missing
```

### Linting

```bash
ruff check .
ruff format --check .
mypy ecoflow/
```

## Troubleshooting

### "signature is wrong" error (REST API)

Ensure your system clock is synchronized. The API requires accurate timestamps.

### No data received (MQTT/Device API)

1. Check credentials are correct
2. Verify device is online in the EcoFlow app
3. Try increasing `LOG_LEVEL` to `DEBUG`

### Connection timeouts

Adjust timeout values:

```bash
export HTTP_TIMEOUT=60
export MQTT_TIMEOUT=120
```

### Device goes offline and doesn't recover (REST API)

The REST API caches the device list. By default, it refreshes every 60 seconds. You can adjust this:

```bash
export DEVICE_LIST_CACHE_TTL=30  # Refresh every 30 seconds
```

## License

MIT License
