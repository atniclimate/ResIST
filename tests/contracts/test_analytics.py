"""AnalyticsProvider null (design 1.16): no metric until the owner names one (D-063)."""

import pytest

from resist.errors import DependencyError

KIND, NAME = "analytics", "null"


def test_null_shape(subject):
    assert subject.name == "null"
    av = subject.available()
    assert not av.ok and av.reason.startswith("no-metric") and av.remediation
    assert subject.measures() == []
    with pytest.raises(DependencyError) as e:
        subject.compute("any", {})
    assert e.value.reason == "no-metric"
