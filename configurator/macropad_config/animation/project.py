"""Animation project files (``*.mpanim.json``).

Stored in ``<user data>/animations`` (``paths.user_data_dir()``), overridable
with ``MACROPAD_ANIMATIONS_DIR``. Format (see docs/ANIMATION.md)::

    {
      "format": "macropad-animation",
      "schema_version": 1,
      "name": "stars",                  # <= 8 ASCII chars go into the blob
      "fps": 20, "loop": true,
      "width": 128, "height": 64,
      "frame_encoding": "ssd1306-pages-base64",
      "frames": ["<base64 of 1024 bytes>", ...],
      "idle": {"enabled": true, "idle_timeout_s": 60, "blank_timeout_s": 600},
      "generator": "macropad-configurator 0.26.0"
    }

Frames use the same page order as the firmware (see ``codec``), so a
project converts losslessly to/from the device blob.
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..paths import user_data_dir
from ..version import HOST_APP_VERSION
from . import codec as A

FORMAT_ID = "macropad-animation"
SCHEMA_VERSION = 1
SUFFIX = ".mpanim.json"


class ProjectError(ValueError):
    pass


def animations_dir(create: bool = True) -> Path:
    env = os.environ.get("MACROPAD_ANIMATIONS_DIR")
    d = Path(env).expanduser() if env else user_data_dir() / "animations"
    if create:
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
    return d


@dataclass
class AnimationProject:
    frames: list[bytes] = field(default_factory=lambda: [bytes(A.FRAME_BYTES)])
    fps: int = 15
    loop: bool = True
    name: str = "custom"
    idle_enabled: bool = True
    idle_timeout_s: int = A.DEFAULT_IDLE_S
    blank_timeout_s: int = A.DEFAULT_BLANK_S

    def validate(self) -> None:
        if not self.frames:
            raise ProjectError("animation has no frames")
        if len(self.frames) > A.MAX_FRAMES:
            raise ProjectError(f"too many frames ({len(self.frames)} > {A.MAX_FRAMES})")
        for i, f in enumerate(self.frames):
            if len(f) != A.FRAME_BYTES:
                raise ProjectError(f"frame {i} has {len(f)} bytes")
        if not 1 <= int(self.fps) <= A.MAX_FPS:
            raise ProjectError(f"fps must be 1..{A.MAX_FPS}")
        for v in (self.idle_timeout_s, self.blank_timeout_s):
            if not 0 <= int(v) <= 0xFFFF:
                raise ProjectError("timeouts must be 0..65535 s")

    # -- blob ---------------------------------------------------------------
    def to_blob(self) -> bytes:
        self.validate()
        return A.build_blob(self.frames, self.fps, self.loop, blob_name(self.name))

    @classmethod
    def from_blob(cls, blob: bytes, name: Optional[str] = None) -> AnimationProject:
        parsed = A.parse_blob(blob)
        return cls(
            frames=list(parsed.frames), fps=parsed.fps, loop=parsed.loop, name=name or parsed.name or "device"
        )

    # -- json ---------------------------------------------------------------
    def to_dict(self) -> dict:
        self.validate()
        return {
            "format": FORMAT_ID,
            "schema_version": SCHEMA_VERSION,
            "name": self.name,
            "fps": int(self.fps),
            "loop": bool(self.loop),
            "width": A.WIDTH,
            "height": A.HEIGHT,
            "frame_encoding": "ssd1306-pages-base64",
            "frames": [base64.b64encode(bytes(f)).decode("ascii") for f in self.frames],
            "idle": {
                "enabled": bool(self.idle_enabled),
                "idle_timeout_s": int(self.idle_timeout_s),
                "blank_timeout_s": int(self.blank_timeout_s),
            },
            "generator": f"macropad-configurator {HOST_APP_VERSION}",
        }

    @classmethod
    def from_dict(cls, d: dict) -> AnimationProject:
        if d.get("format") != FORMAT_ID:
            raise ProjectError("not a macropad animation project")
        if int(d.get("schema_version", 0)) != SCHEMA_VERSION:
            raise ProjectError(f"unsupported schema_version {d.get('schema_version')}")
        if (d.get("width"), d.get("height")) != (A.WIDTH, A.HEIGHT):
            raise ProjectError("only 128x64 animations are supported")
        if d.get("frame_encoding", "ssd1306-pages-base64") != "ssd1306-pages-base64":
            raise ProjectError("unknown frame_encoding")
        try:
            frames = [base64.b64decode(s, validate=True) for s in d.get("frames", [])]
        except Exception as exc:
            raise ProjectError(f"bad frame data: {exc}") from exc
        idle = d.get("idle") or {}
        p = cls(
            frames=frames,
            fps=int(d.get("fps", 15)),
            loop=bool(d.get("loop", True)),
            name=str(d.get("name") or "custom"),
            idle_enabled=bool(idle.get("enabled", True)),
            idle_timeout_s=int(idle.get("idle_timeout_s", A.DEFAULT_IDLE_S)),
            blank_timeout_s=int(idle.get("blank_timeout_s", A.DEFAULT_BLANK_S)),
        )
        p.validate()
        return p

    def save(self, path: os.PathLike | str) -> Path:
        path = Path(path)
        data = json.dumps(self.to_dict(), indent=1) + "\n"
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(data, encoding="utf-8")
        tmp.replace(path)
        return path

    @classmethod
    def load(cls, path: os.PathLike | str) -> AnimationProject:
        try:
            d = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProjectError(f"cannot read {path}: {exc}") from exc
        return cls.from_dict(d)


def blob_name(name: str) -> str:
    """ASCII, max 8 chars (blob header name field)."""
    clean = "".join(ch for ch in (name or "") if 32 <= ord(ch) < 127)
    return clean[:8]
