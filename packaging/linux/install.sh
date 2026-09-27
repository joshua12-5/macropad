#!/bin/sh
# Optional helper: install the udev rule + a desktop launcher for the current user.
# Usage: ./install.sh            (asks for sudo only for the udev rule)
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
echo "Installing udev rule (sudo)…"
sudo install -m 0644 "$HERE/70-macropad.rules" /etc/udev/rules.d/70-macropad.rules
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=hidraw || true
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$APPS"
sed "s|^Exec=.*|Exec=\"$HERE/MacropadConfigurator/MacropadConfigurator\"|" \
  "$HERE/macropad-configurator.desktop" > "$APPS/macropad-configurator.desktop"
echo "Desktop launcher: $APPS/macropad-configurator.desktop"
echo "Done. Replug the macropad, then start MacropadConfigurator."
