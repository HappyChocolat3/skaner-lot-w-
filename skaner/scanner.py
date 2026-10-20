"""Główna logika: pobiera ceny, wybiera najtańszą ofertę na miesiąc i buduje raport."""

import html
import logging
import os
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from .airports import describe
from .config import Config
from .models import Offer
from .providers import Provider
from .storage import State

log = logging.getLogger(__name__)

MONTHS_SHORT = ["sty", "lut", "mar", "kwi", "maj", "cze", "lip", "sie", "wrz", "paź", "lis", "gru"]


@dataclass
class Alert:
    kind: str  # "drop" | "below"
    destination: str
    month: str
    offer: dict
    previous: float | None = None


def scan_months(today: date, months_ahead: int, until: str | None = None) -> list[str]:
    """Miesiące od bieżącego: do `until` (YYYY-MM) włącznie albo `months_ahead` sztuk."""
    result, y, m = [], today.year, today.month
    while (until and f"{y:04d}-{m:02d}" <= until) or (not until and len(result) < months_ahead):
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
    months = scan_months(today, cfg.search.months_ahead, cfg.search.until)
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
            alert = _decide(cfg, entry, record, dest, month)
            if alert:
                alerts.append(alert)
            log.info("%s %s: %.0f %s z %s", dest, month, best.price, best.currency, best.origin)

    return alerts


def _decide(cfg: Config, entry: dict, record: dict, dest: str, month: str) -> Alert | None:
    """Aktualizuje minimum dla miesiąca; zwraca Alert, gdy cena spadła wyraźnie."""
    eff = record["effective_price"]
    prev_best = entry.get("best")

    if prev_best is None:
        entry["best"] = record
        entry["last_alert_price"] = eff
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


def report_slot(now: datetime, hours: list[int], early_minutes: int = 5, max_late_minutes: int = 120) -> str | None:
    """Godzina raportu, w której okno właśnie trwa, np. '2026-10-19 12'.

    Okno zaczyna się chwilę przed pełną godziną (skan trwa kilka minut), a kończy po
    `max_late_minutes` – GitHub potrafi mocno opóźniać zaplanowane zadania, a raport
    „z 18:00” wysłany o 23 nie ma sensu.
    """
    for h in sorted(hours, reverse=True):
        at = now.replace(hour=h, minute=0, second=0, microsecond=0)
        if at - timedelta(minutes=early_minutes) <= now <= at + timedelta(minutes=max_late_minutes):
            return f"{now.date().isoformat()} {h:02d}"
    return None


def format_report(cfg: Config, state: State, alerts: list[Alert], now: datetime) -> str:
    months = scan_months(now.date(), cfg.search.months_ahead, cfg.search.until)
    drops = {(a.destination, a.month): a for a in alerts}
    s = cfg.search
    trip = "w jedną stronę" if s.one_way else "w obie strony"
    if not s.one_way and (s.min_trip_days or s.max_trip_days):
        trip += f", {s.min_trip_days or 1}–{s.max_trip_days or '∞'} dni"

    sections = []
    for dest in s.destinations:
        lines = [
            f"✈️ <b>Raport lotów: {html.escape(describe(dest))}</b>",
            f"{now.strftime('%d.%m.%Y, %H:%M')} · {trip}",
        ]
        route = state.data["routes"].get(dest, {})
        offers = [(m, route[m]) for m in months if route.get(m, {}).get("current")]
        top = sorted(offers, key=lambda x: x[1]["current"]["effective_price"])[: cfg.notify.report_top]
        if any((dest, m) in drops for m, _ in top):
            lines.append("🔥 = nowa najniższa cena")
        lines.append("")
        if not top:
            lines.append("Brak ofert na żaden miesiąc.")
        for i, (month, entry) in enumerate(top, 1):
            lines.append(f"{i}. " + _format_month(month, entry["current"], entry.get("best"), drops.get((dest, month))))
        if len(offers) > len(top):
            lines.append(f"…i {_more_months(len(offers) - len(top))} {_page_link('na stronie')}")
        sections.append("\n".join(lines))
    return "\n\n".join(sections)


def _format_month(month: str, o: dict, best: dict | None, alert: Alert | None) -> str:
    dep = date.fromisoformat(o["departure_date"])
    when = dep.strftime("%d.%m")
    if o.get("return_date"):
        ret = date.fromisoformat(o["return_date"])
        when += f"–{ret.strftime('%d.%m')} ({(ret - dep).days} dni)"
    origin = html.escape(describe(o["origin"]))
    extra = o["effective_price"] - o["price"]
    if extra:
        origin += f" +{_fmt(extra)} dojazd"
    line = f"<b>{_short_month(month)}</b>: {_fmt(o['price'])} {o['currency']} · {origin} · {when}"
    transfers = max(o.get("transfers", 0), o.get("return_transfers", 0))
    line += " · bezpośredni" if transfers == 0 else f" · przesiadki: {transfers}"
    if o.get("link"):
        line += f' · <a href="{html.escape(o["link"])}">oferta</a>'
    if alert:
        pct = (alert.previous - o["effective_price"]) / alert.previous * 100
        line = f"🔥 {line} (-{pct:.0f}%)"
    elif best and best["effective_price"] < o["effective_price"]:
        line += f" · min. dotąd {_fmt(best['price'])}"
    return line


def _more_months(n: int) -> str:
    if n == 1:
        return "1 droższy miesiąc"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return f"{n} droższe miesiące"
    return f"{n} droższych miesięcy"


def _page_link(text: str) -> str:
    """Link do strony na GitHub Pages (w GitHub Actions znamy repozytorium z GITHUB_REPOSITORY)."""
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" not in repo:
        return text
    owner, name = repo.split("/", 1)
    return f'<a href="https://{owner.lower()}.github.io/{name}/">{text}</a>'


def _short_month(month: str) -> str:
    y, m = month.split("-")
    return f"{MONTHS_SHORT[int(m) - 1]} {y}"


def _fmt(amount: float) -> str:
    return f"{amount:,.0f}".replace(",", " ")
