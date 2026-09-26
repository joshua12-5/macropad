"""Profile dataclass + JSON load/save for schema v1."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .schema import SCHEMA_VERSION, SchemaError, validate_action, validate_profile_dict


class ProfileLoadError(Exception):
    """Failed to load or validate a profile file."""

    def __init__(self, path: Path | str, message: str) -> None:
        self.path = Path(path)
        self.message = message
        super().__init__(f"{self.path}: {message}")


@dataclass
class Profile:
    """In-memory representation of a schema v1 profile."""

    schema_version: int
    id: str
    name: str
    oled: dict[str, Any]
    keys: dict[str, dict[str, Any]]
    encoder: dict[str, dict[str, Any]]
    source_path: Path | None = field(default=None, repr=False)

    @property
    def oled_title(self) -> str:
        title = self.oled.get("title")
        return title if isinstance(title, str) else self.name

    def action_for_key(self, key_num: int) -> dict[str, Any] | None:
        return self.keys.get(str(key_num))

    def action_for_encoder(self, slot: str) -> dict[str, Any] | None:
        return self.encoder.get(slot)

    def set_key_action(self, key_num: int, action: dict[str, Any]) -> None:
        """Replace the action for key 1–12 (validated)."""
        if not 1 <= int(key_num) <= 12:
            raise ValueError(f"key_num must be 1–12, got {key_num}")
        validated = validate_action(dict(action), path=f"keys[{key_num}]")
        self.keys[str(key_num)] = dict(validated)

    def set_encoder_action(self, slot: str, action: dict[str, Any]) -> None:
        """Replace an encoder slot action (cw/ccw/press/long_press)."""
        if slot not in ("cw", "ccw", "press", "long_press"):
            raise ValueError(f"unknown encoder slot {slot!r}")
        validated = validate_action(dict(action), path=f"encoder.{slot}")
        self.encoder[slot] = dict(validated)

    def set_name(self, name: str) -> None:
        name = str(name).strip()
        if not name:
            raise ValueError("profile name must be non-empty")
        self.name = name

    def set_oled_title(self, title: str) -> None:
        self.oled = dict(self.oled)
        self.oled["title"] = str(title)

    def summary(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "schema_version": self.schema_version,
            "oled_title": self.oled_title,
            "source": str(self.source_path) if self.source_path else None,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "name": self.name,
            "oled": self.oled,
            "keys": self.keys,
            "encoder": self.encoder,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, path: Path | None = None) -> Profile:
        validated = validate_profile_dict(data)
        return cls(
            schema_version=int(validated["schema_version"]),
            id=str(validated["id"]),
            name=str(validated["name"]),
            oled=dict(validated["oled"]),
            keys={k: dict(v) for k, v in validated["keys"].items()},
            encoder={k: dict(v) for k, v in validated["encoder"].items()},
            source_path=path,
        )


def default_profiles_dir() -> Path:
    """Resolve profiles directory: MACROPAD_PROFILES_DIR or repo profiles/."""
    env = os.environ.get("MACROPAD_PROFILES_DIR")
    if env:
        return Path(env).expanduser().resolve()
    # configurator/ is parent of macropad_config/; repo root is parent of configurator/
    configurator_dir = Path(__file__).resolve().parents[2]
    return (configurator_dir.parent / "profiles").resolve()


def load_profile(path: Path | str) -> Profile:
    """Load and validate a single profile JSON file."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
    except OSError as exc:
        raise ProfileLoadError(path, f"cannot read file: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ProfileLoadError(path, f"invalid JSON: {exc}") from exc

    try:
        return Profile.from_dict(data, path=path)
    except SchemaError as exc:
        raise ProfileLoadError(path, str(exc)) from exc


def load_profiles_dir(
    directory: Path | str | None = None,
) -> tuple[list[Profile], list[ProfileLoadError]]:
    """Load all *.json profiles from a directory.

    Returns (successful profiles sorted by name, list of load errors).
    SCHEMA.md and other non-profile JSON that fail validation are reported
    as errors (caller may filter by filename if desired).
    """
    directory = Path(directory) if directory else default_profiles_dir()
    profiles: list[Profile] = []
    errors: list[ProfileLoadError] = []

    if not directory.is_dir():
        errors.append(ProfileLoadError(directory, "profiles directory not found"))
        return profiles, errors

    for path in sorted(directory.glob("*.json")):
        try:
            profiles.append(load_profile(path))
        except ProfileLoadError as exc:
            errors.append(exc)

    profiles.sort(key=lambda p: (p.name.lower(), p.id.lower()))
    return profiles, errors


def save_profile(profile: Profile, path: Path | str | None = None) -> Path:
    """Write profile JSON (pretty-printed). Used later by editors; available now."""
    dest = Path(path) if path else profile.source_path
    if dest is None:
        raise ValueError("no destination path for save_profile")
    payload = profile.to_dict()
    validate_profile_dict(payload)
    dest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    profile.source_path = dest
    return dest


__all__ = [
    "SCHEMA_VERSION",
    "Profile",
    "ProfileLoadError",
    "default_profiles_dir",
    "load_profile",
    "load_profiles_dir",
    "save_profile",
]
