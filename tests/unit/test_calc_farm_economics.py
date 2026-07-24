# -*- coding: utf-8 -*-
"""Unit tests for farming/tools/calc_farm_economics.py (FARM-051).

leg_dist_cents(): дефолтная дистанция ноги должна совпадать с реальным
QUOTE_OFFSET демона (farming_daemon.py:59, 2c), а не со старой spread-based
оценкой min(spread/2, max_spread*0.9). Чистая функция, без сети/SDK.
"""
import os
import sys

_TOOLS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "farming", "tools")
)
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

import calc_farm_economics as cfe


def test_default_dist_is_quote_offset_constant():
    dist, warn = cfe.leg_dist_cents(ms=10.0)
    assert dist == cfe.DEFAULT_DIST_CENTS == 2.0


def test_narrow_max_spread_warns_without_override():
    # McConnell market (FARM-051 bug report): max_spread=3.5c < 4*2.0=8.0
    dist, warn = cfe.leg_dist_cents(ms=3.5)
    assert dist == 2.0
    assert warn is True


def test_wide_max_spread_no_warning():
    dist, warn = cfe.leg_dist_cents(ms=10.0)
    assert warn is False


def test_offset_override_suppresses_warning_and_is_used():
    dist, warn = cfe.leg_dist_cents(ms=3.5, offset_override=0.5)
    assert dist == 0.5
    assert warn is False


def test_dist_clamped_to_max_spread():
    dist, warn = cfe.leg_dist_cents(ms=1.0, offset_override=5.0)
    assert dist == 1.0


def test_mcconnell_score_factor_matches_bug_report():
    # FARM-051: ms=3.5c, dist=2c (реальный QUOTE_OFFSET) -> score_factor ~0.184
    # (было 0.735 при старом dist=0.5c из spread-based формулы)
    dist, _ = cfe.leg_dist_cents(ms=3.5)
    score_factor = ((3.5 - dist) / 3.5) ** 2
    assert abs(score_factor - 0.1837) < 0.001
