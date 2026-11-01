# skaner-lot-w-

Skaner najtańszych lotów, który działa w tle. Szuka lotów **w jedną stronę** po trasie:
z Polski (i lotnisk przy granicy w Czechach i Niemczech) przez wybrane miejsca, po kolei,
i z powrotem – domyślnie **Polska → Las Vegas → Miami → Polska**. Codziennie o **9, 12, 15 i 18**
wysyła na **Telegram** raport z 3 najtańszymi lotami na każdym odcinku, z wylotem od czerwca 2027
do grudnia 2028 (pełna lista miesięcy jest na stronie). 🔥 oznacza nową najniższą cenę.

Przykładowy raport:

```
✈️ Raport lotów: Polska i okolice → Las Vegas → Miami → Polska i okolice
01.11.2026, 09:00 · loty w jedną stronę, cze 2027 – gru 2028

1. Polska i okolice → Las Vegas (LAS)
• 15.09.2027: 1 914 PLN · Katowice (KTW) → LAS · przesiadki: 1 · oferta
• …

2. Las Vegas (LAS) → Miami (MIA)
• 08.11.2027: 454 PLN · LAS → MIA · bezpośredni · oferta
• …

3. Miami (MIA) → Polska i okolice
• 18.10.2027: 1 724 PLN · MIA → Berlin (BER) (+150 dojazd) · przesiadki: 1 · oferta
• …
```

Każdy odcinek to osobna lista najtańszych lotów – daty nie są ze sobą dopasowywane.

## Jak to działa

1. O 9, 12, 15 i 18 czasu polskiego (GitHub Actions) skaner pyta o ceny dla każdej pary
   *lotnisko wylotu → cel* na każdy miesiąc do `until` (domyślnie grudzień 2028).
   Linie sprzedają bilety ok. 11–12 miesięcy do przodu, więc dalsze miesiące pojawią się
   w raporcie, gdy tylko ruszy sprzedaż.
2. Odrzuca oferty niespełniające filtrów: liczby przesiadek i długości pobytu.
3. Dla każdego miesiąca wybiera najtańszą ofertę. Przy porównaniu dolicza koszt dojazdu
   do lotnisk zagranicznych (`extra_cost`).
4. Porównuje ją z historią w `data/state.json`. Jeśli to nowe minimum, niższe o co najmniej
   `min_drop_percent` od ostatnio oznaczonej ceny, oznacza miesiąc w raporcie 🔥.
5. Wysyła raport na Telegram.

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
Raporty przychodzą wtedy o 9, 12, 15 i 18. GitHub potrafi opóźniać, a nawet pomijać
zaplanowane zadania, dlatego workflow startuje co 10 minut i wysyła raport przy pierwszej
okazji. Raport spóźniony o ponad 2 godziny jest pomijany. Raport na żądanie:
*Actions → Skan lotów → Run workflow*.

### 4. Strona z cenami i wyborem trasy (GitHub Pages)
Strona w `docs/` pokazuje ceny na każdy miesiąc (wykres i lista ofert z linkami) i pozwala
wybrać, dokąd bot ma szukać lotów, także z telefonu.

1. Włącz GitHub Pages: *Settings → Pages → Build and deployment → Source: Deploy from a branch*,
   gałąź `main`, folder `/docs`, *Save*. Po minucie strona będzie pod adresem
   `https://<twój-login>.github.io/skaner-lot-w-/`.
2. Żeby zapisywać trasę, utwórz token na
   <https://github.com/settings/personal-access-tokens/new>: dostęp tylko do tego repozytorium,
   uprawnienia **Contents** i **Actions** ustawione na *Read and write*. Wklej go na stronie
   w sekcji „Połączenie z GitHubem”. Token zostaje tylko w Twojej przeglądarce.
3. Dodaj przystanki (po kolei) i kliknij **Zapisz i skanuj**. Strona zapisze je w `data/settings.json`
   i uruchomi skan, a raport przyjdzie na Telegram po kilku minutach.

Przystanki z `data/settings.json` mają pierwszeństwo przed listą w `config.toml`.

### Alternatywa: uruchomienie lokalnie (Python 3.11+, bez dodatkowych bibliotek)

```bash
export TRAVELPAYOUTS_TOKEN=...
export TELEGRAM_BOT_TOKEN=...
export TELEGRAM_CHAT_ID=...

python -m skaner test-notify          # testowa wiadomość na Telegram
python -m skaner run --dry-run        # skan bez wysyłki (wynik w konsoli)
python -m skaner run --force          # skan i raport od razu
python -m skaner loop                 # działa w tle, raporty o godzinach z configu
```

## Dostosowanie (`config.toml`)

- **Inna trasa:** najprościej na stronie (patrz wyżej) – przystanki po kolei. Bez strony:
  `data/settings.json` (`{"destinations": ["LAS", "MIA"]}`) albo jednorazowo
  `python -m skaner run --dest BKK`. Jeden przystanek = lot tam i osobno lot z powrotem.
  Nazwy celów na stronie i w raportach pochodzą z `data/destinations.json`.
- **Lotniska wylotowe:** lista `origins`. Wszystkie znane lotniska wypisze
  `python -m skaner airports`. `origins = ["ALL"]` oznacza wszystkie z listy.
- **Przesiadki:** `max_transfers` (maks. na jednym locie).
- **Koszt dojazdu** do lotnisk w CZ/DE: sekcja `[search.extra_cost]`.
- **Zakres miesięcy:** `since = "2027-06"` (od kiedy) i `until = "2028-12"` (do kiedy) albo `months_ahead = 12`.
- **Godziny raportów:** `report_hours = [9, 12, 15, 18]`. Po zmianie dopasuj też
  `cron` w `.github/workflows/scan.yml` (godziny w UTC; workflow startuje co 10 minut i sam
  sprawdza, czy to pora raportu).
- **Długość raportu:** `report_top = 3` – ile najtańszych ofert na odcinek trasy.
- **Oznaczenie 🔥:** `min_drop_percent`. Opcjonalnie `alert_below`, czyli oznaczenie,
  gdy cena spadnie poniżej podanej kwoty.

## Testy

```bash
python -m unittest discover -s tests
```
