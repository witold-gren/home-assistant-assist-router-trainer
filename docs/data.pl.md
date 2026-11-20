# Jak powstają dane {#data}

Ta strona opisuje, skąd biorą się przykłady do nauki i co się z nimi dzieje po drodze, krok po kroku. Przyda
się, gdy chcesz wytrenować model na **innym domu**: innych encjach, pokojach, automatyzacjach i domownikach.
Kod generatorów niczego nie zakłada o Waszym domu - wszystko, co domowe, przychodzi z Home Assistanta albo z
`trainer.yaml`. Lista rzeczy do przygotowania jest na końcu: [Nowy dom](#new-home).

Model uczy się trzech ról, każda ma własne dane:

| Rola | Wejście → wyjście | Plik danych |
|---|---|---|
| **router** | pytanie → temat z `router.yaml` | `generated/router.jsonl` |
| **sterowanie** | polecenie → JSON rozbioru polecenia (intencja, pokój, urządzenie, wartość) | `generated/control.jsonl` |
| **odpowiedzi** | pytanie + dane domu → krótka odpowiedź do przeczytania na głos | `generated/answers.jsonl` |

W trybie „Tylko wybór tematu” powstaje i trenuje się wyłącznie router.

Każdy przykład w zbiorze to **dokładnie ta rozmowa, którą wysyła Assist Router** (prompt systemowy i pytanie
użytkownika, zbudowane kodem routera w wersji z Twojego HA) plus odpowiedź, którą model ma dać. Dzięki temu
mały model uczy się na tym samym formacie, który dostanie w domu.

## Etap 1. Pobranie z Home Assistanta {#fetch}

„Pobierz z HA” w studiu (albo `router-trainer fetch`, albo pierwszy krok treningu automatycznego) łączy się z
Home Assistantem przez WebSocket tokenem **administratora** i wywołuje komendy Assist Routera tylko do odczytu.
Nic w HA nie jest zapisywane ani uruchamiane.

`assist_router/training/export` (Assist Router 0.1.8+) zwraca naraz:

| Co | Skąd w HA | Plik w `workspace/inputs/` | Do czego |
|---|---|---|---|
| `router.yaml` | `/config/assist/router.yaml` | `router.yaml` | tematy, opisy, przykłady, domownicy - podstawa wszystkiego |
| test | `/config/assist/model_test.yaml` (+ `_data`) | `model_test.yaml`, `model_test_data.yaml` | test z HA („ha”), nigdy do nauki |
| dziennik | `unrecognized_commands.csv` Assist Routera | `unrecognized_commands.csv` | prawdziwe pytania domowników |
| automatyzacje | wszystkie z wyzwalaczem `conversation`, także z `packages/` | `ha_config/automations.yaml` | zdania wyzwalaczy |
| własne zdania | `/config/custom_sentences/<język>/*.yaml` | `ha_config/custom_sentences/` | własne intencje |
| wersja i język | integracja Assist Router | `ha_export.json` | pobranie kodu routera tej samej wersji |

Potem trener pobiera z GitHuba **kod Assist Routera w wersji, którą ma HA** (`/data/router/<wersja>`). Z niego
bierze prompty, schematy odpowiedzi i parser poleceń - dzięki temu dane zawsze pasują do tego, co działa w domu.

**Nagrania głosu** (Assist Router 0.1.11+): jeśli w `configuration.yaml` HA jest

```yaml
assist_pipeline:
  debug_recording_dir: /share/assist_pipeline
```

HA zapisuje każde polecenie głosowe jako WAV (`<urządzenie>/<potok>/<przebieg>/01_stt….wav`). Komendy
`assist_router/training/recordings` (lista) i `assist_router/training/recording_files` (pliki w częściach po
4 MB) przenoszą je do `inputs/recordings/` - tylko te, których jeszcze nie ma. Nagrania wybudzenia
(`00_wake.wav`) nie są pobierane. Wyłącza to `generate.router.recordings: false`. Nagrania i ich tekst zostają
na maszynie z GPU.

## Etap 2. Migawka domu {#snapshot}

`snapshot` czyta z HA (REST, tym samym tokenem) encje **udostępnione Assistowi** z nazwami i aliasami,
pokoje, piętra, skrypty i sceny - tym samym kodem, którego używa test sterowania w repozytorium routera. Wynik:
`home/snapshot.json`. Z niego powstają nazwy urządzeń i pokoi w zdaniach oraz plany poleceń sterowania.

Dla nowego domu to najważniejsze miejsce: model nauczy się tylko tych nazw, które HA udostępnia Assistowi.
Dobre aliasy (np. „lampka” dla „Lampa przy kanapie”) od razu trafiają do danych.

## Etap 3. Test i zamrożenie {#test}

Test jest jedyną miarą modelu, więc **żadne zdanie testu nie trafia do nauki**, nawet lekko przerobione.

- **Test z HA** (`model_test.yaml`) albo **nowy test** (`testgen`): pisarz testu (`ollama.test_writer`, inny
  model niż nauczyciel) oznacza prawdziwe pytania z dziennika i dopisuje brakujące pytania, polecenia i pytania o
  Wikipedię; sędzia (nauczyciel) sprawdza każdy przypadek. Szczegóły: [Krok po kroku → Test](steps.md#test).
- `freeze` zapisuje zdania testu do `holdout/holdout.json`. Od tej chwili każde wygenerowane zdanie jest z nimi
  porównywane: po normalizacji (małe litery, bez ogonków i znaków) **identyczne** albo **podobne** - przez
  rdzenie słów (`holdout.word_similarity`, 0,8) lub trójki liter (`holdout.char_similarity`, 0,85) - odpada.

## Etap 4. Dane routera {#router}

Każdy wiersz pamięta swoje **źródło** (`source`), więc karta zbioru pokazuje, ile czego jest.

| Źródło | Jak powstaje | Temat |
|---|---|---|
| `trigger` | szablony hassil z wyzwalaczy `conversation` Waszych automatyzacji rozwinięte losowo (`per_template` zdań na szablon); `{zmienne}` dostają wartości z `slot_values`, a gdy ich brak - propozycje nauczyciela (zapisane w `generated/slot_values.json` do przejrzenia) | zdanie wzorcowe tematu (`command` w `router.yaml`), `topic_overrides`, a na końcu wybór nauczyciela (`generated/trigger_topics.json`) |
| `intent` | wbudowane intencje HA (`home-assistant-intents` dla języka routera) z nazwami Waszych urządzeń, pokoi i pięter (`native_intents`) | polecenia → temat z `control: true`; inne wg `intent_topics`, reszta → `fallback_topic` |
| `custom` | Wasze `custom_sentences` z HA, tak samo | jak `intent`; intencja Waszego `intent_script` - wybór nauczyciela albo `topic_overrides` `intent:<nazwa>` |
| `example` | przykłady tematów z `router.yaml` | swój temat |
| `external` | zdania napisane poza trenerem - w dowolnym czacie AI albo przez człowieka - z zadań [przekazania ręcznego](teacher.md#manual) | temat zadania - **po sprawdzeniu etykiety** |
| `paraphrase` | nauczyciel pisze po `paraphrases_per_topic` zdań na temat w sześciu stylach (krótkie, z kontekstem, z imionami, z błędami rozpoznawania mowy, od „a”/„słuchaj”, nieoczywiste), z podpowiedzią z pokojami i urządzeniami domu | swój temat - **po sprawdzeniu etykiety** (niżej) |
| `contrast` | zdania z obu stron granicy tematów, które się mylą ([pary kontrastowe](steps.md#auto)) | po sprawdzeniu etykiety |
| `knowledge` | pytania o losowe hasła Wikipedii języka routera (`knowledge`) | temat z `search` |
| `chat`, `gibberish` | rozmowa z pakietu językowego; bełkot ze zlepków sylab, napisów z filmów i urwanych zdań (`gibberish`) | `fallback_topic`; temat z `unclear: true` |
| `log` | prawdziwe pytania z dziennika, niepodobne do testu | nauczyciel z promptem routera |
| `recording` | Wasze nagrania przepisane przez Whispera domu; odpada to, co Whisper „słyszy” w ciszy (lista halucynacji w pakiecie językowym) | nauczyciel z promptem routera |
| `asr` | `asr_per_topic` naturalnych pytań na temat przeczytanych przez Pipera (wszystkie głosy języka po kolei) i zapisanych przez Whispera; zostają tylko te zapisane inaczej | temat oryginału |

**Sprawdzanie etykiet.** Nauczyciel pisze parafrazy, widząc jeden temat naraz, więc czasem napisze zdanie, które
`router.yaml` kieruje gdzie indziej. Każde jego zdanie czyta więc jeszcze raz **z pełnym promptem routera**
(wszystkie tematy i opisy); zdanie, które trafia do innego tematu, odpada razem ze swoimi kopiami z Whispera, a
parafrazy dopełniają brakujące (`check_labels`). Odrzucone są w `generated/labels_dropped.jsonl` - to najlepsza
lista niejasnych opisów tematów w `router.yaml`.

**Kto pisze i kto ocenia.** Zdania pisze nauczyciel-pisarz, a tematy i rozbiór sprawdza
nauczyciel-sędzia - każdy może być lokalną Gemmą, API, Claude albo pracą ręczną
([Nauczyciel](teacher.md)).

**Mowa.** Piper i Whisper to te same usługi, których używa HA (Wyoming, porty 10200 i 10300 hosta Ollamy domu
albo `generate.router.speech`). Bez nich oba źródła mowy są pomijane z komunikatem.

## Etap 5. Dane sterowania {#control}

1. Python **planuje polecenie** z migawki domu: intencja, pokój, urządzenie, wartość, kolor, muzyka, skrypt,
   lista (`control.labels` planów) - np. HassLightSet w kuchni na 40%.
2. Nauczyciel pisze `sentences_per_label` naturalnych zdań, które znaczą dokładnie to (poprawna odmiana, kilka
   stylów).
3. Nauczyciel **rozbiera każde zdanie** promptem i schematem parsera Assist Routera, a `parse_command` i
   `find_target` routera czytają odpowiedź. Zdanie zostaje tylko, gdy rozbiór zgadza się z planem i wskazuje
   zaplanowane urządzenie. Ta odpowiedź staje się odpowiedzią do nauki - etykieta jest sprawdzona dwa razy i ma
   dokładnie format z domu. Odrzucone: `generated/control_rejected.jsonl`.

Muzyka do poleceń „puść…” jest w `music` w `trainer.yaml` - dla nowego domu wpisz wykonawców i playlisty, których
słuchacie.

## Etap 6. Dane odpowiedzi {#answers}

- `given`: zmyślone dane (kieszonkowe, kalendarze, lekcje, samochód…) z faktami policzonymi w Pythonie; odpowiedź
  nauczyciela zostaje, gdy zawiera właściwe fakty i nie zawiera błędnych (ta sama kontrola co w teście).
- `live`: Wasze bieżące dane z HA zbudowane dokładnie tak jak integracja (`topic_data`) dla pytań napisanych dla
  tematu; sprawdzana forma (długość, bez markdownu, bez surowych stanów typu `unavailable`).
- `wikipedia`: streszczenia losowych artykułów (nigdy artykułów z testu) promptem streszczenia routera.

## Etap 7. Zbiór danych {#dataset}

`build` składa wszystko w `datasets/<nazwa>/`:

- zdania testu sprawdzane są jeszcze raz (lista odrzuconych w karcie);
- tematy routera: najpierw zdania naturalne, potem szablony; najwyżej `max_per_topic`, mniejsze dopełniane do
  `min_per_topic` kopiami z szumem; `noise` (30%) zdań dostaje szum rozpoznawania mowy (małe litery, bez
  ogonków, literówki, „JAkie”);
- duplikaty usuwane, role brane wg `dataset.mix`;
- część `dev` (strata walidacyjna) wybierana po skrócie tekstu (`dev_fraction`, 5%) - to samo zdanie zawsze po
  tej samej stronie, także po przebudowie z większą ilością danych;
- `card.json`: ile przykładów z jakiego źródła i roli.

Wszystkie etapy **wznawiają się**: to, co już powstało, zostaje, a odpowiedzi nauczyciela, Whispera i Pipera są
zapisane w `generated/*.json`. Ponowne uruchomienie dopisuje tylko brakujące.

## Nowy dom - lista kroków {#new-home}

Trener działa na każdym domu z Assist Routerem. Dla nowego domu:

1. **W Home Assistancie**
    - zainstaluj Assist Router (0.1.11+, żeby działały nagrania) i napisz `router.yaml` dla tego domu: `household`,
      `people`, tematy z opisami i 3-5 przykładami; temat z `control: true` (polecenia), z `search` (wiedza),
      z `unclear: true` (bełkot) i temat „wszystko inne”. Opisy tematów są najważniejsze - z nich korzysta i
      router w domu, i sprawdzanie etykiet;
    - udostępnij Assistowi encje, które mają być sterowane, i nadaj im aliasy, jakich używacie;
    - włącz `assist_pipeline: debug_recording_dir`, żeby zbierać nagrania (im dłużej dom żyje, tym więcej
      prawdziwej mowy);
    - utwórz token długoterminowy użytkownika-administratora.
2. **W studiu**: połącz Home Assistanta, „Pobierz z HA”.
3. **`trainer.yaml`** (Ustawienia w studiu):
    - `fallback_topic` i `intent_topics` - nazwy tematów z **Twojego** `router.yaml` (przykład ma polskie
      `inne` i `pogoda`);
    - `music` - Wasza muzyka;
    - `slot_values` - wartości `{zmiennych}` z wyzwalaczy, których nauczyciel nie zgadnie (np. imiona dzieci).
4. **Tematy wyzwalaczy**: `router-trainer triggers` wypisuje każdy wyzwalacz z kluczem `id#numer`, tematem i
   sposobem, w jaki go dostał (`override`, `reference`, `teacher`, `none`); `!!` oznacza temat, którego nie ma
   w `router.yaml`. Popraw złe w `topic_overrides` - pytanie o stan i polecenie w jednej automatyzacji mogą
   iść do różnych tematów (`asystent_alarm#0: alarm`, `asystent_alarm#2: sterowanie`).
5. **Test**: nowy dom zwykle nie ma `model_test.yaml` - wybierz „nowy test” (`testgen`); dziennik pytań na
   początku jest pusty, więc pisarz testu napisze pytania sam. Przejrzyj test w studiu.
6. **Trening automatyczny** - najpierw „Tylko wybór tematu”, E2B. Po walidacji przejrzyj
   `generated/labels_dropped.jsonl` i błędy w wynikach; popraw opisy tematów i powtórz - pary kontrastowe same
   wezmą błędy z poprzedniej walidacji.
7. Po kilku tygodniach życia domu: znów „Pobierz z HA” (dziennik i nagrania urosły) i nowy trening.

Nie trzeba pisać żadnego kodu: wszystko, co domowe, jest w `router.yaml`, HA i `trainer.yaml`. Kod pisze się tylko
dla **nowego języka** - patrz [Nowy język](languages.md).
