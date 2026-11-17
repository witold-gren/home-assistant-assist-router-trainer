# Jak robić to dobrze {#good-practice}

## Jak trenować {#how}

- Przed każdym nowym zbiorem pobierz dane z Home Assistanta i sprawdź kod routera.
- Nazywaj zbiory datą (`lis16`): stare zbiory i przebiegi zostają do porównań.
- Zmieniaj **jedną rzecz naraz** (parametr albo dane) i porównuj **na tym samym teście**.
- Zacznij od E2B (szybko), potem E4B z najlepszymi ustawieniami.
- Po zmianie `router.yaml` (tematy, przykłady) zbuduj zbiór od nowa - przypomni o tym ostrzeżenie o promptach.
- Szybki sprawdzian całej drogi na małej kopii: `make docker-shell`, potem `router-trainer smoke` (E2B,
  ok. 15-25 minut).

## Ile danych {#data}

Wartości domyślne dają ok. 12-15 tysięcy przykładów treningowych - wystarczy na jedną epokę. Więcej zdań z
szablonów nie pomaga: model uczy się szablonu, a nie znaczenia. Najbardziej pomagają **prawdziwe pytania z
dziennika** i **parafrazy**. Temat z mniej niż `min_per_topic` przykładami jest dopełniany zaszumionymi kopiami -
dopisz mu przykłady w `router.yaml`.

## Podział {#split}

- **Test** - jedyna miara. Zdanie treningowe takie samo albo podobne do zdania testu odpada: po rdzeniach słów
  (`holdout.word_similarity`) i trójkach znaków (`holdout.char_similarity`), przy generowaniu i ponownie przy
  składaniu, przed szumem.
- **Dev** (`dataset.dev_fraction`) - tylko do straty ewaluacyjnej; podział po skrócie tekstu (to samo zdanie zawsze
  po tej samej stronie). Dev nie zastępuje testu.
- **Wyrównanie**: `max_per_topic` przycina duże tematy, `min_per_topic` dopełnia małe; `noise` dodaje błędy jak z
  rozpoznawania mowy; `dataset.mix` bierze część przykładów każdej roli.

## Parametry {#parameters}

Każdy parametr `trainer.yaml` (Ustawienia w studiu); wartość domyślna to wartość w kodzie
(`router_trainer/trainer.example.yaml`).

| Parametr | Domyślnie | Zakres | Działanie |
|---|---|---|---|
| `models.e4b.load_in_4bit` | true | true / false | QLoRA: baza 4-bitowa; E4B w bf16 nie mieści się w 24 GB z długimi promptami |
| `models.e4b.epochs` | 1 | 0.5-3 | przejścia po danych; 2, gdy dev jeszcze spada na końcu |
| `models.e4b.learning_rate` | 0.0001 | 5e-5 - 2e-4 | wyższy uczy szybciej i szybciej przeucza |
| `models.e4b.lora_r` | 16 | 8-64 | rozmiar adaptera; 32 przy bardzo dużym zbiorze |
| `models.e4b.lora_alpha` | 32 | 2 × r | waga adaptera |
| `models.e4b.batch_size` | 2 | 1-8 | przykłady na krok na karcie; mniej przy „out of memory” |
| `models.e4b.grad_accum` | 8 | 1-32 | kroki sumowane przed aktualizacją; batch × accum = prawdziwa paczka |
| `models.e4b.max_seq_length` | 6144 | 2048-8192 | dłuższe przykłady są pomijane i liczone |
| `models.e2b.load_in_4bit` | false | true / false | E2B mieści się w bf16 (LoRA) |
| `models.e2b.batch_size` | 4 | 1-16 | jak wyżej |
| `models.e2b.grad_accum` | 4 | 1-32 | jak wyżej |
| `generate.router.paraphrases_per_topic` | 300 | 100-600 | zdania pisane przez nauczyciela na temat |
| `generate.router.per_template` | 30 | 10-60 | zdania na szablon Twoich automatyzacji |
| `generate.router.native_intents` | 1500 | 0-3000 | wbudowane intencje HA z Twoimi nazwami |
| `generate.router.knowledge` | 800 | 0-1500 | pytania o wiedzę (temat z `search`) |
| `generate.router.gibberish` | 300 | 0-600 | bełkot z rozpoznawania mowy (temat z `unclear`) |
| `generate.router.max_per_topic` | 900 | 300-2000 | limit na temat |
| `generate.router.min_per_topic` | 250 | 50-500 | małe tematy dopełniane do tej liczby |
| `generate.router.noise` | 0.3 | 0-0.6 | część z szumem rozpoznawania mowy |
| `generate.control.labels` | 1500 | 500-3000 | polecenia zaplanowane z Twojego domu |
| `generate.control.sentences_per_label` | 3 | 1-5 | zdania pisane na zaplanowane polecenie |
| `generate.answers.given` | 600 | 200-1500 | wymyślone dane z faktami z Pythona |
| `generate.answers.live_per_topic` | 40 | 10-100 | pytania na temat z Twoich danych z HA na żywo |
| `generate.answers.wikipedia` | 300 | 0-600 | streszczenia z Wikipedii |
| `test.router_per_topic` | 12 | 5-30 | przypadki routera na temat |
| `test.control` | 150 | 50-300 | przypadki sterowania |
| `test.control_overhead` | 4 | 2-6 | zaplanowane polecenia na jedno zachowane |
| `test.answers` | 35 | 10-80 | przypadki z danymi podanymi |
| `test.real_per_topic` | 5 | 2-10 | przypadki z danymi z HA na temat |
| `test.real_max` | 90 | 30-150 | przypadki z danymi z HA najwyżej |
| `test.wikipedia` | 15 | 5-40 | przypadki z Wikipedii |
| `holdout.word_similarity` | 0.8 | 0.6-0.95 | niżej = więcej zdań treningowych odpada |
| `holdout.char_similarity` | 0.85 | 0.6-0.95 | niżej = więcej odpada |
| `dataset.dev_fraction` | 0.05 | 0.02-0.1 | część zostawiona na stratę ewaluacyjną |
| `export.quantization` | q8_0 | q8_0 / bf16 / f16 | q8_0: prawie bez strat, połowa rozmiaru |

## Czytanie wykresu {#chart}

Wykres widoku na żywo: strata treningowa (niebieska) i strata dev (pomarańczowa) względem kroków, na jednej osi.
Najechanie pokazuje wartości kroku; kliknięcie otwiera go na pełnym ekranie, gdzie przeciąganie przybliża, a
kliknięcie przypina krok.

- Obie spadają razem - dobrze.
- **Dev rośnie, treningowa spada** - przeuczenie: model uczy się przykładów na pamięć. Studio ostrzega, gdy dev
  wzrośnie dwa razy z rzędu. Zatrzymaj; mniej epok albo mniejszy learning rate.
- Obie stoją wysoko - za mało danych albo za mały learning rate.
- „Pominięte (za długie)” - przykłady dłuższe niż `max_seq_length`; dużo ich oznacza za duże dane z HA (przytnij
  tematy w `router.yaml`).

## Wznawianie {#resume}

<span class="ui">Wznów</span> z tym samym zbiorem i modelem kontynuuje od najnowszego punktu kontrolnego. Karta
startu mówi, ile naprawdę zostanie wytrenowane: „od kroku 510 z 806 - zostało 296 kroków”. Skończony przebieg nie
ma nic do zrobienia: zamiast tego zwiększ epoki (nowy przebieg).

## Czytanie wyników {#results}

- zielone ≥ 95%, żółte ≥ 85%, czerwone poniżej;
- **naprawione / zepsute** mówią więcej niż wynik: zepsute przypadki pokazują, czego model się oduczył;
- model jest lepszy, gdy wygrywa w routerze i sterowaniu **i** nie traci w odpowiedziach; liczy się też czas
  (sekundy obok wyniku) - po to jest mniejszy model.

## Przepisy {#recipes}

| Problem | Spróbuj |
|---|---|
| Świetna strata dev, słaby test | model nauczył się szablonów: więcej parafraz i pytań z dziennika, mniejsze `max_per_topic`, mniej epok |
| Słabe sterowanie | dużo odrzuconych poleceń w `generated/control_rejected.jsonl`; dodaj aliasy urządzeń w HA |
| „CUDA out of memory” | mniejsze `batch_size`, większe `grad_accum` (ten sam iloczyn) albo mniejsze `max_seq_length` |
| Słabe odpowiedzi z danych HA | więcej `live_per_topic`; krótsze dane tematów w `router.yaml` (`details`, `fetch`) |

## Przykład z domu {#example}

Runda 3 porównania modeli routera: bazowa Gemma 4 E4B miała router 95%, sterowanie 90%, dane z HA 84%. Test
generowany z tego samego domu dał podobne wyniki routera i sterowania oraz surowszy wynik danych z HA (~70%), bo
wymaga faktu z danych. Dlatego modele porównuje się tylko na jednym teście.
