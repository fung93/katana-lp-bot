"""Tests for the sustained in/out-of-range alert state machine.

Pure logic, simulated timestamps - no network, no waiting 5 minutes.
"""
from __future__ import annotations

from app.monitor import step

SUS = 300.0  # 5 minutes


def test_out_alert_after_sustained_out() -> None:
    s, a = step(None, False, 0, SUS)      # first observation: out
    assert a is None
    s, a = step(s, False, 200, SUS)       # still out, < 5 min
    assert a is None
    s, a = step(s, False, 300, SUS)       # 5 min out -> alert
    assert a == "out"
    s, a = step(s, False, 600, SUS)       # already alerted, no repeat
    assert a is None


def test_recovery_in_alert_only_after_out() -> None:
    s, a = step(None, False, 0, SUS)
    s, a = step(s, False, 300, SUS)
    assert a == "out"
    s, a = step(s, True, 360, SUS)        # crossed back in: transition, no alert yet
    assert a is None
    s, a = step(s, True, 660, SUS)        # 5 min back in -> recovery alert
    assert a == "in"
    s, a = step(s, True, 999, SUS)        # no repeat
    assert a is None


def test_initial_in_range_never_alerts() -> None:
    s, a = step(None, True, 0, SUS)
    s, a = step(s, True, 300, SUS)
    s, a = step(s, True, 9999, SUS)
    assert a is None                      # in range the whole time -> silence


def test_flicker_below_sustain_is_silent() -> None:
    s, a = step(None, False, 0, SUS)      # out
    s, a = step(s, False, 120, SUS)       # out 2 min
    s, a = step(s, True, 130, SUS)        # back in before 5 min -> no out alert
    assert a is None
    s, a = step(s, True, 500, SUS)        # in a while, but never alerted out
    assert a is None                      # so no recovery alert either
