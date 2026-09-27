"""PyInstaller entry script for Macropad Configurator.

Kept outside the package so PyInstaller analyses ``macropad_config`` as a
normal package (relative imports intact).
"""

import sys

from macropad_config.app import main

if __name__ == "__main__":
    sys.exit(main())
