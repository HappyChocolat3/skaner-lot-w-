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
from skaner.scanner import format_report, report_slot, scan, scan_months
from skaner.storage import State

TODAY = date(2026, 10, 18)


class FakeProvider(Provider):
    def __init__(self, prices):
        # prices: {(origin, destination, month): [(price, dep_day, transfers)]}
        self.prices = prices
        self.calls = []

    def search_month(self, origin, destination, month, one_way, currency):
        self.calls.append((origin, destination, month, one_way))
        y, m = map(int, month.split("-"))
        return [
            Offer(origin, destination, price, currency, date(y, m, day), None, "LO", transfers, 0,
                  f"https://example.com/{origin}{destination}{month}")
            for price, day, transfers in self.prices.get((origin, destination, month), [])
        ]


def make_cfg(**notify):
    return Config(
        search=SearchConfig(destinations=["LAS", "MIA"], origins=["WAW", "BER"], months_ahead=2,
                            max_transfers=2, extra_cost={"BER": 150}),
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

    def run_scan(self, prices, cfg=None, provider=None):
        state = State(self.state_path)
        alerts = scan(cfg or make_cfg(), provider or FakeProvider(prices), state, today=TODAY, request_delay=0)
        state.save()
        return alerts

    def route(self, leg, month):
        return State(self.state_path).data["routes"][leg][month]

    def test_scan_months(self):
        self.assertEqual(scan_months(date(2026, 11, 5), 3), ["2026-11", "2026-12", "2027-01"])
        months = scan_months(date(2026, 10, 19), 12, until="2028-12")
        self.assertEqual((months[0], months[-1], len(months)), ("2026-10", "2028-12", 27))
        months = scan_months(date(2026, 10, 19), 12, until="2028-12", since="2027-06")
        self.assertEqual((months[0], months[-1], len(months)), ("2027-06", "2028-12", 19))
        # gdy "since" już minął, liczymy od bieżącego miesiąca
        self.assertEqual(scan_months(date(2027, 8, 1), 12, until="2027-09", since="2027-06"), ["2027-08", "2027-09"])

    def test_legs_chain_one_way(self):
        legs = make_cfg().search.legs()
        self.assertEqual([l.id for l in legs], ["PL>LAS", "LAS>MIA", "MIA>PL"])
        self.assertEqual((legs[0].origins, legs[0].destinations), (("WAW", "BER"), ("LAS",)))
        self.assertEqual((legs[2].origins, legs[2].destinations), (("MIA",), ("WAW", "BER")))

        provider = FakeProvider({})
        self.run_scan({}, provider=provider)
        pairs = {(o, d) for o, d, _, _ in provider.calls}
        self.assertEqual(pairs, {("WAW", "LAS"), ("BER", "LAS"), ("LAS", "MIA"), ("MIA", "WAW"), ("MIA", "BER")})
        self.assertTrue(all(one_way for *_, one_way in provider.calls))

    def test_only_real_drops_are_flagged(self):
        prices = {("WAW", "LAS", "2026-10"): [(3000, 20, 1)], ("WAW", "LAS", "2026-11"): [(2800, 5, 1)]}
        # pierwsze ceny to punkt odniesienia, nie spadek
        self.assertEqual(self.run_scan(prices), [])
        self.assertEqual(self.run_scan(prices), [])

        # spadek o 1% (< min_drop_percent) -> bez oznaczenia
        prices[("WAW", "LAS", "2026-11")] = [(2772, 5, 1)]
        self.assertEqual(self.run_scan(prices), [])

        # kolejny spadek: łącznie > 2% od ostatnio oznaczonej ceny
        prices[("WAW", "LAS", "2026-11")] = [(2700, 5, 1)]
        alerts = self.run_scan(prices)
        self.assertEqual([(a.kind, a.route, a.month) for a in alerts], [("drop", "PL>LAS", "2026-11")])
        self.assertEqual(alerts[0].previous, 2800)

        # wzrost ceny -> minimum zostaje
        prices[("WAW", "LAS", "2026-11")] = [(3500, 5, 1)]
        self.assertEqual(self.run_scan(prices), [])
        entry = self.route("PL>LAS", "2026-11")
        self.assertEqual((entry["best"]["price"], entry["current"]["price"]), (2700, 3500))

    def test_filter_change_resets_minima(self):
        prices = {("WAW", "LAS", "2026-11"): [(2000, 5, 2), (2600, 5, 1)]}
        self.run_scan(prices)
        self.assertEqual(self.route("PL>LAS", "2026-11")["best"]["price"], 2000)

        cfg = make_cfg()
        cfg.search.max_transfers = 1
        self.run_scan(prices, cfg)
        entry = self.route("PL>LAS", "2026-11")
        self.assertEqual((entry["best"]["price"], entry["current"]["price"]), (2600, 2600))

    def test_old_routes_removed(self):
        state = State(self.state_path)
        state.month("LAX", "2026-11")["current"] = {"price": 1}
        state.save()
        self.run_scan({})
        data = State(self.state_path).data
        self.assertEqual(set(data["routes"]), {"PL>LAS", "LAS>MIA", "MIA>PL"})
        self.assertEqual(data["legs"][2], {"id": "MIA>PL", "label": "Miami (MIA) → Polska i okolice"})

    def test_extra_cost_both_ends_and_filters(self):
        prices = {
            # BER tańszy o 100, ale z dojazdem (150) droższy
            ("BER", "LAS", "2026-10"): [(2900, 20, 1)],
            ("WAW", "LAS", "2026-10"): [(3000, 20, 1), (1100, 20, 3)],  # 3 przesiadki – odpada
            # powrót: przylot do BER też liczy dojazd
            ("MIA", "BER", "2026-11"): [(1000, 3, 1)],
            ("MIA", "WAW", "2026-11"): [(1100, 3, 1)],
        }
        self.run_scan(prices)
        out = self.route("PL>LAS", "2026-10")["current"]
        self.assertEqual((out["origin"], out["price"]), ("WAW", 3000))
        back = self.route("MIA>PL", "2026-11")["current"]
        self.assertEqual((back["destination"], back["price"]), ("WAW", 1100))

    def test_provider_error_does_not_stop_scan(self):
        class Broken(FakeProvider):
            def search_month(self, origin, *a):
                if origin == "BER":
                    raise RuntimeError("boom")
                return super().search_month(origin, *a)

        self.run_scan({}, provider=Broken({("WAW", "LAS", "2026-10"): [(3000, 20, 1)]}))
        self.assertEqual(self.route("PL>LAS", "2026-10")["current"]["price"], 3000)

    def test_report(self):
        prices = {("BER", "LAS", "2026-11"): [(2600, 3, 1)], ("LAS", "MIA", "2026-11"): [(400, 8, 0)]}
        self.run_scan(prices)
        prices[("BER", "LAS", "2026-11")] = [(2500, 3, 1)]
        alerts = self.run_scan(prices)
        msg = format_report(make_cfg(), State(self.state_path), alerts, datetime(2026, 10, 19, 12, 1))
        self.assertIn("<b>Raport lotów: Polska i okolice → Las Vegas → Miami → Polska i okolice</b>", msg)
        self.assertIn("19.10.2026, 12:01 · loty w jedną stronę, paź 2026 – lis 2026", msg)
        self.assertIn("<b>1. Polska i okolice → Las Vegas (LAS)</b>", msg)
        self.assertIn("• 🔥 <b>03.11.2026</b>: 2 500 PLN · Berlin (BER) → LAS (+150 dojazd) · przesiadki: 1", msg)
        self.assertIn('<a href="https://example.com/BERLAS2026-11">oferta</a> (-4%)', msg)
        self.assertIn("<b>2. Las Vegas (LAS) → Miami (MIA)</b>\n• <b>08.11.2026</b>: 400 PLN · LAS → MIA · bezpośredni", msg)
        self.assertIn("<b>3. Miami (MIA) → Polska i okolice</b>\nBrak ofert.", msg)

        # cena wyżej niż minimum -> pokazujemy minimum, bez 🔥
        prices[("BER", "LAS", "2026-11")] = [(2900, 3, 1)]
        alerts = self.run_scan(prices)
        msg = format_report(make_cfg(), State(self.state_path), alerts, datetime(2026, 10, 19, 15, 0))
        self.assertNotIn("🔥", msg)
        self.assertIn("min. dotąd 2 500", msg)

    def test_report_shows_only_cheapest(self):
        cfg = make_cfg()
        cfg.search.months_ahead = 5
        prices = {("WAW", "LAS", m): [(p, 5, 1)] for m, p in
                  [("2026-10", 4000), ("2026-11", 3000), ("2026-12", 2500), ("2027-01", 3500), ("2027-02", 2800)]}
        self.run_scan(prices, cfg)
        msg = format_report(cfg, State(self.state_path), [], datetime(2026, 10, 19, 9, 0))
        first_leg = msg.split("<b>2.")[0]
        self.assertEqual([l.split("</b>")[0].split("<b>")[1] for l in first_leg.splitlines() if l.startswith("• ")],
                         ["05.12.2026", "05.02.2027", "05.11.2026"])
        self.assertIn("…i 2 droższe miesiące na stronie", msg)
        with mock.patch.dict("os.environ", {"GITHUB_REPOSITORY": "HappyChocolat3/skaner-lot-w-"}):
            msg = format_report(cfg, State(self.state_path), [], datetime(2026, 10, 19, 9, 0))
        self.assertIn('<a href="https://happychocolat3.github.io/skaner-lot-w-/">na stronie</a>', msg)

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
        state.month("PL>LAS", "2026-09")["best"] = {"effective_price": 1}
        scan(make_cfg(), FakeProvider({}), state, today=TODAY, request_delay=0)
        self.assertNotIn("2026-09", state.data["routes"]["PL>LAS"])


class ConfigTest(unittest.TestCase):
    def test_settings_override_destinations(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Path(tmp) / "settings.json"
            settings.write_text('{"destinations": ["BKK", "NYC"]}')
            self.assertEqual(load_config("config.toml", settings).search.destinations, ["BKK", "NYC"])
            self.assertEqual(load_config("config.toml", Path(tmp) / "brak.json").search.destinations, ["LAS", "MIA"])

    def test_destination_names_from_catalog(self):
        self.assertEqual(describe("BKK"), "Bangkok (BKK)")
        self.assertEqual(describe("XYZ"), "XYZ")
        self.assertEqual(describe("PL"), "Polska i okolice")


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
