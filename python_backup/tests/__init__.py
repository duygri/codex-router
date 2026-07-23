import os
import sys


SOURCE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if SOURCE_ROOT not in sys.path:
    sys.path.insert(0, SOURCE_ROOT)
