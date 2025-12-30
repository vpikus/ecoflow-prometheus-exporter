import logging as log
import os
import re
from collections.abc import Iterable

import inflection
from prometheus_client import Counter, Gauge, Histogram, Info

METRICS_PREFIX = os.getenv("METRICS_PREFIX", "ecoflow")


class EcoflowMetric:
    """Prometheus metric wrapper for EcoFlow device data.

    Handles metric naming conventions and label management.
    Converts EcoFlow camelCase keys to Prometheus snake_case format.
    """

    METRICS_POOL: dict[str, Info | Gauge | Counter | Histogram] = {}
    LABEL_NAMES = ["device", "device_name", "product_name", "device_general_key"]

    def __init__(
        self,
        metric_type: type[Info | Gauge | Counter | Histogram],
        name: str,
        description: str,
        labelnames: Iterable[str] = (),
        *,
        buckets: tuple[float, ...] | None = None,
        **labels: str,
    ):
        name, index_labels = self._extract_indexes(name)
        self.labels = {**labels, **index_labels}

        if name in self.METRICS_POOL:
            self.metric = self.METRICS_POOL[name]
            if buckets is not None:
                log.warning(
                    "Metric '%s' already exists; buckets parameter ignored", name
                )
        else:
            modified_labelnames = list(labelnames) + list(index_labels.keys())
            if metric_type == Histogram and buckets is not None:
                self.metric = metric_type(  # type: ignore[call-arg]
                    f"{METRICS_PREFIX}_{self._to_snake_case(name)}",
                    description,
                    labelnames=modified_labelnames,
                    buckets=buckets,
                )
            else:
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

    def set(self, value: int | float) -> None:
        """Set gauge value."""
        self.metric.labels(**self.labels).set(value)  # type: ignore[union-attr]

    def info(self, data: dict[str, str]) -> None:
        """Set info metric data."""
        self.metric.labels(**self.labels).info(data)  # type: ignore[union-attr]

    def inc(self, value: int | float = 1) -> None:
        """Increment counter."""
        self.metric.labels(**self.labels).inc(value)  # type: ignore[union-attr]

    def observe(self, value: float) -> None:
        """Observe a value for histogram."""
        self.metric.labels(**self.labels).observe(value)  # type: ignore[union-attr]

    def clear(self) -> None:
        """Clear all label values for this metric."""
        self.metric.clear()
