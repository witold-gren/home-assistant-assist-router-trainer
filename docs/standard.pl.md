# Jeden standard {#standard}

Trener jest jedną z kilku aplikacji domu: studio słów budzących, Piper Voice Cloner, Edytor Home Dashboard,
Edytor Assist Router. Wszystkie stosują **wspólny standard** (`gpu-studio.md`). Dzięki niemu mają te same polecenia,
ten sam wygląd i zachowanie studia, dokumentację zbudowaną tak samo i te same zasady testów. Kto zna jedną aplikację,
od razu odnajdzie się w pozostałych.

Ta strona zbiera wszystko, co trzeba było w trenerze zmienić, żeby spełnić standard (listopad 2026). Szczegóły
każdej zmiany są w ostatnim rozdziale, „Lista zmian”.

## W skrócie {#summary}

| Obszar | Przed | Po |
|---|---|---|
| Gdzie działa | panel na stdlib HTTP na Ubuntu, sterowany z Maca przez SSH, usługa systemd | studio w Dockerze na maszynie z GPU, startuje razem z maszyną |
| Dane z Home Assistanta | pliki kopiowane z udziału Samby | komenda Assist Routera `assist_router/training/export` (tylko odczyt, przez API) |
| Kod routera | kopia z dysku Maca | tag z GitHuba w wersji, którą ma Home Assistant |
| Wygląd | własny panel z 5 krokami | studio jak w edytorach: drzewo, środek, karty na żywo, pasek górny |
| Ustawienia | ręczna edycja `trainer.yaml` | formularze, szkic, cofnij/ponów, zapis z różnicami, historia 30 wersji |
| Dokumentacja | statyczne strony HTML | MkDocs Material, PL i EN z tymi samymi kotwicami, zrzuty z dema |
| Polecenia | własne nazwy (`studio`, `studio-demo`, `show-login`…) | wspólne nazwy i grupy `make help` |
| Wypróbowanie | Python, uv i repozytorium routera na Macu | tylko Docker Desktop: `make demo` |
| Testy | 96 | 197 (w tym 18 w przeglądarce i 2 z Dockerem) |

## Studio w Dockerze {#docker}

- **Jeden obraz dla maszyny z GPU** (`docker/Dockerfile`), z warstwami od najwolniejszej do najszybszej:
  - pakiety systemowe;
  - środowiska z `scripts/setup.sh`: Home Assistant z zależnościami testów routera, Unsloth, Ollama trenera
    i llama.cpp;
  - na końcu kod. Zmiana kodu przebudowuje tylko ostatnią warstwę.
- **Samotesty** po każdej warstwie: importy obu środowisk i obecność przewodnika.
- **Przypięty torch** (`TORCH_SPEC`, domyślnie `torch==2.14.1` dla sterownika 580 / CUDA 13.0). Bez przypięcia pip
  bierze nowszą CUDA, której sterownik nie uruchomi.
- **Compose:**
  - użytkownik z UID/GID maszyny, healthcheck i `restart: unless-stopped`, więc studio wstaje razem z maszyną;
  - dane w `docker/data/`, login w `docker/config/env` (prawa 600).
- **`docker/install-ubuntu.sh`:**
  - sprawdza Dockera, Compose, uprawnienia, sterownik, NVIDIA Container Toolkit i wolne miejsce;
  - zapisuje login, włącza autostart Dockera, buduje i uruchamia studio;
  - wyłącza starą usługę `router-trainer.service`.
- **Usunięte:** tryb SSH, `deploy.py`, `scripts/deploy.sh`, `scripts/install-service.sh` i stary panel (kopie są
  w `backup/`).
- **Przewodnik w obrazie:** osobny etap `docs` buduje go z `--strict`, a studio podaje go pod `/docs/`, także bez
  internetu.

## Dane z Home Assistanta {#ha-data}

- W Assist Routerze doszła komenda `assist_router/training/export`. Działa tylko dla administratora i tylko
  odczytuje. Zwraca:
  - `router.yaml`;
  - dziennik nierozpoznanych zdań;
  - pliki testu;
  - automatyzacje z wyzwalaczem rozmowy, także z `packages/`;
  - pliki `custom_sentences`.
- Trenerowi wystarczą adres Home Assistanta i token. Udział Samby nie jest potrzebny.
- Studio porównuje wersję routera w Home Assistancie ze swoją. Kod tej wersji pobiera z GitHuba (`router_repo:
  auto`).

## Wygląd i zachowanie studia {#studio}

To samo co w pozostałych studiach i edytorach:

- **Pasek górny:**
  - ☰, ikona i nazwa;
  - chip zadania (etap, procent, czas do końca) i chip maszyny (GPU, temperatura, pamięć, wyłączenie);
  - odliczanie do wyłączenia z „Anuluj”, pigułka wersji routera, szkic, cofnij/ponów;
  - motyw, YAML, **?** (pełny przewodnik w nowej karcie), ustawienia, historia, zapis.
- **Trzy kolumny z przesuwanymi podziałkami:**
  - po lewej drzewo kroków z ✓ przy zrobionych;
  - pośrodku widok;
  - po prawej karty na żywo.
  - Kolumny zwijają się przyciskami ‹ › albo Ctrl/⌘+B i Ctrl/⌘+Alt+B. Stan zostaje po przeładowaniu, a w wąskim
    oknie prawa kolumna jest zwinięta od startu.
- **Pomoc w okienkach:** **?** karty otwiera małe okienko z opisem i linkiem do kotwicy przewodnika. Okienko
  zamykają ✕, Esc, kliknięcie obok albo ponowne **?**. Tylko **?** w pasku otwiera cały przewodnik.
- **Ustawienia jako formularze:**
  - zmiana pola podmienia tylko wartość w tekście `trainer.yaml`, więc komentarze zostają, a w różnicy jest jedna
    linia;
  - szkic, cofnij/ponów, zapis z różnicami i notatką, historia 30 wersji, konflikt przy równoczesnej zmianie.
- **Zadania:**
  - historia zadań z całym dziennikiem, stan „Przerwane”;
  - interaktywny wykres straty: podpowiedź kroku, pełny ekran, przybliżanie, przypięcie kroku;
  - „Wyłącz maszynę po zadaniu” z odliczaniem, które można anulować.
- **Logowanie** z blokadą po pięciu złych hasłach.

## Wydajność {#performance}

- Stan jest odpytywany dopiero po odpowiedzi na poprzednie pytanie, najwyżej jedno pytanie naraz. Karta w tle
  w ogóle nie pyta.
- Identyczny stan niczego nie przerysowuje.
- Każde pytanie ma limit czasu i kończy się czytelnym komunikatem: zwykle 20 s, „Wypróbuj” 920 s, „Pobierz router”
  320 s.
- Szkic zapisuje się jeden naraz. Zmiany z tego czasu idą jednym zapisem, a po błędzie nie ma pętli ponownych prób.
- Przegląd testu pokazuje po 150 przypadków. Wszystkie widoki na danych demo mieszczą się w 500 ms na zadanie.

## Dokumentacja {#docs}

- **Przewodnik od nowa w MkDocs Material**, angielski i polski, z tymi samymi kotwicami. Rozdziały:
  - Co to jest, Instalacja, Ekran, Krok po kroku;
  - Jak robić to dobrze (tabela wszystkich parametrów z wartościami z kodu), Home Assistant i zasilanie;
  - FAQ, ta strona, Zmiany.
- **Zrzuty** z dema w obu językach (`make screenshots`).
- **FAQ dla każdego znanego błędu:** dokładny komunikat, przyczyna i co zrobić. Każdy nowy błąd dopisujemy w obu
  językach.
- **„Wypróbuj na Macu”:** ta sama krótka sekcja w obu README i na stronie [Instalacja](installation.md#try-on-a-mac).
- **Sprawdzanie:** budowa z `--strict`, a testy pilnują nazw przycisków w tekście (muszą być prawdziwymi napisami
  studia), kotwic, obrazków i tabeli parametrów.
- Przewodnik trafia też na wspólną stronę dokumentacji domu, z zerem martwych linków.

## Polecenia make {#make}

Te same nazwy i grupy we wszystkich aplikacjach (`make help` po polsku albo angielsku):

| Grupa | Polecenia | Czego potrzebuje |
|---|---|---|
| 1. Start | `help`, `demo`, `demo-clean`, `docs`, `docs-serve`, `doctor` | tylko Docker Desktop |
| 2. Maszyna z GPU | `install`, `deploy`, `login`, `logs`, `status`, `docker-up/down/logs/shell`, `migrate`, `migrate-finish` | Docker Desktop, ssh, rsync |
| 3. Rozwój | `setup`, `demo-local`, `test`, `test-browser`, `test-docker`, `test-all`, `lint`, `format`, `docs-build`, `screenshots`, `icons`, `clean` | uv (sam pobiera Pythona `PYTHON_VERSION`) |
| 4. Bez studia | `fetch`, `router`, `smoke`, `testgen`, `data`, `train`, `resume`, `export`, `evaluate` | na maszynie, w kontenerze |

- Adres maszyny jest jeden dla wszystkich aplikacji: `~/.config/gpu-studio/host.mk`. Wyjątki trafiają do
  `Makefile.local`, który nie jest w git.
- **Zmienione nazwy:** `show-login` → `login`, `studio-demo` → `demo`, `studio-icons` → `icons`, `shell` →
  `docker-shell`. `make studio` zniknęło, aliasów nie ma.
- **`make demo`** buduje mały obraz demo (bez CUDA i bibliotek treningu, działa na arm64 i amd64) i uruchamia go na
  http://localhost:8791 z loginem demo/demo. Ctrl+C usuwa kontener.
- **`make docs`, `docs-build`, `docs-serve`** działają w Dockerze. Podgląd na żywo jest pod http://localhost:9791.
- **`make doctor`** sprawdza na Macu Dockera, Chrome, uv, adres maszyny i ssh, a przez ssh kartę i środowisko w
  kontenerze. Niczego nie instaluje.
- **Testy:**
  - `make test` nigdy nie buduje obrazów, a `make test-docker` buduje;
  - `make test-all` = lint, test, test-browser i test-docker.

## Testy {#tests}

| Etap | Liczba testów |
|---|---|
| Przed zmianami (panel + SSH) | 96 |
| Studio w Dockerze, Playwright | 120 |
| Wspólny standard (Makefile, Docker, pasek górny, dokumentacja) | 149 |
| Pomoc w okienkach i wydajność | 154–155 |
| Zwijanie kolumn | 157 |
| „Wypróbuj na Macu”, demo w Dockerze | 162–166 |
| Wspólne polecenia make | 197 |

- **Testy nie łączą się z niczym poza 127.0.0.1.** Blokada działa na poziomie gniazda, więc obejmuje też aiohttp i
  WebSocket.
- **Wyłączanie maszyny w testach jest nieszkodliwe:** atrapa zamiast prawdziwego przełącznika.
- **Playwright** sprawdza:
  - pasek górny, odliczanie i jego anulowanie, start i postęp zadania, wykres, historię zadań;
  - okienka pomocy, zwijanie kolumn i jeden zapis szkicu naraz;
  - limity czasu i 500 ms na zadanie strony.
- **Test z Dockerem** buduje obraz demo, loguje się, sprawdza przewodnik i to, że po zatrzymaniu nie zostaje żaden
  kontener. Drugi test buduje przewodnik w Dockerze.

## Co jeszcze zostało {#left}

- **Sprawdzenie na maszynie z GPU:**
  - instalacja, migracja starego workspace;
  - próba całej drogi (`smoke`) i autostart po restarcie;
  - czy Unsloth przyjmuje `torch==2.14.1`.
- **Aktualizacja Assist Routera w Home Assistancie do 0.1.8** (wydany 17 listopada 2026, ma komendę eksportu). Ze
  starszą wersją „Pobierz z Home Assistanta” kończy się błędem opisanym w [FAQ](faq.md).
- **Mniejsze punkty standardu:**
  - Stop zapisuje `stop_requested` w stanie zadania;
  - zrzuty bez ścieżek, adresów i nazw;
  - stare okno „Jak trenować?” znika w wersji 0.2.0.
