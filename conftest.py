"""Root conftest.py – makes the src/ layout importable and stubs out
krakenex (which requires a legacy build chain not available in all envs)."""

import sys
import os
from unittest.mock import MagicMock

# Add src/ to the path so altotrader is importable without `pip install`
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

# krakenex uses an old setup.py that may fail to build.  Since no test
# exercises the real network calls, a MagicMock is sufficient.
if "krakenex" not in sys.modules:
    sys.modules["krakenex"] = MagicMock()
