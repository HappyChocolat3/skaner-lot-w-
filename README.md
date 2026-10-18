# skaner-lot-w-

Skaner najtańszych lotów, który działa w tle. Sprawdza ceny lotów z polskich lotnisk
(oraz przygranicznych w Czechach i Niemczech) do wybranego celu, domyślnie **Las Vegas (LAS)**.
Gdy cena na któryś miesiąc spadnie do nowego minimum, wysyła powiadomienie na **WhatsApp**.

Przykładowe powiadomienie:

```
✈️ *Nowe najniższe ceny lotów!*

*Las Vegas (LAS) – listopad 2026*: 2 499 PLN (-7% względem poprzedniego minimum)
Wylot Berlin (BER) 2026-11-03, powrót 2026-11-15 (12 dni)
Przesiadki: 1/1, linia: LO
Z dojazdem na lotnisko: ~2 649 PLN
https://www.aviasales.com/search/...
```

## Jak to działa

1. Co 6 godzin (GitHub Actions) skaner pyta o ceny dla każdej pary *lotnisko wylotu → cel*
   na każdy z najbliższych 12 miesięcy.
2. Odrzuca oferty niespełniające filtrów: liczby przesiadek i długości pobytu.
3. Dla każdego miesiąca wybiera najtańszą ofertę. Przy porównaniu dolicza koszt dojazdu
   do lotnisk zagranicznych (`extra_cost`).
4. Porównuje ją z historią w `data/state.json`. Jeśli to nowe minimum, niższe o co najmniej
   `min_drop_percent` od ostatnio zgłoszonej ceny, wysyła WhatsApp.

**Źródło cen:** [Travelpayouts / Aviasales Data API](https://www.travelpayouts.com/).
Jest darmowe i zbiera ceny z wyszukiwań w setkach linii lotniczych i agencji.
Bezpośrednie scrapowanie Skyscannera czy Google Flights jest zawodne, bo strony blokują
boty, i łamie ich regulamin. Dlatego źródła są osobnymi „providerami” (`skaner/providers/`)
i łatwo dodać kolejne (np. Kiwi Tequila, SerpApi Google Flights).

> Ceny z Travelpayouts to ceny znalezione niedawno w wyszukiwaniach, nie ceny „na żywo”.
> Przed zakupem zawsze sprawdź cenę pod linkiem.

## Konfiguracja krok po kroku

### 1. Token Travelpayouts (darmowy)
Załóż konto na <https://www.travelpayouts.com/>. Token API znajdziesz w
*Profile → API token*.

### 2. WhatsApp przez CallMeBot (darmowy)
1. Dodaj do kontaktów numer bota podany na
   <https://www.callmebot.com/blog/free-api-whatsapp-messages/>
   (numer czasem się zmienia, więc sprawdź go na stronie).
2. Wyślij do niego na WhatsAppie wiadomość `I allow callmebot to send me messages`.
3. W odpowiedzi dostaniesz `apikey`.

Alternatywnie możesz użyć Twilio (`channel = "twilio"` w `config.toml`).

### 3. Uruchomienie w tle na GitHub Actions (zalecane)
W repozytorium na GitHubie wejdź w *Settings → Secrets and variables → Actions*
i dodaj sekrety:

| Sekret | Wartość |
|---|---|
| `TRAVELPAYOUTS_TOKEN` | token z kroku 1 |
| `WHATSAPP_PHONE` | Twój numer, np. `+48600123456` |
| `CALLMEBOT_APIKEY` | apikey z kroku 2 |

Workflow `.github/workflows/scan.yml` musi być na domyślnej gałęzi (`main`).
Uruchamia się wtedy co 6 godzin. Pierwszy skan możesz odpalić ręcznie:
*Actions → Skan lotów → Run workflow*. Przy pierwszym skanie przyjdzie podsumowanie
najtańszych cen na każdy miesiąc, a później tylko nowe minima.

### Alternatywa: uruchomienie lokalnie (Python 3.11+, bez dodatkowych bibliotek)

```bash
export TRAVELPAYOUTS_TOKEN=...
export WHATSAPP_PHONE=+48600123456
export CALLMEBOT_APIKEY=...

python -m skaner test-notify          # testowa wiadomość na WhatsApp
python -m skaner run --dry-run        # skan bez wysyłki (wynik w konsoli)
python -m skaner run                  # jeden skan
python -m skaner loop --hours 6       # działa w tle, skan co 6 godzin
```

## Dostosowanie (`config.toml`)

- **Inny cel:** `destinations = ["LAS", "JFK"]`, albo jednorazowo `python -m skaner run --dest BKK`.
- **Lotniska wylotowe:** lista `origins`. Wszystkie znane lotniska wypisze
  `python -m skaner airports`. `origins = ["ALL"]` oznacza wszystkie z listy.
- **Lot w jedną stronę:** `one_way = true`.
- **Filtry:** `max_transfers`, `min_trip_days`, `max_trip_days`.
- **Koszt dojazdu** do lotnisk w CZ/DE: sekcja `[search.extra_cost]`.
- **Czułość powiadomień:** `min_drop_percent`. Opcjonalnie `alert_below`, czyli
  powiadomienie, gdy cena spadnie poniżej podanej kwoty.

## Testy

```bash
python -m unittest discover -s tests
```
