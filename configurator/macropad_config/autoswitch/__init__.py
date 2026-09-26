"""Host-side foreground → profile auto-switch (Step 18)."""

from .matcher import BUILTIN_SLOT_MAP, MatchResult, match_foreground, resolve_slot
from .rules import (
    AutoswitchRules,
    default_rules_path,
    load_rules,
    save_rules,
    validate_rules,
)

__all__ = [
    "AutoswitchRules",
    "BUILTIN_SLOT_MAP",
    "MatchResult",
    "default_rules_path",
    "load_rules",
    "match_foreground",
    "resolve_slot",
    "save_rules",
    "validate_rules",
]
