"""Hardware-in-the-loop test tooling (Step 23).

* ``suite``  — ordered HIL tests over the vendor config HID channel.
* ``mock``   — in-process fake ``hid`` module + firmware protocol model.
* ``cli``    — ``python scripts/hil_test.py`` / ``python -m macropad_config.hil``.
"""

from .suite import HilOptions, HilReport, TEST_IDS, run_suite

__all__ = ["HilOptions", "HilReport", "TEST_IDS", "run_suite"]
