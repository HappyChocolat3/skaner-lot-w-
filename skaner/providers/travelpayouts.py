"""Travelpayouts / Aviasales Data API (darmowe, wymaga tokenu z travelpayouts.com).

Zwraca najtańsze ceny znalezione przez użytkowników Aviasales w ostatnich dniach
(dane z setek linii lotniczych i agencji), więc nie trzeba scrapować stron.
"""

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date

from ..models import Offer
from .base import Provider

log = logging.getLogger(__name__)

API_URL = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"
SITE_URL = "https://www.aviasales.com"


class TravelpayoutsProvider(Provider):
    name = "travelpayouts"

    def __init__(self, token: str, market: str = "pl", limit: int = 30, max_retries: int = 3):
        if not token:
            raise ValueError("Brak tokenu Travelpayouts (zmienna TRAVELPAYOUTS_TOKEN)")
        self.token = token
        self.market = market
        self.limit = limit
        self.max_retries = max_retries

    def _get(self, params: dict) -> dict:
        url = f"{API_URL}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(
            url, headers={"X-Access-Token": self.token, "Accept-Encoding": "identity"}
        )
        for attempt in range(1, self.max_retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code == 429 or e.code >= 500:
                    time.sleep(2**attempt)
                    continue
                raise
            except urllib.error.URLError:
                if attempt == self.max_retries:
                    raise
                time.sleep(2**attempt)
        raise RuntimeError(f"Travelpayouts: przekroczono liczbę prób dla {params}")

    def search_month(self, origin, destination, month, one_way, currency):
        params = {
            "origin": origin,
            "destination": destination,
            "departure_at": month,
            "one_way": "true" if one_way else "false",
            "currency": currency.lower(),
            "market": self.market,
            "sorting": "price",
            "unique": "false",
            "limit": self.limit,
        }
        payload = self._get(params)
        if not payload.get("success", False):
            log.warning("Travelpayouts %s-%s %s: %s", origin, destination, month, payload.get("error"))
            return []
        return [o for o in (self._parse(item, currency) for item in payload.get("data", [])) if o]

    @staticmethod
    def _parse(item: dict, currency: str) -> Offer | None:
        try:
            dep = date.fromisoformat(item["departure_at"][:10])
            ret = date.fromisoformat(item["return_at"][:10]) if item.get("return_at") else None
            link = item.get("link") or ""
            return Offer(
                origin=item.get("origin_airport") or item["origin"],
                destination=item.get("destination_airport") or item["destination"],
                price=float(item["price"]),
                currency=currency.upper(),
                departure_date=dep,
                return_date=ret,
                airline=item.get("airline", ""),
                transfers=int(item.get("transfers") or 0),
                return_transfers=int(item.get("return_transfers") or 0),
                link=f"{SITE_URL}{link}" if link.startswith("/") else link,
                source="travelpayouts",
            )
        except (KeyError, ValueError, TypeError) as e:
            log.debug("Pomijam niepoprawny rekord %s: %s", item, e)
            return None
