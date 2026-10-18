# skaner-lot-w-

Skaner najtańszych lotów, który działa w tle. Sprawdza ceny lotów z polskich lotnisk
(oraz przygranicznych w Czechach i Niemczech) do wybranego celu, domyślnie **Las Vegas (LAS)**.
Gdy cena na któryś miesiąc spadnie do nowego minimum, wysyła powiadomienie na **Telegram**.

Przykładowe powiadomienie:

```
✈️ Nowe najniższe ceny lotów!

Las Vegas (LAS) – listopad 2026: 2 499 PLN (-7% względem poprzedniego minimum)
Wylot Berlin (BER) 2026-11-03, powrót 2026-11-15 (12 dni)
Przesiadki: 1/1, linia: LO
Z dojazdem na lotnisko: ~2 649 PLN
Zobacz ofertę
```

## Jak to działa

1. Co 6 godzin (GitHub Actions) skaner pyta o ceny dla każdej pary *lotnisko wylotu → cel*
   na każdy z najbliższych 12 miesięcy.
2. Odrzuca oferty niespełniające filtrów: liczby przesiadek i długości pobytu.
3. Dla każdego miesiąca wybiera najtańszą ofertę. Przy porównaniu dolicza koszt dojazdu
   do lotnisk zagranicznych (`extra_cost`).
4. Porównuje ją z historią w `data/state.json`. Jeśli to nowe minimum, niższe o co najmniej
   `min_drop_percent` od ostatnio zgłoszonej ceny, wysyła wiadomość na Telegram.

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

### 2. Bot na Telegramie (darmowy)
1. W Telegramie otwórz czat z **@BotFather** i wyślij `/newbot`.
2. Podaj nazwę bota (dowolną) i jego login (musi kończyć się na `bot`, np. `moj_skaner_lotow_bot`).
3. BotFather odpowie **tokenem**, np. `123456789:AAH...`. To jest `TELEGRAM_BOT_TOKEN`.
4. Znajdź swojego nowego bota w Telegramie, kliknij **Start** i wyślij mu dowolną wiadomość.
5. Otwórz w przeglądarce `https://api.telegram.org/bot<TOKEN>/getUpdates`, wstawiając swój token
   w miejsce `<TOKEN>`. W odpowiedzi znajdź `"chat":{"id":123456789,...`. Ta liczba to
   `TELEGRAM_CHAT_ID`. Lokalnie to samo pokaże `python -m skaner telegram-chat-id`.

### 3. Uruchomienie w tle na GitHub Actions (zalecane)
W repozytorium na GitHubie wejdź w *Settings → Secrets and variables → Actions*
i dodaj sekrety:

| Sekret | Wartość |
|---|---|
| `TRAVELPAYOUTS_TOKEN` | token z kroku 1 |
| `TELEGRAM_BOT_TOKEN` | token od @BotFather |
| `TELEGRAM_CHAT_ID` | id czatu z kroku 2 |

Workflow `.github/workflows/scan.yml` musi być na domyślnej gałęzi (`main`).
Uruchamia się wtedy co 6 godzin. Pierwszy skan możesz odpalić ręcznie:
*Actions → Skan lotów → Run workflow*. Przy pierwszym skanie przyjdzie podsumowanie
najtańszych cen na każdy miesiąc, a później tylko nowe minima.

### Alternatywa: uruchomienie lokalnie (Python 3.11+, bez dodatkowych bibliotek)

```bash
export TRAVELPAYOUTS_TOKEN=...
export TELEGRAM_BOT_TOKEN=...
export TELEGRAM_CHAT_ID=...

python -m skaner test-notify          # testowa wiadomość na Telegram
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
