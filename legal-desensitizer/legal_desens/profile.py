"""Profile-based desensitization policy: data-driven redact/preserve decisions."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Dict, Optional, Set


@dataclass
class TypePolicy:
    action: str  # "redact" or "preserve"
    label: Optional[str] = None  # e.g. "【姓名】" — only for redact types


@dataclass
class EntityPolicy:
    """Entity type preservation switch for fine-tuning per case."""
    preserve_types: Set[str] = field(default_factory=set)  # Types to preserve (not redact)
    force_redact_types: Set[str] = field(default_factory=set)  # Types to force redact


@dataclass
class Profile:
    name: str
    label_style: str  # "bracket_unnumbered"
    types: Dict[str, TypePolicy]
    address_merge: bool = True
    org_abbrev_dict: bool = True
    conservative_markdown: bool = True
    entity_policy: Optional[EntityPolicy] = None

    def should_redact(self, entity_type: str) -> bool:
        """Return True if this entity_type should be redacted under this profile."""
        # Check entity_policy overrides first
        if self.entity_policy:
            if entity_type in self.entity_policy.preserve_types:
                return False
            if entity_type in self.entity_policy.force_redact_types:
                return True

        policy = self.types.get(entity_type)
        if policy is None:
            return True  # Unknown types default to redact (safe)
        return policy.action == "redact"

    def get_label_text(self, entity_type: str) -> Optional[str]:
        """Return the bracket label text for redact types, e.g. '【姓名】'."""
        policy = self.types.get(entity_type)
        if policy and policy.action == "redact" and policy.label:
            return policy.label
        return None

    def redact_entity_types(self) -> set:
        """Return set of entity_type strings that should be redacted."""
        result = set()
        for t, p in self.types.items():
            # Check entity_policy overrides
            if self.entity_policy:
                if t in self.entity_policy.preserve_types:
                    continue
                if t in self.entity_policy.force_redact_types:
                    result.add(t)
                    continue
            if p.action == "redact":
                result.add(t)
        return result


# Backward-compat mapping: --level value → profile name
_LEVEL_TO_PROFILE = {
    "strict": "strict",
}


def _default_profiles_dir() -> Path:
    """Return path to bundled profiles/ directory."""
    import sys as _sys

    if getattr(_sys, "frozen", False) and hasattr(_sys, "_MEIPASS"):
        return Path(_sys._MEIPASS) / "profiles"
    # Normal install: profiles/ is a subdirectory of the package
    try:
        return Path(resources.files("legal_desens").joinpath("profiles"))
    except (TypeError, FileNotFoundError):
        pass
    # Fallback: look relative to this file
    return Path(__file__).resolve().parent / "profiles"


def load_profile(
    name: str,
    profiles_dir: Optional[str | Path] = None,
    entity_policy_file: Optional[str | Path] = None,
) -> Profile:
    """Load a profile by name from profiles/<name>.json.

    Args:
        name: Profile name (e.g. "labor", "strict").
        profiles_dir: Override profiles directory path.
        entity_policy_file: Path to case-specific entity_policy JSON file.
                           This file is local, NOT in git.

    Returns:
        Profile instance.

    Raises:
        FileNotFoundError: If profile JSON not found.
        ValueError: If profile JSON is invalid.
    """
    if profiles_dir is None:
        pdir = _default_profiles_dir()
    else:
        pdir = Path(profiles_dir)

    profile_path = pdir / f"{name}.json"
    if not profile_path.exists():
        raise FileNotFoundError(
            f"Profile not found: {profile_path}. "
            f"Available profiles: labor, strict"
        )

    with open(profile_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    types: Dict[str, TypePolicy] = {}
    for entity_type, cfg in raw.get("types", {}).items():
        types[entity_type] = TypePolicy(
            action=cfg.get("action", "redact"),
            label=cfg.get("label"),
        )

    # Load entity_policy if provided
    entity_policy = None
    if entity_policy_file:
        entity_policy = _load_entity_policy(entity_policy_file)

    return Profile(
        name=raw.get("name", name),
        label_style=raw.get("label_style", "bracket_unnumbered"),
        types=types,
        address_merge=raw.get("address_merge", True),
        org_abbrev_dict=raw.get("org_abbrev_dict", True),
        conservative_markdown=raw.get("conservative_markdown", True),
        entity_policy=entity_policy,
    )


def _load_entity_policy(path: str | Path) -> EntityPolicy:
    """Load entity_policy from a JSON file.

    Expected format:
    {
        "preserve_types": ["COURT", "ARBITRATION"],  // Types to preserve
        "force_redact_types": ["ORG"]  // Types to force redact
    }
    """
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    return EntityPolicy(
        preserve_types=set(raw.get("preserve_types", [])),
        force_redact_types=set(raw.get("force_redact_types", [])),
    )


def resolve_profile_name(profile: Optional[str], level: Optional[str]) -> str:
    """Resolve CLI args to profile name.

    Priority: --profile > --level mapping > default "labor".
    """
    if profile:
        return profile
    if level and level in _LEVEL_TO_PROFILE:
        return _LEVEL_TO_PROFILE[level]
    return "labor"
