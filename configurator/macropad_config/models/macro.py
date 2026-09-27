"""Macro library dataclasses + JSON load/save (Step 13)."""

from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .schema import SchemaError

MACRO_SCHEMA_VERSION = 1

MACRO_OPS = (
    "END",
    "KEY_DOWN",
    "KEY_UP",
    "TAP",
    "DELAY_MS",
    "TEXT",
    "CONSUMER",
)

OPS_WITH_KEY = frozenset({"KEY_DOWN", "KEY_UP", "TAP"})
OPS_WITH_ARG = frozenset({"DELAY_MS", "TEXT", "CONSUMER"})
ALLOWED_MODS = frozenset({"CTRL", "SHIFT", "ALT", "GUI", "WIN", "CMD"})

# Fallback labels matching firmware macros.c when library.json is missing.
BUILTIN_MACRO_NAMES: dict[int, str] = {
    0: "hello",
    1: "sel+cpy",
    2: "undo/redo",
    3: "git st",
    4: "alt-tab",
}


class MacroLoadError(Exception):
    """Failed to load or validate a macro library file."""

    def __init__(self, path: Path | str, message: str) -> None:
        self.path = Path(path)
        self.message = message
        super().__init__(f"{self.path}: {message}")


@dataclass
class MacroStep:
    """One host-side macro step."""

    op: str
    mods: list[str] = field(default_factory=list)
    key: str = ""
    arg: int = 0

    def to_dict(self) -> dict[str, Any]:
        op = self.op
        out: dict[str, Any] = {"op": op}
        if op in OPS_WITH_KEY:
            if self.mods:
                out["mods"] = list(self.mods)
            else:
                out["mods"] = []
            # Always emit key ("" for mods-only / all-release).
            out["key"] = self.key if self.key is not None else ""
        if op in OPS_WITH_ARG:
            out["arg"] = int(self.arg)
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, path: str = "step") -> MacroStep:
        if not isinstance(data, dict):
            raise SchemaError(f"{path}: step must be an object")
        op = str(data.get("op", "")).upper()
        if op not in MACRO_OPS:
            raise SchemaError(f"{path}: unknown op {op!r}")

        mods_raw = data.get("mods", [])
        if mods_raw is None:
            mods_raw = []
        if not isinstance(mods_raw, list):
            raise SchemaError(f"{path}: mods must be a list")
        canon_mods: list[str] = []
        seen: set[str] = set()
        for m in mods_raw:
            name = str(m).upper()
            if name in ("WIN", "CMD"):
                name = "GUI"
            if name not in ("CTRL", "SHIFT", "ALT", "GUI"):
                raise SchemaError(f"{path}: invalid mod {m!r}")
            if name not in seen:
                seen.add(name)
                canon_mods.append(name)

        key = data.get("key", "")
        if key is None:
            key = ""
        key = str(key)

        arg_raw = data.get("arg", 0)
        arg = _parse_arg(arg_raw, path=path)

        if op == "END":
            return cls(op=op)
        if op in OPS_WITH_KEY:
            return cls(op=op, mods=canon_mods, key=key)
        if op == "DELAY_MS":
            if arg < 0 or arg > 65535:
                raise SchemaError(f"{path}: DELAY_MS arg out of range")
            return cls(op=op, arg=arg)
        if op == "TEXT":
            if not 0 <= arg <= 7:
                raise SchemaError(f"{path}: TEXT arg (text_id) must be 0–7")
            return cls(op=op, arg=arg)
        if op == "CONSUMER":
            if arg < 0 or arg > 65535:
                raise SchemaError(f"{path}: CONSUMER arg out of range")
            return cls(op=op, arg=arg)
        raise SchemaError(f"{path}: unhandled op {op!r}")


def _parse_arg(value: Any, *, path: str) -> int:
    if value is None:
        return 0
    if isinstance(value, bool):
        raise SchemaError(f"{path}: arg must be int/hex string")
    if isinstance(value, int):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return 0
        try:
            if text.lower().startswith("0x"):
                return int(text, 16)
            return int(text, 10)
        except ValueError as exc:
            raise SchemaError(f"{path}: invalid arg {value!r}") from exc
    raise SchemaError(f"{path}: arg must be int/hex string")


@dataclass
class Macro:
    """One named macro with stable id and ordered steps."""

    id: int
    name: str
    steps: list[MacroStep] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": int(self.id),
            "name": self.name,
            "steps": [s.to_dict() for s in self.steps],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, path: str = "macro") -> Macro:
        if not isinstance(data, dict):
            raise SchemaError(f"{path}: macro must be an object")
        if "id" not in data:
            raise SchemaError(f"{path}: missing id")
        try:
            mid = int(data["id"])
        except (TypeError, ValueError) as exc:
            raise SchemaError(f"{path}: id must be int") from exc
        if mid < 0:
            raise SchemaError(f"{path}: id must be >= 0")
        name = str(data.get("name", "")).strip()
        if not name:
            raise SchemaError(f"{path}: name must be non-empty")
        steps_raw = data.get("steps")
        if not isinstance(steps_raw, list):
            raise SchemaError(f"{path}: steps must be a list")
        steps = [
            MacroStep.from_dict(s, path=f"{path}.steps[{i}]")
            for i, s in enumerate(steps_raw)
        ]
        if not steps:
            raise SchemaError(f"{path}: steps must be non-empty")
        if steps[-1].op != "END":
            raise SchemaError(f"{path}: last step must be END")
        return cls(id=mid, name=name, steps=steps)


@dataclass
class MacroLibrary:
    """Host-side macro library (schema_version + macros list)."""

    schema_version: int
    macros: list[Macro] = field(default_factory=list)
    source_path: Path | None = field(default=None, repr=False)

    def to_dict(self) -> dict[str, Any]:
        # Stable sort by id for deterministic files.
        ordered = sorted(self.macros, key=lambda m: m.id)
        return {
            "schema_version": int(self.schema_version),
            "macros": [m.to_dict() for m in ordered],
        }

    def macro_by_id(self, macro_id: int) -> Macro | None:
        for m in self.macros:
            if m.id == macro_id:
                return m
        return None

    def names_map(self) -> dict[int, str]:
        return {m.id: m.name for m in self.macros}

    def max_id(self) -> int:
        if not self.macros:
            return -1
        return max(m.id for m in self.macros)

    def next_id(self) -> int:
        return self.max_id() + 1

    def add_macro(self, name: str = "new macro") -> Macro:
        macro = Macro(id=self.next_id(), name=name, steps=[MacroStep(op="END")])
        self.macros.append(macro)
        return macro

    def duplicate_macro(self, src: Macro, name: str | None = None) -> Macro:
        new_name = name if name is not None else f"{src.name} copy"
        macro = Macro(
            id=self.next_id(),
            name=new_name,
            steps=copy.deepcopy(src.steps),
        )
        self.macros.append(macro)
        return macro

    def remove_macro(self, macro_id: int) -> bool:
        before = len(self.macros)
        self.macros = [m for m in self.macros if m.id != macro_id]
        return len(self.macros) < before

    @classmethod
    def from_dict(
        cls, data: dict[str, Any], *, path: Path | None = None
    ) -> MacroLibrary:
        validated = validate_library_dict(data)
        macros = [
            Macro.from_dict(m, path=f"macros[{i}]")
            for i, m in enumerate(validated["macros"])
        ]
        return cls(
            schema_version=int(validated["schema_version"]),
            macros=macros,
            source_path=path,
        )


def validate_library_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Validate a library JSON object; return a shallow-normalized copy."""
    if not isinstance(data, dict):
        raise SchemaError("library must be an object")
    if "schema_version" not in data:
        raise SchemaError("missing schema_version")
    try:
        version = int(data["schema_version"])
    except (TypeError, ValueError) as exc:
        raise SchemaError("schema_version must be int") from exc
    if version != MACRO_SCHEMA_VERSION:
        raise SchemaError(
            f"unsupported schema_version {version} (expected {MACRO_SCHEMA_VERSION})"
        )
    macros_raw = data.get("macros")
    if not isinstance(macros_raw, list):
        raise SchemaError("macros must be a list")
    seen_ids: set[int] = set()
    for i, item in enumerate(macros_raw):
        macro = Macro.from_dict(item, path=f"macros[{i}]")
        if macro.id in seen_ids:
            raise SchemaError(f"duplicate macro id {macro.id}")
        seen_ids.add(macro.id)
    return {
        "schema_version": version,
        "macros": list(macros_raw),
    }


def default_macros_path() -> Path:
    """Resolve library path: MACROPAD_MACROS_PATH, else paths.data_root()/macros/library.json."""
    env = os.environ.get("MACROPAD_MACROS_PATH")
    if env:
        return Path(env).expanduser().resolve()
    from ..paths import data_root

    return (data_root() / "macros" / "library.json").resolve()


def load_library(path: Path | str | None = None) -> MacroLibrary:
    """Load and validate the host macro library JSON."""
    path = Path(path) if path else default_macros_path()
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
    except OSError as exc:
        raise MacroLoadError(path, f"cannot read file: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise MacroLoadError(path, f"invalid JSON: {exc}") from exc
    try:
        return MacroLibrary.from_dict(data, path=path)
    except SchemaError as exc:
        raise MacroLoadError(path, str(exc)) from exc


def save_library(library: MacroLibrary, path: Path | str | None = None) -> Path:
    """Write library JSON (pretty-printed)."""
    dest = Path(path) if path else library.source_path
    if dest is None:
        dest = default_macros_path()
    payload = library.to_dict()
    validate_library_dict(payload)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    library.source_path = dest
    return dest


def macro_names(path: Path | str | None = None) -> dict[int, str]:
    """Return {id: name} from library, or built-in fallback if missing/invalid."""
    try:
        lib_path = Path(path) if path else default_macros_path()
        if not lib_path.is_file():
            return dict(BUILTIN_MACRO_NAMES)
        library = load_library(lib_path)
        names = library.names_map()
        return names if names else dict(BUILTIN_MACRO_NAMES)
    except (MacroLoadError, OSError, SchemaError):
        return dict(BUILTIN_MACRO_NAMES)


def try_load_library(path: Path | str | None = None) -> MacroLibrary | None:
    """Load library or return None if missing/invalid."""
    try:
        lib_path = Path(path) if path else default_macros_path()
        if not lib_path.is_file():
            return None
        return load_library(lib_path)
    except (MacroLoadError, OSError, SchemaError):
        return None


__all__ = [
    "ALLOWED_MODS",
    "BUILTIN_MACRO_NAMES",
    "MACRO_OPS",
    "MACRO_SCHEMA_VERSION",
    "Macro",
    "MacroLibrary",
    "MacroLoadError",
    "MacroStep",
    "default_macros_path",
    "load_library",
    "macro_names",
    "save_library",
    "try_load_library",
    "validate_library_dict",
]
