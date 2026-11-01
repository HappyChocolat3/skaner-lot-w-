"""Główna logika: dla każdego odcinka trasy pobiera ceny, wybiera najtańszą ofertę na miesiąc i buduje raport."""

import html
import logging
import os
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from .airports import HOME, describe
from .config import Config, Leg
from .models import Offer
from .providers import Provider
from .storage import State

log = logging.getLogger(__name__)

MONTHS_SHORT = ["sty", "lut", "mar", "kwi", "maj", "cze", "lip", "sie", "wrz", "paź", "lis", "gru"]


@dataclass
class Alert:
    kind: str  # "drop" | "below"
    route: str  # id odcinka, np. "PL>LAS"
    month: str
    offer: dict
    previous: float | None = None


def scan_months(today: date, months_ahead: int, until: str | None = None, since: str | None = None) -> list[str]:
    """Miesiące od bieżącego (albo od `since`, jeśli później): do `until` (YYYY-MM) włącznie
    albo `months_ahead` sztuk."""
    y, m = today.year, today.month
    if since and since > f"{y:04d}-{m:02d}":
        y, m = map(int, since.split("-"))
    result = []
    while (until and f"{y:04d}-{m:02d}" <= until) or (not until and len(result) < months_ahead):
        result.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return result


def offer_ok(offer: Offer, cfg: Config) -> bool:
    s = cfg.search
    if s.max_transfers is not None and offer.transfers > s.max_transfers:
        return False
    return offer.price > 0


def effective_price(offer: Offer, cfg: Config) -> float:
    """Cena biletu + dojazd do lotniska wylotu albo z lotniska przylotu (np. Berlin, Praga)."""
    extra = cfg.search.extra_cost
    return offer.price + extra.get(offer.origin, 0) + extra.get(offer.destination, 0)


def leg_label(leg: Leg) -> str:
    a, b = leg.id.split(">")
    return f"{describe(a)} → {describe(b)}"


def scan(cfg: Config, provider: Provider, state: State, today: date | None = None,
         request_delay: float = 0.2) -> list[Alert]:
    today = today or date.today()
    months = scan_months(today, cfg.search.months_ahead, cfg.search.until, cfg.search.since)
    legs = cfg.search.legs()
    state.keep_routes([leg.id for leg in legs])
    state.prune_before(months[0])
    _reset_minima_if_filters_changed(cfg, state)
    state.data["legs"] = [{"id": leg.id, "label": leg_label(leg)} for leg in legs]
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    alerts: list[Alert] = []

    for leg in legs:
        for month in months:
            offers: list[Offer] = []
            for origin in leg.origins:
                for dest in leg.destinations:
                    try:
                        found = provider.search_month(origin, dest, month, True, cfg.search.currency)
                    except Exception as e:  # jedno lotnisko nie może zatrzymać całego skanu
                        log.warning("Błąd %s→%s %s: %s", origin, dest, month, e)
                        found = []
                    # API czasem zwraca loty spoza zapytanego miesiąca – filtrujemy
                    offers += [o for o in found if o.month == month and offer_ok(o, cfg)]
                    if request_delay:
                        time.sleep(request_delay)

            entry = state.month(leg.id, month)
            entry["checked_at"] = now
            if not offers:
                entry["current"] = None
                continue

            best = min(offers, key=lambda o: effective_price(o, cfg))
            record = best.to_dict() | {"effective_price": effective_price(best, cfg), "found_at": now}
            entry["current"] = record
            alert = _decide(cfg, entry, record, leg.id, month)
            if alert:
                alerts.append(alert)
            log.info("%s %s: %.0f %s (%s→%s)", leg.id, month, best.price, best.currency, best.origin, best.destination)

    return alerts


def _filters_signature(cfg: Config) -> str:
    s = cfg.search
    return f"one_way;transfers={s.max_transfers};{s.currency}"


def _reset_minima_if_filters_changed(cfg: Config, state: State) -> None:
    """Po zmianie filtrów stare minima nie są porównywalne z nowymi ofertami – zaczynamy od nowa."""
    sig = _filters_signature(cfg)
    if state.data.get("filters") != sig and state.data["routes"]:
        for months in state.data["routes"].values():
            for entry in months.values():
                entry.pop("best", None)
                entry.pop("last_alert_price", None)
        log.info("Zmienione filtry (%s) – resetuję zapamiętane minima", sig)
    state.data["filters"] = sig


def _decide(cfg: Config, entry: dict, record: dict, route: str, month: str) -> Alert | None:
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
        return Alert("drop", route, month, record, previous=last_alert)
    if cfg.notify.alert_below and eff <= cfg.notify.alert_below < last_alert:
        entry["last_alert_price"] = eff
        return Alert("below", route, month, record, previous=last_alert)
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
    months = scan_months(now.date(), cfg.search.months_ahead, cfg.search.until, cfg.search.since)
    drops = {(a.route, a.month): a for a in alerts}
    legs = cfg.search.legs()
    stops = [describe(HOME)] + [describe(d).split(" (")[0] for d in cfg.search.destinations] + [describe(HOME)]
    period = f", {_short_month(months[0])} – {_short_month(months[-1])}" if months else ""
    lines = [
        f"✈️ <b>Raport lotów: {html.escape(' → '.join(stops))}</b>",
        f"{now.strftime('%d.%m.%Y, %H:%M')} · loty w jedną stronę{period}",
    ]
    if drops:
        lines.append("🔥 = nowa najniższa cena")

    for n, leg in enumerate(legs, 1):
        route = state.data["routes"].get(leg.id, {})
        offers = [(m, route[m]) for m in months if route.get(m, {}).get("current")]
        top = sorted(offers, key=lambda x: x[1]["current"]["effective_price"])[: cfg.notify.report_top]
        lines += ["", f"<b>{n}. {html.escape(leg_label(leg))}</b>"]
        if not top:
            lines.append("Brak ofert.")
        for month, entry in top:
            lines.append("• " + _format_offer(leg, entry["current"], entry.get("best"), drops.get((leg.id, month))))
        if len(offers) > len(top):
            lines.append(f"…i {_more_months(len(offers) - len(top))} {_page_link('na stronie')}")
    return "\n".join(lines)


def _format_offer(leg: Leg, o: dict, best: dict | None, alert: Alert | None) -> str:
    dep = date.fromisoformat(o["departure_date"]).strftime("%d.%m.%Y")
    # przy lotniskach domowych pokazujemy nazwę (wybór lotniska jest ważny), w pozostałych sam kod
    a, b = leg.id.split(">")
    origin = describe(o["origin"]) if a == HOME else o["origin"]
    dest = describe(o["destination"]) if b == HOME else o["destination"]
    line = f"<b>{dep}</b>: {_fmt(o['price'])} {o['currency']} · {html.escape(origin)} → {html.escape(dest)}"
    extra = o["effective_price"] - o["price"]
    if extra:
        line += f" (+{_fmt(extra)} dojazd)"
    line += " · bezpośredni" if o.get("transfers", 0) == 0 else f" · przesiadki: {o['transfers']}"
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
