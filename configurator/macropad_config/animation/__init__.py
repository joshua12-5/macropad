"""OLED idle animation authoring.

Pure-Python modules (no Qt import at package level):

* :mod:`codec`   — firmware blob format (``MPAN`` header + RAW/RLE/DELTA
  frame records), PackBits, pixel helpers, wire helpers for ANIM_* cmds;
* :mod:`presets` — procedural built-in animations;
* :mod:`project` — ``*.mpanim.json`` project files in the user data folder;
* :mod:`gifwriter` — tiny GIF89a encoder (export / previews);
* :mod:`imaging` — GIF / PNG import → 128x64 1bpp (uses QtGui, imported lazily).
"""
