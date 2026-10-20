"""Lotniska wylotowe dogodne z Polski: polskie + przygraniczne w Czechach i Niemczech."""

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path


@dataclass(frozen=True)
class Airport:
    code: str
    city: str
    country: str


AIRPORTS: dict[str, Airport] = {
    a.code: a
    for a in [
        # Polska
        Airport("WAW", "Warszawa Chopin", "PL"),
        Airport("WMI", "Warszawa Modlin", "PL"),
        Airport("KRK", "Kraków", "PL"),
        Airport("KTW", "Katowice", "PL"),
        Airport("GDN", "Gdańsk", "PL"),
        Airport("WRO", "Wrocław", "PL"),
        Airport("POZ", "Poznań", "PL"),
        Airport("RZE", "Rzeszów", "PL"),
        Airport("LUZ", "Lublin", "PL"),
        Airport("BZG", "Bydgoszcz", "PL"),
        Airport("SZZ", "Szczecin", "PL"),
        Airport("LCJ", "Łódź", "PL"),
        Airport("SZY", "Olsztyn-Mazury", "PL"),
        Airport("IEG", "Zielona Góra", "PL"),
        Airport("RDO", "Radom", "PL"),
        # Czechy (blisko granicy)
        Airport("PRG", "Praga", "CZ"),
        Airport("OSR", "Ostrawa", "CZ"),
        Airport("BRQ", "Brno", "CZ"),
        Airport("PED", "Pardubice", "CZ"),
        # Niemcy (blisko granicy)
        Airport("BER", "Berlin", "DE"),
        Airport("DRS", "Drezno", "DE"),
        Airport("LEJ", "Lipsk/Halle", "DE"),
        Airport("HAM", "Hamburg", "DE"),
    ]
}


CATALOG_PATH = Path(__file__).resolve().parent.parent / "data" / "destinations.json"


@cache
def destination_names() -> dict[str, str]:
    """Nazwy celów z katalogu używanego też przez stronę (działa każdy kod IATA, katalog to tylko nazwy)."""
    try:
        return {d["code"]: d["name"] for d in json.loads(CATALOG_PATH.read_text(encoding="utf-8"))}
    except (OSError, ValueError, KeyError):
        return {}


def describe(code: str) -> str:
    a = AIRPORTS.get(code)
    name = a.city if a else destination_names().get(code)
    return f"{name} ({code})" if name else code
