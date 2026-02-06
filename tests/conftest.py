# -*- coding: utf-8 -*-
"""
Pytest configuration file.

This file is automatically loaded by pytest and configures the test environment.
"""

import sys
import os
from pathlib import Path

# Add src directory to Python path
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Print paths for debugging
print(f"Python path updated:")
print(f"  - Project root: {project_root}")
print(f"  - Src path: {src_path}")
