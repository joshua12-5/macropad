"""Load / save / validate autoswitch/rules.json (schema v1)."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

SCHEMA_VERSION = 1
DEFAULT_POLL_MS = 750
POLL_MS_MIN = 100
POLL_MS_MAX = 10000


class RulesError(ValueError):
    """Invalid rules document."""


@dataclass
class Rule:
    profile_id: str
    process: list[str]
    title_regex: Optional[str] = None
    slot: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "profile_id": self.profile_id,
            "process": list(self.process),
            "title_regex": self.title_regex,
        }
        if self.slot is not None:
            d["slot"] = self.slot
        return d


@dataclass
class AutoswitchRules:
    schema_version: int = SCHEMA_VERSION
    enabled: bool = False
    poll_ms: int = DEFAULT_POLL_MS
    fallback_profile_id: Optional[str] = None
    rules: list[Rule] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "enabled": self.enabled,
            "poll_ms": self.poll_ms,
            "fallback_profile_id": self.fallback_profile_id,
            "rules": [r.to_dict() for r in self.rules],
        }


def _repo_root() -> Path:
    # Source checkout → repo root; frozen build → per-user data dir.
    from ..paths import data_root

    return data_root()


def default_rules_path() -> Path:
    env = os.environ.get("MACROPAD_AUTOSWITCH_PATH")
    if env:
        return Path(env).expanduser()
    return _repo_root() / "autoswitch" / "rules.json"


def validate_rules(data: Any) -> AutoswitchRules:
    if not isinstance(data, dict):
        raise RulesError("root must be an object")
    ver = data.get("schema_version", SCHEMA_VERSION)
    if ver != SCHEMA_VERSION:
        raise RulesError(f"unsupported schema_version {ver} (want {SCHEMA_VERSION})")
    enabled = bool(data.get("enabled", False))
    try:
        poll_ms = int(data.get("poll_ms", DEFAULT_POLL_MS))
    except (TypeError, ValueError) as exc:
        raise RulesError("poll_ms must be an int") from exc
    if not POLL_MS_MIN <= poll_ms <= POLL_MS_MAX:
        raise RulesError(f"poll_ms must be {POLL_MS_MIN}..{POLL_MS_MAX}, got {poll_ms}")
    fb = data.get("fallback_profile_id", None)
    if fb is not None and not isinstance(fb, str):
        raise RulesError("fallback_profile_id must be string or null")
    if isinstance(fb, str) and not fb.strip():
        fb = None

    raw_rules = data.get("rules", [])
    if not isinstance(raw_rules, list):
        raise RulesError("rules must be an array")

    rules: list[Rule] = []
    for i, item in enumerate(raw_rules):
        if not isinstance(item, dict):
            raise RulesError(f"rules[{i}] must be an object")
        pid = item.get("profile_id")
        if not isinstance(pid, str) or not pid.strip():
            raise RulesError(f"rules[{i}].profile_id required")
        procs = item.get("process")
        if not isinstance(procs, list) or not procs:
            raise RulesError(f"rules[{i}].process must be a non-empty string array")
        for j, p in enumerate(procs):
            if not isinstance(p, str) or not p:
                raise RulesError(f"rules[{i}].process[{j}] must be a non-empty string")
        title_regex = item.get("title_regex", None)
        if title_regex is not None and not isinstance(title_regex, str):
            raise RulesError(f"rules[{i}].title_regex must be string or null")
        slot = item.get("slot", None)
        if slot is not None:
            try:
                slot = int(slot)
            except (TypeError, ValueError) as exc:
                raise RulesError(f"rules[{i}].slot must be int") from exc
            if not 0 <= slot <= 4:
                raise RulesError(f"rules[{i}].slot must be 0..4")
        rules.append(
            Rule(
                profile_id=pid.strip(),
                process=[str(p) for p in procs],
                title_regex=title_regex,
                slot=slot,
            )
        )

    return AutoswitchRules(
        schema_version=SCHEMA_VERSION,
        enabled=enabled,
        poll_ms=poll_ms,
        fallback_profile_id=fb,
        rules=rules,
    )


def load_rules(path: Optional[Path] = None) -> AutoswitchRules:
    path = path or default_rules_path()
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return validate_rules(data)


def save_rules(rules: AutoswitchRules, path: Optional[Path] = None) -> Path:
    path = path or default_rules_path()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = rules.to_dict()
    # Re-validate before write
    validate_rules(payload)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")
    tmp.replace(path)
    return path


def clone_rules(rules: AutoswitchRules) -> AutoswitchRules:
    return validate_rules(deepcopy(rules.to_dict()))
