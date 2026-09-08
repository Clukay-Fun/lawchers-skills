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
    """Return Path to the bundled rules.json.

    Resolution order (first hit wins):
    1. PyInstaller _MEIPASS
    2. importlib.resources (normal pip install)
    3. __file__-relative (editable/source install)
    4. Walk up from cwd (last resort)
    """
    import sys as _sys

    # 1. PyInstaller
    if getattr(_sys, "frozen", False) and hasattr(_sys, "_MEIPASS"):
        return Path(_sys._MEIPASS) / "rules.json"

    # 2. importlib.resources (works for wheel/pip install)
    try:
        ref = resources.files("legal_desens").joinpath("rules/rules.json")
        # Try to resolve to a real path
        resolved = Path(str(ref))
        if resolved.exists():
            return resolved
        # For Traversable objects, try as_path
        with resources.as_file(ref) as p:
            if Path(p).exists():
                return Path(p)
    except (TypeError, FileNotFoundError, Exception):
        pass

    # 3. __file__-relative (editable install, source checkout)
    pkg_dir = Path(__file__).resolve().parent
    candidate = pkg_dir / "rules" / "rules.json"
    if candidate.exists():
        return candidate

    # 4. Walk up from package dir (in case of nested install)
    for parent in pkg_dir.parents:
        candidate = parent / "legal_desens" / "rules" / "rules.json"
        if candidate.exists():
            return candidate

    raise FileNotFoundError(
        f"Cannot find rules.json. Searched:\n"
        f"  - importlib.resources\n"
        f"  - {pkg_dir / 'rules' / 'rules.json'}\n"
        f"  Install with: pip install -e . or pip install legal-desens"
    )


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
