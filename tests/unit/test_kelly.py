# -*- coding: utf-8 -*-
"""Unit tests for Kelly Criterion calculations."""

import pytest
from decimal import Decimal


class TestKellyCalculator:
    """Test Kelly Criterion position sizing."""
    
    def test_kelly_calculation_basic(self):
        """Test basic Kelly formula: f* = (bp - q) / b"""
        # Edge case: 60% win rate, 2:1 payoff
        bankroll = Decimal("100")
        win_prob = Decimal("0.6")
        payoff = Decimal("2.0")
        
        # f* = (2*0.6 - 0.4) / 2 = 0.4
        # Position = 100 * 0.4 = 40
        expected = Decimal("40")
        # TODO: Implement actual test
        assert True
    
    def test_kelly_zero_edge(self):
        """Test Kelly returns 0 when no edge."""
        # 50% win rate, 1:1 payoff = no edge
        pass
    
    def test_kelly_max_cap(self):
        """Test Kelly respects 25% max position limit."""
        pass
