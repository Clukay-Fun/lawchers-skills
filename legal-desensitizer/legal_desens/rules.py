"""Load and manage desensitization rules from rules.json."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import List, Optional


@dataclass
class Rule:
    id: str
    name: str
    entity_type: str
    label_prefix: str
    pattern: str
    enabled: bool = True
    priority: int = 100
    _compiled: object = field(default=None, repr=False, compare=False)

    def compile(self) -> None:
        import re
        self._compiled = re.compile(self.pattern)

    @property
    def compiled(self):
        if self._compiled is None:
            self.compile()
        return self._compiled


def _default_rules_path() -> Path:
    """Return Path to the bundled rules.json, handling PyInstaller."""
    import sys as _sys

    if getattr(_sys, "frozen", False) and hasattr(_sys, "_MEIPASS"):
        # PyInstaller: rules.json is at the root of the temp extract dir
        return Path(_sys._MEIPASS) / "rules.json"
    # Normal install: use importlib.resources
    return resources.files("legal_desens").joinpath("rules/rules.json")


def load_rules(path: Optional[str | Path] = None) -> List[Rule]:
    if path is None:
        rules_path = _default_rules_path()
        with open(rules_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    else:
        path = Path(path)
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)

    rules: List[Rule] = []
    for item in raw:
        r = Rule(
            id=item["id"],
            name=item["name"],
            entity_type=item["entity_type"],
            label_prefix=item["label_prefix"],
            pattern=item["pattern"],
            enabled=item.get("enabled", True),
            priority=item.get("priority", 100),
        )
        r.compile()
        rules.append(r)

    return [r for r in rules if r.enabled]
