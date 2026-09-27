"""Hardware-in-the-loop test tooling.

* ``suite``  — ordered HIL tests over the vendor config HID channel.
* ``mock``   — in-process fake ``hid`` module + firmware protocol model.
* ``cli``    — ``python scripts/hil_test.py`` / ``python -m macropad_config.hil``.
"""

from .suite import TEST_IDS, HilOptions, HilReport, run_suite

__all__ = ["TEST_IDS", "HilOptions", "HilReport", "run_suite"]
