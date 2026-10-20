import json
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .airports import AIRPORTS


@dataclass
class SearchConfig:
    destinations: list[str]
    origins: list[str]
    months_ahead: int = 12
    until: str | None = None
    one_way: bool = False
    currency: str = "PLN"
    max_transfers: int | None = None
    min_trip_days: int | None = None
    max_trip_days: int | None = None
    extra_cost: dict[str, float] = field(default_factory=dict)


@dataclass
class NotifyConfig:
    channel: str = "console"
    min_drop_percent: float = 2.0
    alert_below: float = 0
    report_hours: list[int] = field(default_factory=lambda: [9, 12, 15, 18])
    timezone: str = "Europe/Warsaw"


@dataclass
class Config:
    search: SearchConfig
    notify: NotifyConfig
    provider_name: str
    provider_settings: dict


def _opt(value):
    return value or None


def load_config(path: str | Path, settings_path: str | Path | None = None) -> Config:
    """Wczytuje config.toml; kierunki z pliku ustawień strony (data/settings.json) mają pierwszeństwo."""
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    if settings_path and Path(settings_path).exists():
        settings = json.loads(Path(settings_path).read_text(encoding="utf-8"))
        if settings.get("destinations"):
            raw.setdefault("search", {})["destinations"] = settings["destinations"]

    s = raw.get("search", {})
    origins = [c.upper() for c in s.get("origins", [])]
    if origins == ["ALL"]:
        origins = list(AIRPORTS)
    search = SearchConfig(
        destinations=[c.upper() for c in s.get("destinations", [])],
        origins=origins,
        months_ahead=int(s.get("months_ahead", 12)),
        until=s.get("until"),
        one_way=bool(s.get("one_way", False)),
        currency=s.get("currency", "PLN").upper(),
        max_transfers=s.get("max_transfers"),
        min_trip_days=_opt(s.get("min_trip_days")),
        max_trip_days=_opt(s.get("max_trip_days")),
        extra_cost={k.upper(): float(v) for k, v in s.get("extra_cost", {}).items()},
    )
    if not search.destinations or not search.origins:
        raise ValueError("config: 'destinations' i 'origins' nie mogą być puste")

    n = raw.get("notify", {})
    notify = NotifyConfig(
        channel=n.get("channel", "console"),
        min_drop_percent=float(n.get("min_drop_percent", 2)),
        alert_below=float(n.get("alert_below", 0)),
        report_hours=sorted(int(h) for h in n.get("report_hours", [9, 12, 15, 18])),
        timezone=n.get("timezone", "Europe/Warsaw"),
    )

    p = dict(raw.get("provider", {}))
    name = p.pop("name", "travelpayouts")
    if name == "travelpayouts":
        p["token"] = os.environ.get("TRAVELPAYOUTS_TOKEN", "")
    return Config(search=search, notify=notify, provider_name=name, provider_settings=p)
