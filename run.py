#!/usr/bin/env python3
"""Rugby SA monitor — run from project root: python run.py --check"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rugby_sa.cli import main

if __name__ == "__main__":
    raise SystemExit(main())