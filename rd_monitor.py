"""
RD / unattended monitor entrypoint.

Run directly:  python rd_monitor.py
Packaged:      QueudAIO.exe  (see scripts/build_rd_exe.ps1)

Expects beside the exe (or project root when run as script):
  .env          credentials, webhook, proxy
  data/         proxies.txt, session files
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


ROOT = _app_root()
os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "data"
os.environ.setdefault("QUEUD_AIO_DATA_DIR", str(DATA_DIR))
os.environ.setdefault("SPRINGBOKS_AUTO_CART", "1")
os.environ.setdefault("QUEUD_AIO_BROWSER_REQUESTS", "0")
os.environ.setdefault("TMPT_SOLVER", "auto")


def main() -> int:
    from queud_aio.cli import dispatch_command
    from queud_aio.log_util import log, setup_logging

    setup_logging(log_file=str(DATA_DIR / "monitor.log"))
    log(f"Queud AIO monitor — root {ROOT}")
    log("Request-based monitor (wreq). Ctrl+C to stop.")

    argv = ["monitor"]
    from queud_aio.settings import env_profiles_csv, env_profiles_row

    csv_path = env_profiles_csv()
    row = env_profiles_row()
    if csv_path:
        argv.extend(["--csv", csv_path])
    if row:
        argv.extend(["--row", row])
    return dispatch_command(argv)


if __name__ == "__main__":
    raise SystemExit(main())