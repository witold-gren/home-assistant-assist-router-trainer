# FAQ: błędy i rozwiązania {#faq}

Komunikaty studia i poleceń są po angielsku. Poniżej każdy znany błąd: dokładny tekst (albo objaw), przyczyna i co
zrobić. Nowy błąd, którego tu nie ma? Dopisz go na tę stronę (PL i EN) razem z rozwiązaniem.

## Instalacja i Docker {#faq-docker}

| Komunikat / objaw | Przyczyna i co zrobić |
|---|---|
| „error: Docker is missing”, „the Docker Compose plugin is missing” | Zainstaluj Dockera z repozytorium Dockera i `docker-compose-plugin` ([Instalacja](installation.md#install-machine)). |
| „error: this user cannot use Docker” | `sudo usermod -aG docker $(id -un)`, potem wyloguj i zaloguj się. |
| „error: the NVIDIA driver is missing” | `sudo ubuntu-drivers install` i restart. |
| „error: nvidia-smi does not see the card” | Sterownik jest zainstalowany, ale niezaładowany: restart; po aktualizacji jądra często wystarczy restart. |
| „error: NVIDIA driver … is too old for the image's CUDA 13.0” | PyTorch z obrazu wymaga sterownika 580 lub nowszego: `sudo ubuntu-drivers install` (albo `sudo apt install nvidia-driver-580`) i restart. |
| „error: the NVIDIA Container Toolkit is missing” | Zainstaluj `nvidia-container-toolkit`, potem `sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker`. |
| „warning: the container does not see the GPU” | Toolkit nie jest skonfigurowany dla Dockera albo sterownik jest starszy niż wymaga PyTorch z obrazu (sterownik 580 / CUDA 13.0). `docker run --rm --gpus all ubuntu nvidia-smi` musi pokazać kartę; `make doctor` (z Maca, przez ssh) sprawdza kontener. |
| Strona się nie otwiera po włączeniu maszyny | Docker nie startuje z systemem (`sudo systemctl enable --now docker`) albo kontener padł: `make logs` z Maca. |
| „error: ROUTER_TRAINER_UI_AUTH must be user:password” | Brak albo zły wpis w `docker/config/env`; uruchom `make install` (zapisze nowy login). |
| Logowanie: „Too many attempts” | Pięć złych haseł z jednego adresu - poczekaj minutę. Hasło: `make login`. |
| „Docker is not installed: install and start Docker Desktop” / „Docker is not running: start Docker Desktop” (po polsku obok: „Brak Dockera…”, „Docker nie działa…”; `make demo`, `make docs`, `make docs-serve`, `make docs-build`, `make doctor`) | Zainstaluj [Docker Desktop](https://www.docker.com/products/docker-desktop/) i go uruchom (wieloryb na pasku menu musi mówić, że działa), potem to samo polecenie jeszcze raz. Do tych poleceń nic więcej nie trzeba. |
| „uv is not installed (development only): curl -LsSf https://astral.sh/uv/install.sh \| sh” (`make setup`, `make test`) | Tylko do pracy nad kodem. Uruchom polecenie z komunikatu (albo `brew install uv`); uv sam pobiera Pythona w wersji `PYTHON_VERSION`. |
| `make doctor`: „-- ssh user@machine: the machine is off or ssh needs a key” | Maszyna jest wyłączona (włącz ją w Home Assistancie) albo ssh pyta o hasło: raz `ssh-copy-id user@maszyna`. `make doctor` tylko sprawdza, niczego nie instaluje. |
| `make docs-serve`: pod adresem jest inna strona albo „address already in use” | Port 9791 zajmuje inny program: `make docs-serve DOCS_PORT=9792`. |
| „GPU_HOST is not set” | Mac nie zna maszyny: `GPU_HOST=user@maszyna` w `~/.config/gpu-studio/host.mk` (wspólne dla wszystkich studiów) albo w `Makefile.local`. |
| „'…' is still running” / „fetching from Home Assistant is still running” | Działa już inne zadanie; poczekaj albo naciśnij <span class="ui">Stop</span>. |
| Po restarcie kontenera zadanie jest „Przerwane” | Restart (aktualizacja, `make deploy`) przerywa zadanie. Trening wznów od punktu kontrolnego (<span class="ui">Wznów</span>); generowanie zacznie od miejsca przerwania. |
| „The studio did not answer within … s - check the machine (make status) and try again.” / „The studio cannot be reached - is the machine on?” (po polsku: „Studio nie odpowiedziało w … s”, „Nie ma połączenia ze studiem”) | Maszyna jest wyłączona albo zajęta, albo kontener się restartuje. `make status` z Maca; strona sama pyta ponownie i komunikat znika, gdy studio odpowie. |

## Home Assistant i kod routera {#faq-ha}

| Komunikat / objaw | Przyczyna i co zrobić |
|---|---|
| „Assist Router in Home Assistant is too old for the trainer - update it to 0.1.8 or newer” | Komenda eksportu jest od Assist Routera 0.1.8. Zaktualizuj integrację przez HACS i zrestartuj HA. |
| „Home Assistant refused the export: the token's user must be an administrator” | Token należy do zwykłego użytkownika. Utwórz token na koncie administratora. |
| „Home Assistant rejected the token”, w pasku „token HA odrzucony” | Token zły, wygasły albo usunięty. Każda odmowa to dla HA nieudane logowanie (`ip_ban`), więc studio przestaje pytać HA do czasu <span class="ui">Połącz z HA</span> z nowym tokenem. |
| „Home Assistant 403: refused - this computer's address may be banned …” | HA zablokował adres po nieudanych logowaniach: usuń wpis z `/config/ip_bans.yaml` i zrestartuj HA. |
| „Home Assistant at … cannot be reached” | Zły adres albo HA się restartuje. Podaj pełny adres z portem, np. `http://192.168.1.10:8123`. |
| Czerwona pigułka „Router 0.1.7 ≠ HA 0.1.8” | Studio ma inną wersję kodu routera niż HA: **Kod routera** → <span class="ui">Pobierz router {version}</span>. |
| „git clone v…: Remote branch … not found” | Tej wersji nie ma jako tagu na GitHubie (wersja lokalna, niewydana). Wydaj ją albo ustaw `router_repo` na folder z kodem. |
| „This router version needs other Python packages than the image has” | Zmieniły się wymagania routera: ustaw `ROUTER_REF=v…` w `docker/.env` i `make deploy`. |
| „…/router.yaml missing” | Najpierw <span class="ui">Pobierz z Home Assistanta</span>. |
| „No test yet”, „no generated test '…'” | Utwórz test albo wybierz inny aktywny. |

## Test i dane treningowe {#faq-data}

| Komunikat / objaw | Przyczyna i co zrobić |
|---|---|
| „… missing - freeze the test first” | W **Generowaniu** zaznacz zamrożenie testu. Potrzebne po każdej zmianie aktywnego testu albo przeglądu. |
| „dataset … missing - build it first” | Generowanie z krokiem złożenia zbioru, potem ta sama nazwa w **Starcie treningu**. |
| „router.yaml or the home changed since this dataset was built” | Zmieniły się prompty integracji. Zbuduj zbiór od nowa. |
| „the trainer's Ollama did not start (…)” | Zobacz wskazany dziennik; zwykle port 11535 jest zajęty - zmień `ollama.local_port`. |
| Model (np. Bielik) nie pobiera się z Hugging Face: „bad record MAC”, błąd TLS | Pobierz plik GGUF w przeglądarce i wgraj przez API Ollamy (`/api/blobs`, potem `/api/create`). W zsh pisz `${repo}:Q4_K_M`, nie `$repo:Q4_K_M`. |
| Mało przypadków w teście, dużo „odrzuconych automatycznie” | „models disagree” to normalne odsiewanie. Gdy odpada prawie wszystko, zwiększ liczby w `test:` albo sprawdź sędziego (Gemma 26B). |
| Dużo odrzuconych poleceń sterowania | `generated/control_rejected.jsonl`; pomagają aliasy urządzeń w HA. |
| „… lower-case letters, digits, . _ - (up to 41 chars)” | Nazwa zbioru, testu albo przebiegu: małe litery, cyfry i `. _ -`. |
| Zapis ustawień: „dataset.dev_fraction: between 0 and 0.5”, „models.e4b.epochs: a number” | Wartość poza zakresem albo nie liczba - popraw pole; szkic zostaje. |
| Zapis: „trainer.yaml was changed elsewhere since this draft was begun” | Plik zmienił się gdzie indziej (np. w terminalu). <span class="ui">Zapisz mimo to</span> nadpisze go - poprzednia wersja zostaje w <span class="ui">Historia</span>. |

## Trening i eksport {#faq-train}

| Komunikat / objaw | Przyczyna i co zrobić |
|---|---|
| „only … of … GB free on the GPU …” | Kartę zajmuje inny proces (`nvidia-smi` na maszynie), np. inny kontener z modelem. Zatrzymaj go. |
| „no CUDA GPU - training needs an NVIDIA card” | Kontener nie widzi karty - patrz [Instalacja i Docker](#faq-docker). |
| „CUDA out of memory” | Zmniejsz `batch_size` (zwiększ `grad_accum`) albo `max_seq_length`. |
| Ostrzeżenie o przeuczeniu | Strata dev rośnie - zatrzymaj; mniej epok albo mniejszy learning rate ([Czytanie wykresu](good-practice.md#chart)). |
| „chat template turn markers not found” | Model bazowy ma inny szablon rozmowy niż Gemma 4; używaj modeli z `models:`. |
| „…/merged missing - train the model first” | Eksport przebiegu bez skończonego treningu. |
| „nothing left to train” przy wznowieniu | Przebieg doszedł już do ostatniego kroku: zacznij nowy przebieg z większą liczbą epok ([Wznawianie](good-practice.md#resume)). |
| Kończy się miejsce na dysku | `du -sh docker/data/workspace/*`; stare przebiegi są w `runs/`, kopia z testu próbnego w `workspace-smoke`. |
| Maszyna nie wyłączyła się po zadaniu | Nie wyłącza się po <span class="ui">Stop</span> ani po restarcie kontenera; błąd (brak tokenu, przełącznik niedostępny) widać w górnym pasku ([Wyłączenie po zadaniu](home-assistant.md#power-off-after)). |

## Ocena {#faq-eval}

| Komunikat / objaw | Przyczyna i co zrobić |
|---|---|
| Test przerywa „Connection reset” | Za mało pamięci na Jetsonie: dopisz duże modele do `evaluate.unload_first` i uruchom ocenę ponownie (dopisuje wyniki). |
| Wyniki inne niż w porównaniu modeli routera | Inny test - porównuj tylko na tym samym aktywnym teście. |
| Świetna strata dev, słaby test | Model nauczył się szablonów - [Przepisy](good-practice.md#recipes). |
