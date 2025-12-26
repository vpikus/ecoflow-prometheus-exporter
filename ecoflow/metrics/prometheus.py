import os
import re
from typing import Iterable, Type, Union

import inflection
from prometheus_client import Counter, Gauge, Info

METRICS_PREFIX = os.getenv("METRICS_PREFIX", "ecoflow")


class EcoflowMetric:
    """Prometheus metric wrapper for EcoFlow device data.

    Handles metric naming conventions and label management.
    Converts EcoFlow camelCase keys to Prometheus snake_case format.
    """

    METRICS_POOL: dict[str, Union[Info, Gauge, Counter]] = {}
    LABEL_NAMES = ["device", "device_name", "product_name"]

    def __init__(
        self,
        metric_type: Type[Union[Info, Gauge, Counter]],
        name: str,
        description: str,
        labelnames: Iterable[str] = (),
        **labels: str,
    ):
        name, index_labels = self._extract_indexes(name)
        self.labels = {**labels, **index_labels}

        if name in self.METRICS_POOL:
            self.metric = self.METRICS_POOL[name]
        else:
            modified_labelnames = list(labelnames) + list(index_labels.keys())
            self.metric = metric_type(
                f"{METRICS_PREFIX}_{self._to_snake_case(name)}",
                description,
                labelnames=modified_labelnames,
            )
            self.METRICS_POOL[name] = self.metric

    def _to_snake_case(self, string: str) -> str:
        """Convert EcoFlow key to Prometheus metric name."""
        result = re.sub(r"[.\[\]]", "_", string)
        result = re.sub(r"_+", "_", result)
        return inflection.underscore(result.strip("_"))

    def _extract_indexes(self, name: str) -> tuple[str, dict[str, str]]:
        """Extract array indices from metric name as labels."""
        pattern = re.compile(r"\[(\d+)\]")
        labels = {}
        matches = pattern.findall(name)
        for i, match in enumerate(matches):
            labels[f"index_{i}"] = match
        name = pattern.sub("", name)
        return name, labels

    def set(self, value: Union[int, float]) -> None:
        """Set gauge value."""
        self.metric.labels(**self.labels).set(value)

    def info(self, data: dict[str, str]) -> None:
        """Set info metric data."""
        self.metric.labels(**self.labels).info(data)

    def inc(self, value: Union[int, float] = 1) -> None:
        """Increment counter."""
        self.metric.labels(**self.labels).inc(value)

    def clear(self) -> None:
        """Clear all label values for this metric."""
        self.metric.clear()
