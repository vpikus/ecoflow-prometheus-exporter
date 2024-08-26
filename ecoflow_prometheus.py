import datetime
import hashlib
import hmac
import logging as log
import os
import random
import re
import signal
import sys
import time
import urllib.parse
from datetime import timezone
from typing import Dict, Iterable, Type, Union

import inflection
import requests
from prometheus_client import REGISTRY, Gauge, Info, start_http_server

HOST = "https://api.ecoflow.com"
DEVICE_LIST_UTL = HOST + "/iot-open/sign/device/list"
GET_ALL_QUOTA_URL = HOST + "/iot-open/sign/device/quota/all"

EXPORTER_PORT = int(os.getenv("EXPORTER_PORT", "9090"))
COLLECTING_INTERVAL = int(os.getenv("COLLECTING_INTERVAL", "10"))
RETRY_TIMEOUT = int(os.getenv("RETRY_TIMEOUT", "60"))
ESTABLISH_ATTEMPTS = int(os.getenv("ESTABLISH_ATTEMPTS", "3"))

METRICTS_PREFIX = os.getenv("METRICTS_PREFIX", "ecoflow")


class EcoflowClientException(Exception):
    """Base class for exceptions in this module."""


class EcoflowAuthentication:

    def __init__(self, accessKey, secretKey):
        self.secretKey = secretKey
        self.accessKey = accessKey

    def build_signature(self, message):
        log.debug("Message: %s", message)
        signature = hmac.new(self.secretKey.encode(), message.encode(), hashlib.sha256).hexdigest()
        return signature


class EcoflowClient:

    def __init__(self, auth: EcoflowAuthentication):
        self.auth = auth

    def _execute_request(self, method, url, params):
        sign_params = dict(params)
        sign_params.update(
            {
                "accessKey": self.auth.accessKey,
                "nonce": f"{random.randint(0,999999):06d}",
                "timestamp": f"{int(datetime.datetime.now(timezone.utc).timestamp() * 1000)}",
            }
        )

        headers = {
            "sign": self.auth.build_signature(urllib.parse.urlencode(sign_params)),
        }
        headers.update(sign_params)
        response = requests.request(method, url, headers=headers, params=params)
        json = response.json()
        log.debug("Payload: %s", json)
        return self.unwrap_response(json)

    def unwrap_response(self, response):
        if str(response["message"]).lower() == "success":
            return response["data"]
        else:
            raise EcoflowClientException(f"Error: {response['message']}")

    def get_device_list(self):
        return self._execute_request("GET", DEVICE_LIST_UTL, {})

    def get_device_statistics(self, device_sn):
        return self._execute_request("GET", GET_ALL_QUOTA_URL, {"sn": device_sn})


class EcoflowMetric:

    METRICS_POOL: Dict[str, Union[Info, Gauge]] = {}

    def __init__(
        self,
        type: Type[Union[Info, Gauge]],
        name: str,
        description: str,
        labelnames: Iterable[str] = (),
        **labels,
    ):
        name, index_labels = self.extract_indexes(name)
        self.labels = {**labels, **index_labels}

        if name in self.METRICS_POOL:
            self.metric = self.METRICS_POOL[name]
        else:
            modified_labelnames = list(labelnames) + list(index_labels.keys())
            self.metric = type(
                f"{METRICTS_PREFIX}_{self.snake_case(name)}", description, labelnames=modified_labelnames
            )
            self.METRICS_POOL[name] = self.metric

    def snake_case(self, string):
        result = re.sub(r"[.\[\]]", "_", string)  # Replace dots and brackets with underscores
        result = re.sub(r"_+", "_", result)  # Remove multiple underscores
        return inflection.underscore(result.strip("_"))

    def extract_indexes(self, name: str) -> tuple[str, Dict[str, str]]:
        # Regular expression to find patterns like [0], [1], etc.
        pattern = re.compile(r"\[(\d+)\]")
        labels = {}
        # Find all matches and replace them in the name
        matches = pattern.findall(name)
        for i, match in enumerate(matches):
            labels[f"index_{i}"] = match
        # Remove the array indices from the name
        name = pattern.sub("", name)
        return name, labels

    def set(self, value: Union[int, float]):
        self.metric.labels(**self.labels).set(value)

    def info(self, data: Dict[str, str]):
        self.metric.labels(**self.labels).info(data)

    def clear(self):
        self.metric.clear()


class Worker:

    def __init__(self, client: EcoflowClient, device_sn):
        self.client = client
        self.device_sn = device_sn
        self.online: EcoflowMetric = EcoflowMetric(
            Gauge, "online", "1 if device is online", labelnames=["device"], device=device_sn
        )
        self.info: EcoflowMetric = EcoflowMetric(
            Info, "info", "Device information", labelnames=["device"], device=device_sn
        )
        self.metrics: Dict[str, EcoflowMetric] = {}

    def run(self):
        while True:
            try:
                self.collect_data()
                log.debug("Sleeping for %s seconds", COLLECTING_INTERVAL)
                time.sleep(COLLECTING_INTERVAL)
            except EcoflowClientException as e:
                log.error(f"Error: {e}")
                log.error("Retrying in %s seconds", RETRY_TIMEOUT)
                self.reset_metrics()
                self.online.clear()
                self.info.clear()
                time.sleep(RETRY_TIMEOUT)

    def collect_data(self):
        log.debug("Collecting data for device %s", device_sn)

        device = filter_device(self.client.get_device_list(), device_sn)
        self.update_divice_status(device)

        if device["online"] == 0:
            log.info(f"Device {device_sn} is offline")
            self.reset_metrics()
            return

        statistics = self.client.get_device_statistics(device_sn)
        self.update_metrics(statistics)

    def update_divice_status(self, device):
        self.online.set(device["online"])
        info_data = dict(device)
        info_data.pop("online")
        self.info.info(info_data)

    def update_metrics(self, statistics: Dict):
        for key, value in statistics.items():
            self.update_metric(key, value)

    def update_metric(self, key: str, value):
        if isinstance(value, (int, float)):
            if key not in self.metrics:
                self.metrics[key] = EcoflowMetric(
                    Gauge, key, f"Device metric {key}", labelnames=["device"], device=device_sn
                )
            self.metrics[key].set(value)
        elif isinstance(value, list):
            for i, sub_value in enumerate(value):
                self.update_metric(f"{key}[{i}]", sub_value)
        elif isinstance(value, dict):
            for sub_key, sub_value in value.items():
                self.update_metric(f"{key}.{sub_key}", sub_value)
        else:
            log.info(f"Skipping metric '{key}' with value '{value}'")

    def reset_metrics(self):
        for metric in self.metrics.values():
            metric.clear()


def signal_handler(signum, frame):
    log.info(f"Received signal {signum}. Exiting...")
    sys.exit(0)


def filter_device(devices, device_sn):
    return next((device for device in devices if device["sn"] == device_sn), None)


if __name__ == "__main__":
    # Register the signal handler for SIGTERM
    signal.signal(signal.SIGTERM, signal_handler)

    # Disable Process and Platform collectors
    for coll in list(REGISTRY._collector_to_names.keys()):
        REGISTRY.unregister(coll)

    log_level = os.getenv("LOG_LEVEL", "INFO")

    match log_level:
        case "DEBUG":
            log_level = log.DEBUG
        case "INFO":
            log_level = log.INFO
        case "WARNING":
            log_level = log.WARNING
        case "ERROR":
            log_level = log.ERROR
        case _:
            log_level = log.INFO

    log.basicConfig(stream=sys.stdout, level=log_level, format="%(asctime)s %(levelname)-7s %(message)s")

    device_sn = os.getenv("ECOFLOW_DEVICE_SN")
    if not device_sn:
        log.error("ECOFLOW_DEVICE_SN must be set")
        sys.exit(1)

    ecoflow_access_key = os.getenv("ECOFLOW_ACCESS_KEY")
    ecoflow_secret_key = os.getenv("ECOFLOW_SECRET_KEY")
    if not ecoflow_access_key or not ecoflow_secret_key:
        log.error("ECOFLOW_ACCESS_KEY and ECOFLOW_SECRET_KEY must be set")
        sys.exit(1)

    auth = EcoflowAuthentication(ecoflow_access_key, ecoflow_secret_key)
    client = EcoflowClient(auth)

    devices = None
    attempt = 0
    while not devices and attempt < ESTABLISH_ATTEMPTS:
        try:
            devices = client.get_device_list()
        except EcoflowClientException as e:
            log.error(f"Error: {e}")
            attempt += 1
            if attempt >= ESTABLISH_ATTEMPTS:
                log.error("Failed to establish connection")
                sys.exit(1)
            log.error("Retrying in %s seconds", RETRY_TIMEOUT)
            time.sleep(RETRY_TIMEOUT)

    filtered_device = filter_device(devices, device_sn)

    if not filtered_device:
        log.error(f"Device with SN {device_sn} not found")
        sys.exit(1)

    worker = Worker(client, device_sn)

    start_http_server(EXPORTER_PORT)

    try:
        worker.run()
    except KeyboardInterrupt:
        log.info("Exiting...")
        sys.exit(0)
