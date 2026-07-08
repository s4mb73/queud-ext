"""Non-interactive menu preview (forces UI styling)."""
from __future__ import annotations

import os
import sys
from io import StringIO
from unittest.mock import patch

# Force color/UI for capture demo
os.environ["FORCE_COLOR"] = "1"

# Patch isatty so ui thinks we're in a terminal
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, root)

inputs = iter(
    [
        "2",  # Signups mode
        "2",  # list-signups
        "data/signups.example.csv",
    ]
)


def fake_input(prompt: str = "") -> str:
    val = next(inputs)
    print(prompt + val)
    return val


with patch("builtins.input", side_effect=fake_input), patch(
    "sys.stdout.isatty", return_value=True
):
    from queud_aio.log_util import set_interactive_mode
    from queud_aio.menu import run_menu

    set_interactive_mode(True)
    run_menu()