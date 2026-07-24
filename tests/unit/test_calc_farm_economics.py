# -*- coding: utf-8 -*-
"""Unit tests for farming/tools/calc_farm_economics.py (FARM-051, FARM-053).

leg_dist_cents(): дефолтная дистанция ноги должна зеркалить реальное
поведение демона (farming_daemon.py). До FARM-053 демон квотировал
фиксированные QUOTE_OFFSET=2c для всех рынков; с FARM-053 — per-market
адаптивную дистанцию (quote_offset_for(), FARM-053), капнутую тем же 2c
потолком. Чистые функции, без сети/SDK.
"""
import os
import sys

_TOOLS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "farming", "tools")
)
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

import calc_farm_economics as cfe


def test_default_dist_caps_at_ceiling_for_wide_market():
    # ratio=0.375, ms=10.0 -> uncapped candidate 3.75c > ceiling 2.0c -> capped
    dist, is_adaptive = cfe.leg_dist_cents(ms=10.0)
    assert dist == cfe.QUOTE_OFFSET_CEILING_CENTS == 2.0
    assert is_adaptive is False  # capped at ceiling == pre-FARM-053 behavior here


def test_mcconnell_adaptive_dist_tightens_below_ceiling():
    # McConnell market (FARM-051/FARM-053 bug report): max_spread=3.5c.
    # ratio = (M_TARGET*REQUOTE_FRAC)/(1+M_TARGET*REQUOTE_FRAC) = 0.375
    # dist = min(0.375*3.5, 2.0) = min(1.3125, 2.0) = 1.3125
    dist, is_adaptive = cfe.leg_dist_cents(ms=3.5)
    assert abs(dist - 1.3125) < 1e-9
    assert is_adaptive is True  # tightened below the ceiling -> FARM-053 kicked in


def test_offset_override_suppresses_adaptive_flag_and_is_used():
    dist, is_adaptive = cfe.leg_dist_cents(ms=3.5, offset_override=0.5)
    assert dist == 0.5
    assert is_adaptive is False


def test_dist_clamped_to_max_spread():
    dist, is_adaptive = cfe.leg_dist_cents(ms=1.0, offset_override=5.0)
    assert dist == 1.0


def test_adaptive_offset_cents_none_max_spread_falls_back_to_ceiling():
    assert cfe.adaptive_offset_cents(None) == cfe.QUOTE_OFFSET_CEILING_CENTS


def test_adaptive_offset_cents_never_exceeds_ceiling():
    for ms in (1.0, 2.0, 3.5, 4.5, 5.5, 8.0, 20.0):
        assert cfe.adaptive_offset_cents(ms) <= cfe.QUOTE_OFFSET_CEILING_CENTS


def test_mcconnell_score_factor_matches_adaptive_formula():
    # FARM-053: ms=3.5c, dist=1.3125c (adaptive, was fixed 2c pre-FARM-053,
    # was 0.5c spread-based pre-FARM-051) -> score_factor ~0.391
    dist, _ = cfe.leg_dist_cents(ms=3.5)
    score_factor = ((3.5 - dist) / 3.5) ** 2
    assert abs(score_factor - 0.390625) < 0.001
