"""Shared pytest setup for the app-level test suite.

Ensures the project root is importable so `import main` and `from src...`
resolve the same way they do when Caspian boots the app.
"""

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Keep the app in its non-production code paths during tests (dev security
# headers, readable error messages, no HTTPS-only cookies).
os.environ.setdefault("APP_ENV", "development")
# Deterministic session secret so importing main.py never raises in dev.
os.environ.setdefault("AUTH_SECRET", "test-secret-not-for-production")
