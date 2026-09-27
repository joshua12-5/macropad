"""Pure foreground → profile match (unit-testable, no OS / USB)."""

from __future__ import annotations

import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Optional

from .rules import AutoswitchRules, Rule

BUILTIN_SLOT_MAP: dict[str, int] = {
    "default": 0,
    "gaming": 1,
    "coding": 2,
    "browser": 3,
    "photoshop": 4,
}


@dataclass(frozen=True)
class MatchResult:
    profile_id: Optional[str]
    slot: Optional[int]
    rule_index: Optional[int]  # None if fallback / no match
    reason: str


def process_basename(process: str) -> str:
    """Return basename without trailing .exe (Windows) for matching."""
    base = os.path.basename(process.replace("\\", "/"))
    if base.lower().endswith(".exe"):
        base = base[:-4]
    return base


def _process_matches(rule: Rule, basename: str) -> bool:
    """Case-insensitive: rule process entry is a substring of the basename."""
    needle = basename.casefold()
    for entry in rule.process:
        if entry and entry.casefold() in needle:
            return True
    return False


def _title_matches(rule: Rule, title: Optional[str]) -> bool:
    if rule.title_regex is None:
        return True
    if title is None:
        return False
    try:
        return re.search(rule.title_regex, title) is not None
    except re.error:
        return False


def resolve_slot(
    profile_id: str,
    *,
    rule_slot: Optional[int] = None,
    host_profile_ids: Optional[Sequence[str]] = None,
) -> Optional[int]:
    """Resolve device slot for a profile id.

    Order: explicit rule.slot → built-in map → host list index.
    """
    if rule_slot is not None and 0 <= int(rule_slot) <= 4:
        return int(rule_slot)
    if profile_id in BUILTIN_SLOT_MAP:
        return BUILTIN_SLOT_MAP[profile_id]
    if host_profile_ids is not None:
        try:
            idx = list(host_profile_ids).index(profile_id)
        except ValueError:
            return None
        if 0 <= idx <= 4:
            return idx
    return None


def match_foreground(
    rules: AutoswitchRules,
    process: Optional[str],
    title: Optional[str] = None,
    *,
    host_profile_ids: Optional[Sequence[str]] = None,
) -> MatchResult:
    """Return the first matching rule, else fallback, else no change."""
    if process:
        basename = process_basename(process)
        for i, rule in enumerate(rules.rules):
            if not _process_matches(rule, basename):
                continue
            if not _title_matches(rule, title):
                continue
            slot = resolve_slot(
                rule.profile_id,
                rule_slot=rule.slot,
                host_profile_ids=host_profile_ids,
            )
            return MatchResult(
                profile_id=rule.profile_id,
                slot=slot,
                rule_index=i,
                reason=f"rule[{i}] process={basename!r}",
            )

    if rules.fallback_profile_id:
        slot = resolve_slot(
            rules.fallback_profile_id,
            host_profile_ids=host_profile_ids,
        )
        return MatchResult(
            profile_id=rules.fallback_profile_id,
            slot=slot,
            rule_index=None,
            reason="fallback",
        )

    return MatchResult(
        profile_id=None,
        slot=None,
        rule_index=None,
        reason="no_match",
    )
