import io
import json
import tempfile
import unittest
import urllib.parse
from unittest import mock
from datetime import date, datetime
from pathlib import Path

from skaner.airports import describe
from skaner.config import Config, NotifyConfig, SearchConfig, load_config
from skaner.models import Offer
from skaner.notifier import TelegramNotifier, split_message
from skaner.providers.base import Provider
from skaner.providers.travelpayouts import TravelpayoutsProvider
from skaner.scanner import _month_ranges, format_report, report_slot, scan, scan_months
from skaner.storage import State

TODAY = date(2026, 10, 18)


class FakeProvider(Provider):
    def __init__(self, prices):
        # prices: {(origin, month): [(price, dep_day, trip_days, transfers)]}
        self.prices = prices

    def search_month(self, origin, destination, month, one_way, currency):
        y, m = map(int, month.split("-"))
        out = []
        for price, day, trip, transfers in self.prices.get((origin, month), []):
            dep = date(y, m, day)
            out.append(Offer(origin, destination, price, currency, dep,
                             date.fromordinal(dep.toordinal() + trip), "LO", transfers, transfers,
                             f"https://example.com/{origin}{month}"))
        return out


def make_cfg(**notify):
    return Config(
        search=SearchConfig(destinations=["LAS"], origins=["WAW", "BER"], months_ahead=2,
                            max_transfers=2, min_trip_days=7, max_trip_days=21,
                            extra_cost={"BER": 150}),
        notify=NotifyConfig(channel="console", **notify),
        provider_name="fake",
        provider_settings={},
    )


class ScannerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state_path = Path(self.tmp.name) / "state.json"

    def tearDown(self):
        self.tmp.cleanup()

    def run_scan(self, prices, cfg=None):
        state = State(self.state_path)
        alerts = scan(cfg or make_cfg(), FakeProvider(prices), state, today=TODAY, request_delay=0)
        state.save()
        return alerts

    def test_scan_months(self):
        self.assertEqual(scan_months(date(2026, 11, 5), 3), ["2026-11", "2026-12", "2027-01"])
        months = scan_months(date(2026, 10, 19), 12, until="2028-12")
        self.assertEqual((months[0], months[-1], len(months)), ("2026-10", "2028-12", 27))

    def test_only_real_drops_are_flagged(self):
        prices = {("WAW", "2026-10"): [(3000, 20, 10, 1)], ("WAW", "2026-11"): [(2800, 5, 14, 1)]}
        # pierwsze ceny to punkt odniesienia, nie spadek
        self.assertEqual(self.run_scan(prices), [])
        self.assertEqual(self.run_scan(prices), [])

        # spadek o 1% (< min_drop_percent) -> bez oznaczenia
        prices[("WAW", "2026-11")] = [(2772, 5, 14, 1)]
        self.assertEqual(self.run_scan(prices), [])

        # kolejny spadek: łącznie > 2% od ostatnio oznaczonej ceny
        prices[("WAW", "2026-11")] = [(2700, 5, 14, 1)]
        alerts = self.run_scan(prices)
        self.assertEqual([(a.kind, a.month) for a in alerts], [("drop", "2026-11")])
        self.assertEqual(alerts[0].previous, 2800)

        # wzrost ceny -> minimum zostaje
        prices[("WAW", "2026-11")] = [(3500, 5, 14, 1)]
        self.assertEqual(self.run_scan(prices), [])
        data = json.loads(self.state_path.read_text())
        self.assertEqual(data["routes"]["LAS"]["2026-11"]["best"]["price"], 2700)
        self.assertEqual(data["routes"]["LAS"]["2026-11"]["current"]["price"], 3500)

    def test_extra_cost_and_filters(self):
        prices = {
            # BER tańszy o 100, ale z dojazdem (150) droższy
            ("BER", "2026-10"): [(2900, 20, 10, 1)],
            ("WAW", "2026-10"): [
                (3000, 20, 10, 1),
                (1000, 20, 3, 1),   # za krótki pobyt
                (1100, 20, 10, 3),  # za dużo przesiadek
            ],
        }
        self.run_scan(prices)
        current = State(self.state_path).data["routes"]["LAS"]["2026-10"]["current"]
        self.assertEqual((current["origin"], current["price"]), ("WAW", 3000))

    def test_provider_error_does_not_stop_scan(self):
        class Broken(FakeProvider):
            def search_month(self, origin, *a):
                if origin == "BER":
                    raise RuntimeError("boom")
                return super().search_month(origin, *a)

        state = State(self.state_path)
        scan(make_cfg(), Broken({("WAW", "2026-10"): [(3000, 20, 10, 1)]}), state, today=TODAY, request_delay=0)
        self.assertEqual(state.data["routes"]["LAS"]["2026-10"]["current"]["price"], 3000)

    def test_report(self):
        prices = {("BER", "2026-11"): [(2600, 3, 14, 1)]}
        self.run_scan(prices)
        prices[("BER", "2026-11")] = [(2500, 3, 14, 0)]
        alerts = self.run_scan(prices)
        msg = format_report(make_cfg(), State(self.state_path), alerts, datetime(2026, 10, 19, 12, 1))
        self.assertIn("<b>Raport lotów: Las Vegas (LAS)</b>", msg)
        self.assertIn("19.10.2026, 12:01 · w obie strony, 7–21 dni", msg)
        self.assertIn("🔥 <b>lis 2026</b>: 2 500 PLN · Berlin (BER) +150 dojazd · 03.11–17.11 (14 dni)", msg)
        self.assertIn("bezpośredni", msg)
        self.assertIn('<a href="https://example.com/BER2026-11">oferta</a> (-4%)', msg)
        self.assertIn("Brak ofert: paź 2026", msg)

        # cena wyżej niż minimum -> pokazujemy minimum, bez 🔥
        prices[("BER", "2026-11")] = [(2900, 3, 14, 1)]
        alerts = self.run_scan(prices)
        msg = format_report(make_cfg(), State(self.state_path), alerts, datetime(2026, 10, 19, 15, 0))
        self.assertNotIn("🔥", msg)
        self.assertIn("przesiadki: 1", msg)
        self.assertIn("min. dotąd 2 500", msg)

    def test_month_ranges(self):
        months = scan_months(date(2026, 10, 1), 12, until="2028-12")
        empty = ["2026-10", "2027-01", "2027-02", "2027-03"] + months[months.index("2027-05"):]
        self.assertEqual(_month_ranges(empty, months), "paź 2026, sty–mar 2027, maj 2027 – gru 2028")

    def test_report_slot(self):
        hours = [9, 12, 15, 18]
        day = datetime(2026, 10, 19)
        slot = lambda h, m: report_slot(day.replace(hour=h, minute=m), hours)
        self.assertIsNone(slot(8, 45))
        self.assertEqual(slot(8, 55), "2026-10-19 09")  # chwilę przed czasem, bo skan trwa
        self.assertEqual(slot(9, 50), "2026-10-19 09")
        self.assertEqual(slot(11, 0), "2026-10-19 09")
        self.assertIsNone(slot(11, 10))                  # za późno na raport z 9:00
        self.assertEqual(slot(11, 55), "2026-10-19 12")
        self.assertEqual(slot(19, 30), "2026-10-19 18")
        self.assertIsNone(slot(22, 42))

    def test_past_months_pruned(self):
        state = State(self.state_path)
        state.month("LAS", "2026-09")["best"] = {"effective_price": 1}
        scan(make_cfg(), FakeProvider({}), state, today=TODAY, request_delay=0)
        self.assertNotIn("2026-09", state.data["routes"]["LAS"])


class ConfigTest(unittest.TestCase):
    def test_settings_override_destinations(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Path(tmp) / "settings.json"
            settings.write_text('{"destinations": ["BKK", "NYC"]}')
            self.assertEqual(load_config("config.toml", settings).search.destinations, ["BKK", "NYC"])
            self.assertEqual(load_config("config.toml", Path(tmp) / "brak.json").search.destinations, ["LAS"])

    def test_destination_names_from_catalog(self):
        self.assertEqual(describe("BKK"), "Bangkok (BKK)")
        self.assertEqual(describe("XYZ"), "XYZ")


class TravelpayoutsParseTest(unittest.TestCase):
    def test_parse(self):
        item = {
            "origin": "WAW", "destination": "LAS", "origin_airport": "WMI",
            "destination_airport": "LAS", "price": 2349, "airline": "LO",
            "departure_at": "2026-12-03T10:15:00+01:00", "return_at": "2026-12-17T18:00:00-08:00",
            "transfers": 1, "return_transfers": 2, "link": "/search/WMI0312LAS17121",
        }
        o = TravelpayoutsProvider._parse(item, "PLN")
        self.assertEqual((o.origin, o.price, o.trip_days, o.return_transfers), ("WMI", 2349, 14, 2))
        self.assertEqual(o.link, "https://www.aviasales.com/search/WMI0312LAS17121")
        self.assertIsNone(TravelpayoutsProvider._parse({"price": 1}, "PLN"))


class TelegramTest(unittest.TestCase):
    def test_send_posts_html_message(self):
        sent = []

        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

        def fake_urlopen(url, data=None, timeout=None):
            sent.append((url, urllib.parse.parse_qs(data.decode())))
            return Resp(b'{"ok": true}')

        with mock.patch("skaner.notifier.urllib.request.urlopen", fake_urlopen):
            TelegramNotifier("123:abc", "42").send("<b>test</b>")
        url, params = sent[0]
        self.assertEqual(url, "https://api.telegram.org/bot123:abc/sendMessage")
        self.assertEqual(params["chat_id"], ["42"])
        self.assertEqual(params["parse_mode"], ["HTML"])
        self.assertEqual(params["text"], ["<b>test</b>"])

    def test_requires_credentials(self):
        with self.assertRaises(ValueError):
            TelegramNotifier("", "42")


class SplitTest(unittest.TestCase):
    def test_split(self):
        lines = ["x" * 600] * 15
        chunks = split_message("\n".join(lines), limit=1500)
        self.assertTrue(all(len(c) <= 1500 for c in chunks))
        self.assertEqual("\n".join(chunks), "\n".join(lines))
