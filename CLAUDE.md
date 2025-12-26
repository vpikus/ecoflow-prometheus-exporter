# EcoFlow Prometheus Exporter

A Prometheus metrics exporter for EcoFlow devices that collects real-time data from the EcoFlow IoT API.

## Project Structure

```
├── ecoflow_prometheus.py    # Main application (all classes in single file)
├── requirements.txt         # Python dependencies
├── Dockerfile              # Container definition (python:3.12-alpine)
├── dev/                    # Development environment (docker-compose, .env)
└── grafana/dashboard/      # Pre-built Grafana dashboard
```

## Quick Commands

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

### Key Classes (ecoflow_prometheus.py)

- **EcoflowAuthentication**: HMAC-SHA256 signature generation for API auth
- **EcoflowClient**: REST API client for EcoFlow IoT endpoints
- **EcoflowMetric**: Prometheus metric wrapper with automatic label handling
- **Worker**: Main loop that collects and exports metrics

### API Endpoints Used

- `https://api.ecoflow.com/iot-open/sign/device/list` - List devices
- `https://api.ecoflow.com/iot-open/sign/device/quota/all` - Device statistics

### Metric Naming

- Prefix: `ecoflow_` (configurable via `METRICTS_PREFIX`)
- camelCase converted to snake_case
- Array indices become labels: `battery[0]` → `ecoflow_battery{index_0="0"}`
- All metrics include labels: `device`, `device_name`, `product_name`

## Environment Variables

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| ECOFLOW_DEVICE_SN | - | Yes | Device serial number |
| ECOFLOW_ACCESS_KEY | - | Yes | API access key |
| ECOFLOW_SECRET_KEY | - | Yes | API secret key |
| EXPORTER_PORT | 9090 | No | Prometheus metrics port |
| COLLECTING_INTERVAL | 10 | No | Seconds between collections |
| RETRY_TIMEOUT | 30 | No | Retry delay on API errors |
| ESTABLISH_ATTEMPTS | 5 | No | Max connection attempts |
| METRICTS_PREFIX | ecoflow | No | Metric name prefix |
| LOG_LEVEL | INFO | No | DEBUG/INFO/WARNING/ERROR |
| ECOFLOW_DEVICE_NAME | - | No | Override device name |

## Dependencies

- `prometheus-client>=0.20.0` - Prometheus metrics library
- `requests>=2.32.3` - HTTP client
- `inflection` - camelCase to snake_case conversion

## Code Patterns

- Single-file architecture with all classes in `ecoflow_prometheus.py`
- Metrics pool pattern to avoid duplicate metric registration
- Recursive metric processing for nested API responses
- Graceful degradation when device is offline (metrics cleared)
- Signal handling for container graceful shutdown (SIGTERM)
