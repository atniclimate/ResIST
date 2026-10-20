"""AnalyticsProvider that computes nothing until the owner names a first measure (design 1.16, D-063)."""

from typing import Mapping

from resist.errors import DependencyError
from resist.models import Availability, Measure, MeasureSpec


class NullAnalytics:
    name = "null"
    version = "1"

    def available(self) -> Availability:
        return Availability(False, "no-metric: no metric chosen; owner decision (D-063)", "the owner names a first measure")

    def measures(self) -> list[MeasureSpec]:
        return []

    def compute(self, measure_id: str, params: Mapping[str, str]) -> Measure:
        raise DependencyError("no-metric", "the owner names a first measure (D-063)")
