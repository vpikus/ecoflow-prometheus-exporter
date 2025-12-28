"""Device discovery and general key resolution."""

import json
import logging as log
import os
from pathlib import Path

# Environment variable override for general key
ECOFLOW_DEVICE_GENERAL_KEY = os.getenv("ECOFLOW_DEVICE_GENERAL_KEY")

# Default path to devices.json (relative to project root)
_DEFAULT_DEVICES_PATH = str(Path(__file__).resolve().parent.parent / "devices.json")
DEVICES_JSON_PATH = os.getenv("ECOFLOW_DEVICES_JSON", _DEFAULT_DEVICES_PATH)

# Cache for loaded devices
_devices_cache: list[dict] | None = None


def _load_devices() -> list[dict]:
    """Load device definitions from devices.json."""
    global _devices_cache

    if _devices_cache is not None:
        return _devices_cache

    log.info("Loading device definitions from %s", DEVICES_JSON_PATH)
    try:
        with open(DEVICES_JSON_PATH, encoding="utf-8") as f:
            _devices_cache = json.load(f)
            log.info("Loaded %d device definitions", len(_devices_cache))
            return _devices_cache
    except FileNotFoundError:
        log.warning("devices.json not found at %s", DEVICES_JSON_PATH)
        _devices_cache = []
        return _devices_cache
    except json.JSONDecodeError as e:
        log.error("Failed to parse devices.json: %s", e)
        _devices_cache = []
        return _devices_cache


def _find_matching_device(device_sn: str) -> dict | None:
    """Find matching device entry from devices.json by SN prefix.

    Args:
        device_sn: Device serial number.

    Returns:
        Matching device entry or None if not found.
    """
    devices = _load_devices()
    for device in devices:
        sn_prefix = device.get("sn", "")
        if sn_prefix and device_sn.startswith(sn_prefix):
            return device
    return None


def get_product_name(device_sn: str) -> str | None:
    """Get product name from devices.json by serial number prefix.

    Args:
        device_sn: Device serial number.

    Returns:
        Product name if found, None otherwise.
    """
    matched = _find_matching_device(device_sn)
    if matched:
        product_name = matched.get("name")
        if product_name:
            log.debug("Found product name for SN %s: %s", device_sn, product_name)
            return product_name
    return None


def get_device_general_key(device_sn: str) -> str:
    """Resolve device general key from serial number.

    Priority:
    1. ECOFLOW_DEVICE_GENERAL_KEY environment variable (if set)
    2. Match device SN prefix against devices.json entries
    3. Return "unknown" if no match found

    Args:
        device_sn: Device serial number.

    Returns:
        The general key for the device.
    """
    # Environment variable override takes priority
    if ECOFLOW_DEVICE_GENERAL_KEY:
        log.debug("Using general key from environment: %s", ECOFLOW_DEVICE_GENERAL_KEY)
        return ECOFLOW_DEVICE_GENERAL_KEY

    # Try to match from devices.json
    matched = _find_matching_device(device_sn)
    if matched:
        general_key = matched.get("generalKey", "unknown")
        log.debug(
            "Matched device SN %s with prefix %s, general key: %s",
            device_sn,
            matched.get("sn"),
            general_key,
        )
        return general_key

    log.warning("No matching device found for SN %s, using 'unknown'", device_sn)
    return "unknown"


def build_device_name(device_sn: str, api_device_name: str | None) -> str:
    """Build device name, using friendly name from devices.json if API name matches SN.

    If the device name from API equals the serial number, builds a friendly name
    using the pattern: "<name from devices.json>-<last 4 chars of SN>"

    Priority:
    1. ECOFLOW_DEVICE_NAME environment variable (if set)
    2. If API name differs from SN, use API name
    3. Build friendly name from devices.json: "<name>-<last 4 chars of SN>"
    4. Fall back to device SN

    Args:
        device_sn: Device serial number.
        api_device_name: Device name from API response.

    Returns:
        The resolved device name.
    """
    # Environment variable override takes priority
    env_name = os.getenv("ECOFLOW_DEVICE_NAME")
    if env_name:
        log.debug("Using device name from environment: %s", env_name)
        return env_name

    # If API provided a different name than SN, use it
    if api_device_name and api_device_name != device_sn:
        log.debug("Using device name from API: %s", api_device_name)
        return api_device_name

    # Try to build friendly name from devices.json
    matched = _find_matching_device(device_sn)
    if matched:
        friendly_name = matched.get("name", "")
        if friendly_name:
            suffix = device_sn[-4:] if len(device_sn) >= 4 else device_sn
            built_name = f"{friendly_name}-{suffix}"
            log.debug("Built device name from devices.json: %s", built_name)
            return built_name

    # Fall back to SN
    log.debug("Using device SN as name: %s", device_sn)
    return device_sn
