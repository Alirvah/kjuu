from datetime import timedelta

from django.utils import timezone

from queueapp.templatetags.time_filters import timedelta_display, timesince_display


def test_timedelta_display_boundaries():
    assert timedelta_display(timedelta(0)) == "0s"
    assert timedelta_display(timedelta(seconds=59)) == "59s"
    assert timedelta_display(timedelta(minutes=2, seconds=5)) == "2m 5s"
    assert timedelta_display(timedelta(hours=1, minutes=2, seconds=3)) == "1h 2m 3s"


def test_timesince_display_with_aware_and_naive_datetimes(monkeypatch):
    fixed_now = timezone.now().replace(microsecond=0)
    monkeypatch.setattr("queueapp.templatetags.time_filters.timezone.now", lambda: fixed_now)

    aware_value = fixed_now - timedelta(hours=1, minutes=1, seconds=1)
    naive_value = (fixed_now - timedelta(seconds=30)).replace(tzinfo=None)

    assert timesince_display(aware_value) == "1h 1m 1s"
    assert timesince_display(naive_value).endswith("30s")


def test_timesince_display_with_timedelta_and_invalid_inputs():
    assert timesince_display(timedelta(minutes=3, seconds=4)) == "3m 4s"
    assert timesince_display(timedelta(seconds=-5)) == "0s"
    assert timesince_display("not-a-time") == ""
    assert timesince_display(None) == ""
