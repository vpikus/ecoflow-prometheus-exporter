# syntax=docker/dockerfile:1

# Stage 1: Build dependencies
FROM python:3.12-alpine AS builder

WORKDIR /app

# Install build dependencies
RUN apk add --no-cache --virtual .build-deps \
    gcc \
    musl-dev

# Install Python dependencies with BuildKit cache for faster rebuilds
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install --upgrade pip wheel setuptools && \
    python -m pip install --no-cache-dir --prefix=/install -r requirements.txt

# Stage 2: Runtime image
FROM python:3.12-alpine AS runtime

# Build arguments for labels
ARG VERSION=dev
ARG BUILD_DATE
ARG VCS_REF

# OCI Image Labels (https://github.com/opencontainers/image-spec/blob/main/annotations.md)
LABEL org.opencontainers.image.title="EcoFlow Prometheus Exporter" \
      org.opencontainers.image.description="Prometheus metrics exporter for EcoFlow portable power stations" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.source="https://github.com/vpikus/ecoflow-prometheus-exporter" \
      org.opencontainers.image.url="https://github.com/vpikus/ecoflow-prometheus-exporter" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.vendor="vpikus"

WORKDIR /app

# Install runtime shared libraries needed by compiled Python packages
# ca-certificates: for HTTPS connections (MQTT TLS, API calls)
# libstdc++: for protobuf and other C++ extensions
RUN apk add --no-cache \
    ca-certificates \
    libstdc++

# Create non-root user and data directory for potential future state/logs
RUN addgroup -g 1000 ecoflow && \
    adduser -u 1000 -G ecoflow -s /bin/sh -D ecoflow && \
    mkdir -p /app/data && \
    chown ecoflow:ecoflow /app/data

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY --chown=ecoflow:ecoflow ecoflow_prometheus.py .
COPY --chown=ecoflow:ecoflow devices.json .
COPY --chown=ecoflow:ecoflow ecoflow/ ./ecoflow/

# Switch to non-root user
USER ecoflow

# Expose metrics port
EXPOSE 9090

# Health check with conservative settings to avoid flapping
# - Start period of 45s allows time for MQTT/REST connection establishment
# - Increased timeout and retries for slow /metrics responses
HEALTHCHECK --interval=30s --timeout=15s --start-period=45s --retries=5 \
    CMD python -c "import urllib.request, os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"EXPORTER_PORT\", \"9090\")}/metrics', timeout=10)"

# Set environment defaults
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    EXPORTER_PORT=9090 \
    LOG_LEVEL=INFO

# Use ENTRYPOINT for predictable execution; CMD can be overridden for args
ENTRYPOINT ["python"]
CMD ["ecoflow_prometheus.py"]
