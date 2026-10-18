from dataclasses import asdict, dataclass
from datetime import date
from typing import Optional


@dataclass
class Offer:
    origin: str
    destination: str
    price: float
    currency: str
    departure_date: date
    return_date: Optional[date] = None
    airline: str = ""
    transfers: int = 0
    return_transfers: int = 0
    link: str = ""
    source: str = ""

    @property
    def month(self) -> str:
        return self.departure_date.strftime("%Y-%m")

    @property
    def trip_days(self) -> Optional[int]:
        if self.return_date is None:
            return None
        return (self.return_date - self.departure_date).days

    def to_dict(self) -> dict:
        d = asdict(self)
        d["departure_date"] = self.departure_date.isoformat()
        d["return_date"] = self.return_date.isoformat() if self.return_date else None
        return d
