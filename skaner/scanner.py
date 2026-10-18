"""Główna logika: pobiera ceny, wybiera najtańszą ofertę na miesiąc i decyduje o powiadomieniu."""

import html
import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone

from .airports import describe
from .config import Config
from .models import Offer
from .providers import Provider
from .storage import State

log = logging.getLogger(__name__)

MONTHS_PL = [
    "styczeń", "luty", "marzec", "kwiecień", "maj", "czerwiec",
    "lipiec", "sierpień", "wrzesień", "październik", "listopad", "grudzień",
]


@dataclass
class Alert:
    kind: str  # "first" | "drop" | "below"
    destination: str
    month: str
    offer: dict
    previous: float | None = None


def months_from(today: date, count: int) -> list[str]:
    result, y, m = [], today.year, today.month
    for _ in range(count):
        result.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return result


def offer_ok(offer: Offer, cfg: Config) -> bool:
    s = cfg.search
    if s.max_transfers is not None and max(offer.transfers, offer.return_transfers) > s.max_transfers:
        return False
    days = offer.trip_days
    if days is not None:
        if s.min_trip_days and days < s.min_trip_days:
            return False
        if s.max_trip_days and days > s.max_trip_days:
            return False
    return offer.price > 0


def effective_price(offer: Offer, cfg: Config) -> float:
    return offer.price + cfg.search.extra_cost.get(offer.origin, 0)


def scan(cfg: Config, provider: Provider, state: State, today: date | None = None,
         request_delay: float = 0.2) -> list[Alert]:
    today = today or date.today()
    first_run = state.is_empty
    months = months_from(today, cfg.search.months_ahead)
    state.prune_before(months[0])
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    alerts: list[Alert] = []

    for dest in cfg.search.destinations:
        for month in months:
            offers: list[Offer] = []
            for origin in cfg.search.origins:
                try:
                    found = provider.search_month(origin, dest, month, cfg.search.one_way, cfg.search.currency)
                except Exception as e:  # jedno lotnisko nie może zatrzymać całego skanu
                    log.warning("Błąd %s→%s %s: %s", origin, dest, month, e)
                    found = []
                # API czasem zwraca loty spoza zapytanego miesiąca – filtrujemy
                offers += [o for o in found if o.month == month and offer_ok(o, cfg)]
                if request_delay:
                    time.sleep(request_delay)

            entry = state.month(dest, month)
            if not offers:
                entry["current"] = None
                entry["checked_at"] = now
                continue

            best = min(offers, key=lambda o: effective_price(o, cfg))
            record = best.to_dict() | {"effective_price": effective_price(best, cfg), "found_at": now}
            entry["current"] = record
            entry["checked_at"] = now
            alert = _decide(cfg, entry, record, dest, month, first_run)
            if alert:
                alerts.append(alert)
            log.info("%s %s: %.0f %s z %s", dest, month, best.price, best.currency, best.origin)

    return alerts


def _decide(cfg: Config, entry: dict, record: dict, dest: str, month: str, first_run: bool) -> Alert | None:
    eff = record["effective_price"]
    prev_best = entry.get("best")

    if prev_best is None:
        entry["best"] = record
        entry["last_alert_price"] = eff
        # nowy miesiąc, który wszedł w okno skanowania, zgłaszamy zawsze
        if cfg.notify.send_initial_summary or not first_run:
            return Alert("first", dest, month, record)
        return None

    prev_eff = prev_best["effective_price"]
    if eff >= prev_eff:
        return None

    entry["best"] = record
    last_alert = entry.get("last_alert_price", prev_eff)
    if eff <= last_alert * (1 - cfg.notify.min_drop_percent / 100):
        entry["last_alert_price"] = eff
        return Alert("drop", dest, month, record, previous=last_alert)
    if cfg.notify.alert_below and eff <= cfg.notify.alert_below < last_alert:
        entry["last_alert_price"] = eff
        return Alert("below", dest, month, record, previous=last_alert)
    return None


def month_label(month: str) -> str:
    y, m = month.split("-")
    return f"{MONTHS_PL[int(m) - 1]} {y}"


def _fmt(amount: float) -> str:
    return f"{amount:,.0f}".replace(",", " ")


def format_alerts(alerts: list[Alert]) -> str:
    if not alerts:
        return ""
    drops = [a for a in alerts if a.kind != "first"]
    firsts = [a for a in alerts if a.kind == "first"]
    parts = []
    if drops:
        parts.append("✈️ <b>Nowe najniższe ceny lotów!</b>")
        parts += [_format_one(a) for a in sorted(drops, key=lambda a: (a.destination, a.month))]
    if firsts:
        parts.append("📋 <b>Najtańsze loty na poszczególne miesiące</b>")
        parts += [_format_one(a) for a in sorted(firsts, key=lambda a: (a.destination, a.month))]
    return "\n\n".join(parts)


def _format_one(a: Alert) -> str:
    o = a.offer
    cur = o["currency"]
    dest = html.escape(describe(a.destination))
    head = f"<b>{dest} – {month_label(a.month)}</b>: {_fmt(o['price'])} {cur}"
    if a.previous:
        pct = (a.previous - o["effective_price"]) / a.previous * 100
        head += f" (-{pct:.0f}% względem poprzedniego minimum)"
    lines = [head]
    dep = f"Wylot {html.escape(describe(o['origin']))} {o['departure_date']}"
    if o.get("return_date"):
        days = (date.fromisoformat(o["return_date"]) - date.fromisoformat(o["departure_date"])).days
        dep += f", powrót {o['return_date']} ({days} dni)"
    lines.append(dep)
    transfers = f"{o['transfers']}" + (f"/{o['return_transfers']}" if o.get("return_date") else "")
    lines.append(f"Przesiadki: {transfers}" + (f", linia: {html.escape(o['airline'])}" if o.get("airline") else ""))
    if o["effective_price"] != o["price"]:
        lines.append(f"Z dojazdem na lotnisko: ~{_fmt(o['effective_price'])} {cur}")
    if o.get("link"):
        lines.append(f'<a href="{html.escape(o["link"])}">Zobacz ofertę</a>')
    return "\n".join(lines)
