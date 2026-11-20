# Nowy język {#languages}

Trener i Assist Router mają polski. Model nauczony po polsku rozumie polski; dla czeskiego,
angielskiego czy niemieckiego dane trzeba wygenerować w tym języku - a do tego potrzebne są dwa
**pakiety językowe**, jeden dla Assist Routera i jeden dla trenera. Ta strona jest dla osoby, która
zna język i chce go dodać - do większości pracy nie trzeba Pythona.

## Co zależy od języka {#what-depends}

| Część | Zależy od języka? | Gdzie |
|---|---|---|
| Prompty routera, sterowania i odpowiedzi, klucze JSON, co asystent mówi, słowa, które rozumie | tak | pakiet Assist Routera `custom_components/assist_router/languages/<kod>/` |
| Prompty nauczyciela, style, rozmowa, bełkot, zmyślone dane, halucynacje Whispera, odmiana w faktach testu | tak | pakiet trenera `router_trainer/languages/<kod>/` |
| Wbudowane intencje Home Assistanta | tak, gotowe | `home-assistant-intents` ma 57 języków |
| Piper i Whisper | wybierane same | głosy Pipera z kodem zaczynającym się od kodu języka; Whisper dostaje kod |
| Wikipedia (wiedza, streszczenia) | z ustawień | `wikipedia_language` w `router.yaml` |
| Ochrona testu, szum, normalizacja | nie | ogonki zdejmowane dla każdego języka z alfabetem łacińskim |
| Studio (ekran, przyciski) | nie - polski i angielski, wybór w ⚙ | `studio/www/i18n.js`, `ui/texts.py` |
| E2B / E4B, Gemma jako nauczyciel, Claude | nie | wielojęzyczne |
| Pisarz testu (`ollama.test_writer`) | wybór | Bielik jest polski - wybierz model, który pisze w tym języku |

**Język danych** wybierany jest jak w Home Assistancie: `language:` w `router.yaml`, a bez niego
język Home Assistanta z ostatniego pobrania (jeśli jest dla niego pakiet).

## Pakiet to katalog {#pack}

Oba pakiety mają ten sam układ. Komentarz nad każdym wpisem mówi, do czego służy.

| Plik | Co zawiera | Co robisz |
|---|---|---|
| `texts.yaml` | zdania i prompty, jako szablony `str.format` | tłumaczysz wartości; każde `{pole}` zostaje |
| `words.yaml` | listy słów i małe słowniki | tłumaczysz słowa; nazwy Home Assistanta zostają |
| `patterns.yaml` (tylko Assist Router) | wyrażenia regularne z przykładami `matches` / `not_matches` | tłumaczysz przykłady, potem wzorzec |
| `grammar.py` | funkcje zależne od gramatyki (liczba mnoga, daty, zmyślone dane) | tłumaczysz tekst w środku, dopasowujesz gramatykę |

Zasady, według których sprawdzany jest każdy pakiet (nazwy, `{pola}`, nazwy Home Assistanta, słowa
kluczy JSON, przykłady wzorców), są w przewodniku Assist Routera:
[Dodanie języka](https://witold-gren.github.io/home-assistant-assist-router/pl/languages/).

## Krok po kroku {#add}

### 1. Sprawdzony szkic: `router-trainer language new` {#new}

```bash
router-trainer language new cs           # na maszynie studia: docker compose exec studio …
router-trainer language new cs --home    # + nazwy czeskiego domu, w którym działa Home Assistant
```

Nauczyciel-**pisarz** ([Nauczyciel](teacher.md): lokalna Gemma, API, Claude albo ręcznie) tłumaczy z
polskiego, kawałek po kawałku, z materiałem wzorcowym: zdaniami, nazwami kolorów i odpowiedziami
samego Home Assistanta w tym języku (`home-assistant-intents`), a z `--home` pokojami i urządzeniami
domu. Każdy kawałek jest sprawdzany zaraz po powrocie:

- tekst zachowuje swoje `{pola}`;
- lista słów zachowuje typ i nazwy Home Assistanta (intencje, domeny, stany, wartości kolorów);
- wzorzec znajduje swoje przetłumaczone `matches` i żadnego z `not_matches`.

Co nie przejdzie, zostaje po polsku i trafia do `REVIEW.md`. Szkic ląduje w
`workspace/languages/<kod>/` - nigdy w repozytoriach:

| Plik | Co to jest |
|---|---|
| `router/` | pakiet Assist Routera |
| `trainer/` | pakiet trenera |
| `router.example.yaml` | przykładowy `router.yaml` z przetłumaczonymi tematami, `language: <kod>` |
| `model_test.yaml` | przypadki routera i sterowania z aktywnego testu, przetłumaczone; przypadki odpowiedzi pominięte - ich wzorce `must` / `never` wymagają osoby znającej język (albo napisz nowy test: `router-trainer testgen`) |
| `REVIEW.md` | co nie przeszło kontroli, co zawsze czyta osoba znająca język (gramatyka), gdzie skopiować pliki |
| `tasks.jsonl` | tylko przy ręcznym pisarzu: zadania tłumaczenia dla dowolnego czatu AI |

**Ręcznie**: przy `teacher.writer.provider: manual` nic nie jest nigdzie wysyłane; zadania trafiają
do `tasks.jsonl` (ten sam format co [przekazanie ręczne](teacher.md#manual)). Odpowiedz na nie w
dowolnym czacie AI i uruchom `router-trainer language new cs --answers odpowiedzi.jsonl`.

### 2. Osoba znająca język czyta szkic {#review}

Zacznij od `REVIEW.md`, w tej kolejności:

1. **Wzorce**, które nie znalazły swoich przykładów (`patterns.yaml`) - od nich zależy, czy polecenia
   i pytania w ogóle zostaną rozpoznane.
2. **`grammar.py`** obu pakietów - tekst jest przetłumaczony, gramatyka jest wciąż polska: liczba
   mnoga (`done_speech`), data czytana na głos (`format_now`, nazwy miesięcy), żeńskie formy
   odpowiedzi (`gendered`), zmyślone dane odpowiedzi (`given_scenario`).
3. **Prompty** w `texts.yaml` - jak poprosiłaby o to osoba mówiąca tym językiem.
4. **Listy słów** - czasowniki poleceń, słowa tak / nie, nazwy kolorów tak, jak mówią ludzie.

### 3. Sprawdzenie i kopiowanie {#check}

```bash
router-trainer language check cs   # oba pakiety szkicu; jedna linia na problem
```

Gdy oba mówią `ready`, skopiuj:

- `router/` → Assist Router `custom_components/assist_router/languages/cs/`, potem
  `tools/check_language.py` i `make test` tam;
- `trainer/` → `router_trainer/languages/cs/`, potem `router-trainer languages --check cs` i
  `make test`.

Oba katalogi wyślij jako pull requesty.

### 4. Użycie {#use}

W Home Assistancie: `router.yaml` z `router.example.yaml` (`language: cs`, Twoje tematy, pokoje i
osoby), model, który pisze w tym języku, test (`model_test.yaml` ze szkicu albo nowy). W
`trainer.yaml`: `ollama.test_writer` dla tego języka, `fallback_topic` i `intent_topics` z nazwami
tematów Twojego `router.yaml`. Potem pierwszy trening „Tylko wybór tematu” na małym zbiorze - i
przejrzyj `generated/router.jsonl` oraz `generated/labels_dropped.jsonl`: czy zdania brzmią
naturalnie?

Samo studio tłumaczy się osobno (nowy język ekranu): klucze w `studio/www/i18n.js` i `ui/texts.py`,
przewodnik w `docs/*.<kod>.md` i język w `mkdocs.yml`.
