"""Root conftest.py – makes the src/ layout importable and stubs out
krakenex only when it cannot be installed (legacy setup.py build issue)."""

import sys
import os
from unittest.mock import MagicMock

# Add src/ to the path so altotrader is importable without `pip install`
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

# Only mock krakenex if it genuinely cannot be imported (e.g. build env
# without legacy setuptools).  In CI where it is installed, the real package
# is used so that test_krakenticker.py keeps working with patch.object.
try:
    import krakenex  # noqa: F401
except Exception:
    sys.modules["krakenex"] = MagicMock()
