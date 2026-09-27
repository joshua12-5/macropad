"""Profile dataclass + JSON load/save for schema v1."""

from __future__ import annotations

import copy
import json
import os
import re
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


_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def is_valid_profile_id(profile_id: str) -> bool:
    """Return True if id matches ^[a-z][a-z0-9_]*$."""
    return bool(_ID_RE.match(profile_id or ""))


def suggest_profile_id(name: str, existing_ids: set[str]) -> str:
    """Slugify *name* to a unique lowercase id matching is_valid_profile_id."""
    slug = (name or "").strip().lower()
    slug = re.sub(r"[^a-z0-9_]+", "_", slug)
    slug = re.sub(r"_+", "_", slug).strip("_")
    if not slug:
        slug = "profile"
    if not slug[0].isalpha():
        slug = f"p_{slug}"
    if not is_valid_profile_id(slug):
        slug = re.sub(r"[^a-z0-9_]", "", slug)
        if not slug or not slug[0].isalpha():
            slug = "profile"
    if slug not in existing_ids:
        return slug
    n = 2
    while f"{slug}_{n}" in existing_ids:
        n += 1
    return f"{slug}_{n}"


def make_blank_profile(profile_id: str, name: str) -> Profile:
    """Create a schema-v1 blank profile (keys DISABLED; encoder volume + long DISABLED)."""
    name = str(name).strip()
    if not name:
        raise ValueError("profile name must be non-empty")
    if not is_valid_profile_id(profile_id):
        raise ValueError(f"invalid profile id {profile_id!r} (expected ^[a-z][a-z0-9_]*$)")
    keys = {str(i): {"type": "DISABLED"} for i in range(1, 13)}
    encoder = {
        "cw": {"type": "VOLUME", "dir": "up"},
        "ccw": {"type": "VOLUME", "dir": "down"},
        "press": {"type": "VOLUME", "dir": "mute"},
        "long_press": {"type": "DISABLED"},
    }
    profile = Profile(
        schema_version=SCHEMA_VERSION,
        id=profile_id,
        name=name,
        oled={"title": name, "animation": "static"},
        keys=keys,
        encoder=encoder,
        source_path=None,
    )
    validate_profile_dict(profile.to_dict())
    return profile


def duplicate_profile(src: Profile, new_id: str, new_name: str) -> Profile:
    """Deep-copy *src* with a new id/name; source_path cleared until saved."""
    new_name = str(new_name).strip()
    if not new_name:
        raise ValueError("profile name must be non-empty")
    if not is_valid_profile_id(new_id):
        raise ValueError(f"invalid profile id {new_id!r} (expected ^[a-z][a-z0-9_]*$)")
    profile = Profile(
        schema_version=int(src.schema_version),
        id=new_id,
        name=new_name,
        oled=copy.deepcopy(src.oled),
        keys={k: copy.deepcopy(v) for k, v in src.keys.items()},
        encoder={k: copy.deepcopy(v) for k, v in src.encoder.items()},
        source_path=None,
    )
    validate_profile_dict(profile.to_dict())
    return profile


def delete_profile_file(profile: Profile) -> None:
    """Unlink profile.source_path if set and present on disk."""
    path = profile.source_path
    if path is None:
        return
    path = Path(path)
    if path.is_file():
        path.unlink()
    profile.source_path = None


def suggest_profile_path(name: str, profile_id: str, directory: Path | str) -> Path:
    """Pick a unique JSON path under *directory* for a new profile file.

    Prefer ``{name with spaces removed}.json``. If that exists, fall back to
    ``{id}.json``, then ``{id}_2.json``, …
    """
    directory = Path(directory)
    base = (name or "").replace(" ", "").strip()
    if not base:
        base = profile_id
    candidate = directory / f"{base}.json"
    if not candidate.exists():
        return candidate
    candidate = directory / f"{profile_id}.json"
    if not candidate.exists():
        return candidate
    n = 2
    while True:
        candidate = directory / f"{profile_id}_{n}.json"
        if not candidate.exists():
            return candidate
        n += 1


def default_profiles_dir() -> Path:
    """Resolve profiles directory: MACROPAD_PROFILES_DIR, else paths.data_root()/profiles.

    Source checkout → repo ``profiles/``; frozen build → per-user data dir.
    """
    env = os.environ.get("MACROPAD_PROFILES_DIR")
    if env:
        return Path(env).expanduser().resolve()
    from ..paths import data_root

    return (data_root() / "profiles").resolve()


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
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    profile.source_path = dest
    return dest


__all__ = [
    "SCHEMA_VERSION",
    "Profile",
    "ProfileLoadError",
    "default_profiles_dir",
    "delete_profile_file",
    "duplicate_profile",
    "is_valid_profile_id",
    "load_profile",
    "load_profiles_dir",
    "make_blank_profile",
    "save_profile",
    "suggest_profile_id",
    "suggest_profile_path",
]
