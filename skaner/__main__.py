"""CLI skanera.

  python -m skaner run              # jeden skan (np. z crona / GitHub Actions)
  python -m skaner loop --hours 6   # działa w tle i skanuje co N godzin
  python -m skaner airports         # lista obsługiwanych lotnisk
  python -m skaner test-notify      # wysyła testową wiadomość na WhatsApp
"""

import argparse
import logging
import sys
import time

from .airports import AIRPORTS
from .config import load_config
from .notifier import build_notifier
from .providers import build_provider
from .scanner import format_alerts, scan
from .storage import State

log = logging.getLogger("skaner")


def run_once(args) -> int:
    cfg = load_config(args.config)
    if args.dest:
        cfg.search.destinations = [d.upper() for d in args.dest]
    notifier = build_notifier("console" if args.dry_run else cfg.notify.channel)
    provider = build_provider(cfg.provider_name, cfg.provider_settings)
    state = State(args.state)

    alerts = scan(cfg, provider, state)
    message = format_alerts(alerts)
    if message:
        # najpierw wysyłka, potem zapis – jeśli wysyłka padnie, alert zostanie ponowiony
        notifier.send(message)
        log.info("Wysłano %d powiadomień", len(alerts))
    else:
        log.info("Brak nowych najniższych cen")
    if not args.dry_run:
        state.save()
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="skaner", description="Skaner najtańszych lotów")
    parser.add_argument("--config", default="config.toml")
    parser.add_argument("--state", default="data/state.json")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)

    for name in ("run", "loop"):
        p = sub.add_parser(name)
        p.add_argument("--dest", nargs="+", help="nadpisz cele z configu, np. --dest LAS JFK")
        p.add_argument("--dry-run", action="store_true", help="wypisz zamiast wysyłać, nie zapisuj stanu")
    sub.choices["loop"].add_argument("--hours", type=float, default=6)
    sub.add_parser("airports")
    sub.add_parser("test-notify")

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if args.cmd == "airports":
        for a in AIRPORTS.values():
            print(f"{a.code}  {a.country}  {a.city}")
        return 0
    if args.cmd == "test-notify":
        build_notifier(load_config(args.config).notify.channel).send("✈️ Skaner lotów: test powiadomienia działa!")
        return 0
    if args.cmd == "run":
        return run_once(args)

    while True:
        try:
            run_once(args)
        except Exception:
            log.exception("Skan nie powiódł się, spróbuję ponownie przy następnym cyklu")
        time.sleep(args.hours * 3600)


if __name__ == "__main__":
    sys.exit(main())
