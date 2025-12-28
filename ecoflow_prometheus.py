import logging as log
import os
import signal
import sys
import time

from prometheus_client import REGISTRY, start_http_server

from ecoflow.api import CredentialsConflictError, EcoflowApiException, create_client
from ecoflow.devices import build_device_name, get_device_general_key, get_product_name
from ecoflow.worker import Worker

EXPORTER_PORT = int(os.getenv("EXPORTER_PORT", "9090"))
RETRY_TIMEOUT = int(os.getenv("RETRY_TIMEOUT", "30"))
ESTABLISH_ATTEMPTS = int(os.getenv("ESTABLISH_ATTEMPTS", "5"))


def signal_handler(signum, frame):
    log.info("Received signal %s. Exiting...", signum)
    sys.exit(0)


def setup_logging() -> None:
    """Configure logging based on LOG_LEVEL environment variable."""
    log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
    log_levels = {
        "DEBUG": log.DEBUG,
        "INFO": log.INFO,
        "WARNING": log.WARNING,
        "ERROR": log.ERROR,
    }
    log_level = log_levels.get(log_level_str, log.INFO)
    log.basicConfig(
        stream=sys.stdout,
        level=log_level,
        format="%(asctime)s %(levelname)-7s %(message)s",
    )


def main() -> None:
    signal.signal(signal.SIGTERM, signal_handler)

    # Disable default Prometheus collectors
    for coll in list(REGISTRY._collector_to_names.keys()):
        REGISTRY.unregister(coll)

    setup_logging()

    device_sn = os.getenv("ECOFLOW_DEVICE_SN")
    if not device_sn:
        log.error("ECOFLOW_DEVICE_SN must be set")
        sys.exit(1)

    try:
        client = create_client(device_sn)
    except CredentialsConflictError as e:
        log.error(str(e))
        sys.exit(1)
    except ValueError as e:
        log.error(str(e))
        sys.exit(1)

    # Attempt to connect with retries
    device = None
    for attempt in range(1, ESTABLISH_ATTEMPTS + 1):
        try:
            client.connect()
            device = client.get_device(device_sn)
            break
        except EcoflowApiException as e:
            log.error("Connection attempt %d failed: %s", attempt, e)
            if attempt >= ESTABLISH_ATTEMPTS:
                log.error("Failed to establish connection after %d attempts", ESTABLISH_ATTEMPTS)
                sys.exit(1)
            log.info("Retrying in %s seconds...", RETRY_TIMEOUT)
            time.sleep(RETRY_TIMEOUT)

    if not device:
        log.error("Device with SN %s not found", device_sn)
        sys.exit(1)

    device_name = build_device_name(device_sn, device.name)
    product_name = (
        os.getenv("ECOFLOW_PRODUCT_NAME")
        or device.product_name
        or get_product_name(device_sn)
        or "Unknown"
    )
    device_general_key = get_device_general_key(device_sn)

    log.info("Starting exporter for device: %s (%s)", device_name, product_name)
    log.info("Device general key: %s", device_general_key)

    worker = Worker(client, device_sn, device_name, product_name, device_general_key)

    start_http_server(EXPORTER_PORT)
    log.info("Prometheus metrics available at http://0.0.0.0:%d", EXPORTER_PORT)

    try:
        worker.run()
    except KeyboardInterrupt:
        pass
    finally:
        log.info("Shutting down...")
        client.disconnect()
        log.info("Exiting...")


if __name__ == "__main__":
    main()
