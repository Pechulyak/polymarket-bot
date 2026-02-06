#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test runner for CopyTradingEngine.

Run this file directly in VS Code or from terminal:
    python run_tests.py
"""

import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

import pytest

if __name__ == "__main__":
    # Run tests with verbose output
    exit_code = pytest.main([
        "tests/unit/test_copy_trading.py",
        "-v",
        "--tb=short",
        "--color=yes",
    ])
    sys.exit(exit_code)
