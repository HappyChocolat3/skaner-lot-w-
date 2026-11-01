"""Historia najniższych cen w pliku JSON (commitowanym przez GitHub Actions)."""

import json
from pathlib import Path


class State:
    """Struktura: {"routes": {"PL>LAS": {"2027-06": {"best": {...}, "current": {...}}}}, "legs": [...]}"""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.data: dict = {"routes": {}}
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
            self.data.setdefault("routes", {})

    @property
    def is_empty(self) -> bool:
        return not self.data["routes"]

    def month(self, route: str, month: str) -> dict:
        return self.data["routes"].setdefault(route, {}).setdefault(month, {})

    def keep_routes(self, routes: list[str]) -> None:
        """Usuwa odcinki, których nie ma już na trasie."""
        for r in [r for r in self.data["routes"] if r not in routes]:
            del self.data["routes"][r]

    def prune_before(self, month: str) -> None:
        """Usuwa miesiące, które już minęły."""
        for months in self.data["routes"].values():
            for m in [m for m in months if m < month]:
                del months[m]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
