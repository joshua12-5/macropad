"""Action type enums and validation helpers for profile schema v1."""

from __future__ import annotations

from enum import Enum
from typing import Any

SCHEMA_VERSION = 1


class ActionType(str, Enum):
    DISABLED = "DISABLED"
    KEY = "KEY"
    SHORTCUT = "SHORTCUT"
    MACRO = "MACRO"
    TEXT = "TEXT"
    MEDIA = "MEDIA"
    VOLUME = "VOLUME"
    APP = "APP"
    URL = "URL"
    PROFILE = "PROFILE"


ACTION_TYPES = frozenset(t.value for t in ActionType)

VOLUME_DIRS = frozenset({"up", "down", "mute"})
KNOWN_MODS = frozenset({"CTRL", "SHIFT", "ALT", "GUI", "WIN", "CMD"})


class SchemaError(ValueError):
    """Raised when a profile or action fails schema checks."""


def validate_action(action: Any, *, path: str = "action") -> dict[str, Any]:
    """Validate an action object; return the dict unchanged if OK."""
    if not isinstance(action, dict):
        raise SchemaError(f"{path}: expected object, got {type(action).__name__}")
    atype = action.get("type")
    if atype not in ACTION_TYPES:
        raise SchemaError(f"{path}: unknown or missing type {atype!r}")

    if atype == ActionType.KEY.value:
        if "key" not in action:
            raise SchemaError(f"{path}: KEY requires 'key'")
    elif atype == ActionType.SHORTCUT.value:
        if "key" not in action:
            raise SchemaError(f"{path}: SHORTCUT requires 'key'")
        mods = action.get("mods", [])
        if not isinstance(mods, list):
            raise SchemaError(f"{path}: mods must be a list")
    elif atype == ActionType.MACRO.value:
        if "macro_id" not in action:
            raise SchemaError(f"{path}: MACRO requires 'macro_id'")
    elif atype in (ActionType.TEXT.value, ActionType.URL.value):
        if "text_id" not in action:
            raise SchemaError(f"{path}: {atype} requires 'text_id'")
    elif atype == ActionType.APP.value:
        if "text_id" not in action and "app_id" not in action:
            raise SchemaError(f"{path}: APP requires 'text_id' or 'app_id'")
    elif atype == ActionType.MEDIA.value:
        if "code" not in action and "usage" not in action:
            raise SchemaError(f"{path}: MEDIA requires 'code' or 'usage'")
    elif atype == ActionType.VOLUME.value:
        direction = action.get("dir")
        if direction not in VOLUME_DIRS:
            raise SchemaError(f"{path}: VOLUME dir must be one of {sorted(VOLUME_DIRS)}")
    elif atype == ActionType.PROFILE.value:
        if "profile_id" not in action and "slot" not in action:
            # allow bare type for now with soft warning path — firmware may use slot index
            pass

    return action


def validate_profile_dict(data: Any) -> dict[str, Any]:
    """Validate a full profile dict (schema v1). Raises SchemaError on failure."""
    if not isinstance(data, dict):
        raise SchemaError(f"profile root must be an object, got {type(data).__name__}")

    version = data.get("schema_version")
    if version != SCHEMA_VERSION:
        raise SchemaError(
            f"unsupported schema_version {version!r} (expected {SCHEMA_VERSION})"
        )

    for field in ("id", "name"):
        if not isinstance(data.get(field), str) or not data[field]:
            raise SchemaError(f"profile requires non-empty string '{field}'")

    oled = data.get("oled")
    if not isinstance(oled, dict):
        raise SchemaError("oled must be an object")
    if not isinstance(oled.get("title"), str):
        raise SchemaError("oled.title must be a string")

    keys = data.get("keys")
    if not isinstance(keys, dict):
        raise SchemaError("keys must be an object")
    for i in range(1, 13):
        key = str(i)
        if key not in keys:
            raise SchemaError(f"keys missing entry '{key}'")
        validate_action(keys[key], path=f"keys[{key}]")

    encoder = data.get("encoder")
    if not isinstance(encoder, dict):
        raise SchemaError("encoder must be an object")
    for slot in ("cw", "ccw", "press", "long_press"):
        if slot not in encoder:
            raise SchemaError(f"encoder missing '{slot}'")
        validate_action(encoder[slot], path=f"encoder.{slot}")

    return data
