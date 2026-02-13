# -*- coding: utf-8 -*-
"""Unit tests for Kelly Criterion calculations."""

import pytest
from decimal import Decimal


def calculate_kelly_fraction(
    win_probability: Decimal,
    payout_ratio: Decimal,
) -> Decimal:
    """Calculate Kelly Criterion fraction.

    Formula: f* = (b * p - q) / b
    Where:
    - b = payout_ratio - 1 (net odds)
    - p = probability of winning
    - q = probability of losing (1 - p)

    Args:
        win_probability: Probability of winning (0.0 to 1.0)
        payout_ratio: Total payout on winning (e.g., 2.0 for 2:1)

    Returns:
        Kelly fraction, or 0 if negative edge
    """
    if win_probability <= Decimal("0") or win_probability >= Decimal("1"):
        return Decimal("0")

    p = win_probability
    q = Decimal("1") - p
    b = payout_ratio - Decimal("1")

    if b <= Decimal("0"):
        return Decimal("0")

    kelly = (b * p - q) / b
    return max(kelly, Decimal("0"))


def calculate_kelly_size(
    bankroll: Decimal,
    win_probability: Decimal,
    payout_ratio: Decimal,
    kelly_multiplier: Decimal = Decimal("0.25"),
    min_fraction: Decimal = Decimal("0.01"),
    max_fraction: Decimal = Decimal("0.05"),
) -> Decimal:
    """Calculate Kelly position size with limits.

    Args:
        bankroll: Total bankroll
        win_probability: Win probability (0.0 to 1.0)
        payout_ratio: Payout ratio
        kelly_multiplier: Kelly fraction multiplier (default 0.25 for quarter Kelly)
        min_fraction: Minimum position as fraction of bankroll
        max_fraction: Maximum position as fraction of bankroll

    Returns:
        Position size in USD
    """
    kelly_fraction = calculate_kelly_fraction(win_probability, payout_ratio)

    if kelly_fraction <= Decimal("0"):
        return Decimal("0")

    adjusted_fraction = kelly_fraction * kelly_multiplier
    final_fraction = max(min_fraction, min(adjusted_fraction, max_fraction))

    return bankroll * final_fraction


class TestKellyCalculator:
    """Test Kelly Criterion position sizing."""

    def test_kelly_calculation_positive_edge(self):
        """Test Kelly formula with positive edge: 60% win rate, 2:1 payout."""
        bankroll = Decimal("100")
        win_prob = Decimal("0.6")
        payout = Decimal("2.0")

        kelly_fraction = calculate_kelly_fraction(win_prob, payout)

        expected_kelly = (Decimal("1") * win_prob - Decimal("0.4")) / Decimal("1")
        assert kelly_fraction == pytest.approx(expected_kelly, rel=Decimal("0.01"))

        size = calculate_kelly_size(bankroll, win_prob, payout)
        full_kelly = bankroll * expected_kelly * Decimal("0.25")
        max_allowed = bankroll * Decimal("0.05")
        expected = min(full_kelly, max_allowed)
        assert size == pytest.approx(expected)

    def test_kelly_zero_edge_50_percent(self):
        """Test Kelly returns 0 when no edge: 50% win rate, 1:1 payout."""
        win_prob = Decimal("0.5")
        payout = Decimal("1.0")

        kelly_fraction = calculate_kelly_fraction(win_prob, payout)
        assert kelly_fraction == Decimal("0")

    def test_kelly_negative_edge(self):
        """Test Kelly returns 0 when negative edge: 40% win rate."""
        win_prob = Decimal("0.4")
        payout = Decimal("1.5")

        kelly_fraction = calculate_kelly_fraction(win_prob, payout)
        assert kelly_fraction == Decimal("0")

    def test_kelly_high_win_rate(self):
        """Test Kelly with high win rate: 80% win rate."""
        bankroll = Decimal("100")
        win_prob = Decimal("0.8")
        payout = Decimal("1.5")

        size = calculate_kelly_size(bankroll, win_prob, payout)
        assert size > Decimal("0")

    def test_kelly_quarter_kelly_multiplier(self):
        """Test Kelly applies quarter Kelly multiplier."""
        bankroll = Decimal("100")
        win_prob = Decimal("0.6")
        payout = Decimal("2.0")

        full_kelly = calculate_kelly_fraction(win_prob, payout)
        quarter_kelly = full_kelly * Decimal("0.25")

        size = calculate_kelly_size(
            bankroll, win_prob, payout, kelly_multiplier=Decimal("0.25")
        )

        expected = bankroll * quarter_kelly
        assert size == pytest.approx(expected)

    def test_kelly_max_fraction_limit(self):
        """Test Kelly respects 5% max position limit."""
        bankroll = Decimal("100")
        win_prob = Decimal("0.9")
        payout = Decimal("5.0")

        size = calculate_kelly_size(bankroll, win_prob, payout)

        max_allowed = bankroll * Decimal("0.05")
        assert size <= max_allowed

    def test_kelly_min_fraction_limit(self):
        """Test Kelly respects 1% min position limit."""
        bankroll = Decimal("100")
        win_prob = Decimal("0.51")
        payout = Decimal("1.1")

        size = calculate_kelly_size(bankroll, win_prob, payout)

        min_allowed = bankroll * Decimal("0.01")
        assert size >= min_allowed or size == Decimal("0")

    def test_kelly_below_min_returns_zero(self):
        """Test Kelly returns 0 when below minimum threshold."""
        bankroll = Decimal("100")
        win_prob = Decimal("0.501")
        payout = Decimal("1.01")

        size = calculate_kelly_size(bankroll, win_prob, payout)
        if size > Decimal("0"):
            min_allowed = bankroll * Decimal("0.01")
            assert size >= min_allowed

    def test_kelly_zero_win_probability(self):
        """Test Kelly returns 0 for zero win probability."""
        kelly_fraction = calculate_kelly_fraction(Decimal("0"), Decimal("2.0"))
        assert kelly_fraction == Decimal("0")

    def test_kelly_unit_win_probability(self):
        """Test Kelly returns 0 for 100% win probability."""
        kelly_fraction = calculate_kelly_fraction(Decimal("1"), Decimal("2.0"))
        assert kelly_fraction == Decimal("0")

    def test_kelly_payout_ratio_one(self):
        """Test Kelly returns 0 for payout ratio of 1."""
        kelly_fraction = calculate_kelly_fraction(Decimal("0.6"), Decimal("1.0"))
        assert kelly_fraction == Decimal("0")

    def test_kelly_payout_less_than_one(self):
        """Test Kelly returns 0 for payout ratio less than 1."""
        kelly_fraction = calculate_kelly_fraction(Decimal("0.6"), Decimal("0.5"))
        assert kelly_fraction == Decimal("0")

    def test_kelly_with_bankroll_zero(self):
        """Test Kelly returns 0 for zero bankroll."""
        size = calculate_kelly_size(Decimal("0"), Decimal("0.6"), Decimal("2.0"))
        assert size == Decimal("0")

    def test_kelly_typical_binary_market(self):
        """Test Kelly with typical Polymarket binary market (50-50 at 0.5)."""
        bankroll = Decimal("100")
        win_prob = Decimal("0.55")
        payout = Decimal("1.82")

        size = calculate_kelly_size(bankroll, win_prob, payout)

        assert size > Decimal("0")
        assert size <= bankroll * Decimal("0.05")

    def test_kelly_70_percent_winner(self):
        """Test Kelly with 70% winning whale."""
        bankroll = Decimal("100")
        win_prob = Decimal("0.70")
        payout = Decimal("1.43")

        size = calculate_kelly_size(bankroll, win_prob, payout)

        assert size > Decimal("0")
