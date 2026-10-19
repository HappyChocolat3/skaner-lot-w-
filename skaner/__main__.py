"""CLI skanera.

  python -m skaner run              # skan + raport, jeśli wypada godzina raportu (np. z crona)
  python -m skaner run --force      # skan + raport od razu
  python -m skaner loop             # działa w tle i wysyła raporty o godzinach z configu
  python -m skaner airports         # lista obsługiwanych lotnisk
  python -m skaner test-notify      # wysyła testową wiadomość na Telegram
  python -m skaner telegram-chat-id # pokazuje chat_id (najpierw napisz coś do bota)
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from .airports import AIRPORTS
from .config import load_config
from .notifier import build_notifier, telegram_chat_ids
from .providers import build_provider
from .scanner import format_report, report_slot, scan
from .storage import State

log = logging.getLogger("skaner")


def run_once(args) -> int:
    cfg = load_config(args.config)
    if args.dest:
        cfg.search.destinations = [d.upper() for d in args.dest]
    state = State(args.state)
    now = datetime.now(ZoneInfo(cfg.notify.timezone))
    slot = report_slot(now, cfg.notify.report_hours)
    force = args.force or args.dry_run
    if not force and (slot is None or state.data.get("last_report") == slot):
        log.info("Nie pora na raport (%s), pomijam skan", now.strftime("%H:%M"))
        return 0

    notifier = build_notifier("console" if args.dry_run else cfg.notify.channel)
    provider = build_provider(cfg.provider_name, cfg.provider_settings)
    alerts = scan(cfg, provider, state, today=now.date())
    # najpierw wysyłka, potem zapis – jeśli wysyłka padnie, raport zostanie ponowiony
    notifier.send(format_report(cfg, state, alerts, now))
    log.info("Wysłano raport (%d nowych minimów)", len(alerts))
    if not args.dry_run:
        if slot:
            state.data["last_report"] = slot
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
        p.add_argument("--force", action="store_true", help="wyślij raport niezależnie od godziny")
    sub.choices["loop"].add_argument("--minutes", type=float, default=10, help="co ile minut sprawdzać godzinę")
    sub.add_parser("airports")
    sub.add_parser("test-notify")
    sub.add_parser("telegram-chat-id")

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
    if args.cmd == "telegram-chat-id":
        chats = telegram_chat_ids(os.environ.get("TELEGRAM_BOT_TOKEN", ""))
        if not chats:
            print("Brak wiadomości. Napisz coś do swojego bota na Telegramie i spróbuj ponownie.")
        for chat_id, name in chats:
            print(f"TELEGRAM_CHAT_ID={chat_id}  ({name})")
        return 0
    if args.cmd == "run":
        return run_once(args)

    while True:
        try:
            run_once(args)
        except Exception:
            log.exception("Skan nie powiódł się, spróbuję ponownie przy następnym cyklu")
        args.force = False  # --force dotyczy tylko pierwszego przebiegu
        time.sleep(args.minutes * 60)


if __name__ == "__main__":
    sys.exit(main())
