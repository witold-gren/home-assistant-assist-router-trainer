# Nauczyciel {#teacher}

Dane do nauki pisze i sprawdza większy model - **nauczyciel**. Każdą z jego trzech ról może pełnić
inny:

| Rola | Co robi |
|---|---|
| **pisarz** (`teacher.writer`) | parafrazy każdego tematu, pary kontrastowe, polecenia dla każdego zaplanowanego polecenia sterowania, odpowiedzi wzorcowe, pytania o wiedzę, wartości `{zmiennych}` wyzwalaczy, tłumaczenie nowego języka |
| **sędzia** (`teacher.judge`) | tematy zdań (sprawdzanie etykiet, wyzwalacze, dziennik, nagrania), rozbiór poleceń do porównania z planem, fakty w generowanym teście |
| **pisarz testu** (`teacher.test_writer`) | generowany test - lepiej inny model niż pisarz, żeby test nie faworyzował jego stylu |

## Dostawcy {#providers}

| `provider` | Co działa | Ustawienia |
|---|---|---|
| `ollama` (domyślnie) | własna Ollama studia na maszynie z GPU | `model` puste = `ollama.teacher` (`ollama.test_writer` dla pisarza testu) |
| `openai` | dowolne API zgodne z OpenAI: OpenAI, OpenRouter (także Claude i Gemini), Groq, LM Studio, vLLM | `base_url`, `model` (wymagany), klucz |
| `claude` | Claude przez API Anthropic | `model` (puste = `claude-opus-5-5`), `effort` (`low` wystarcza do danych i jest najtańsze), klucz |
| `manual` | ręcznie - dowolny czat AI albo człowiek ([niżej](#manual)) | - |

```yaml
teacher:
  writer: {provider: claude}                    # pisze Claude …
  judge: {provider: ollama, model: ""}          # … ocenia lokalna Gemma
  test_writer: {provider: openai, base_url: "https://openrouter.ai/api/v1", model: "google/gemini-2.5-pro"}
```

W studiu: **Ustawienia → Nauczyciel** - dostawca, model i adres dla każdej roli, **Sprawdź** (jedno
krótkie pytanie: czy odpowiada JSON-em?) i klucze API.

- **Odpowiedzi w formacie**: API zgodne z OpenAI dostaje schemat JSON odpowiedzi
  (`response_format`); serwer, który nie przyjmuje schematów, dostaje prośbę słowami, a odpowiedź
  jest wyciągana z tekstu. Claude odpowiada przez structured outputs (sam schemat), a gdy odmówi,
  w tym samym wywołaniu odpowiada model zapasowy (`fallbacks: default`).
- **Zapamiętane odpowiedzi**: każda odpowiedź API jest zapisana w `generated/teacher/<rola>.jsonl`;
  wznowiony krok o nic nie pyta drugi raz - i nic nie płaci drugi raz.
- **Limity**: zajęte API (429, 529, 5xx) jest pytane ponownie po przerwie.

### Klucze i prywatność {#keys}

Klucz zapisuje się w studiu (Ustawienia → Nauczyciel → Klucze API) do
`workspace/secrets/<dostawca>_key`, do odczytu tylko przez właściciela, nigdy więcej niepokazywany;
albo bierze się z `OPENAI_API_KEY` / `ANTHROPIC_API_KEY`. Puste + Zapisz usuwa klucz.

**API dostaje Twój dom**: opis domowników, imiona, nazwy pokoi i urządzeń, pytania z dziennika i
tekst Waszych nagrań. Sprawdzanie ustawień ostrzega, gdy rola używa API. Zostaw sędziego lokalnie,
jeśli prawdziwe pytania domu mają zostać w domu - pisarz pracuje wtedy tylko na `router.yaml` i
migawce.

### Koszt {#cost}

Najwięcej wywołań robi pisarz: około `paraphrases_per_topic / 25` na temat, do tego pary
kontrastowe, `control.labels` poleceń i odpowiedzi - tysiące wywołań na pełny zbiór. Sędzia robi
jedno krótkie wywołanie na sprawdzane zdanie. Z API zacznij od **Tylko wybór tematu** i małego
`paraphrases_per_topic`, i sprawdź koszt tego pierwszego biegu.

## Ręcznie {#manual}

`provider: manual` - nic nie jest nigdzie wysyłane. Trener zapisuje zadania, odpowiadasz na nie w
dowolnym czacie AI (albo sam) i importujesz odpowiedzi. **Pisanie i ocenianie są osobno**: człowiek
może pisać, a model oceniać, albo odwrotnie.

**Pisanie ręczne** (`teacher.writer.provider: manual`):

1. **Eksport**: Ustawienia → Nauczyciel → *Pisanie ręczne* → *Eksportuj zadania* albo
   `router-trainer handoff export writer`. Dostajesz `prompts.md` (polecenia do wklejenia, w
   częściach), `requests.jsonl` (id, wiadomości, schemat odpowiedzi - dla skryptu) i `README.md`.
   Zadania są te same co nauczyciela: parafrazy według tematów (`--per-topic N`), pary kontrastowe,
   zadanie poleceń dla każdego zaplanowanego polecenia sterowania.
2. **Odpowiedź**: każda odpowiedź to obiekt JSON z `id` zadania, np.
   `{"id": "paraphrase:pogoda:0", "zdania": ["…", "…"]}` (słowo klucza z pakietu językowego).
   Odpowiedź czatu może mieć kilka takich obiektów, z tekstem dookoła - import je znajdzie.
3. **Import**: wklej albo wczytaj odpowiedzi → *Importuj odpowiedzi* albo
   `router-trainer handoff import writer odpowiedzi.jsonl`. Zdania stają się wierszami ze źródłem
   `external` i przechodzą te same kontrole co zdania nauczyciela: zamrożony test, sprawdzanie
   etykiet (przez sędziego), rozbiór poleceń przez sędziego. Zadania z odpowiedzią nie są
   eksportowane ponownie.

**Ocenianie ręczne** (`teacher.judge.provider: manual`): zdania wymagające tematu (sprawdzanie
etykiet, dziennik, nagrania) czekają w `generated/handoff/judge-pending.json` i zostają poza
zbiorem, dopóki nie zostaną ocenione. *Eksportuj zadania* daje je jako polecenia dla czatu AI (z
promptem samego routera) i jako `table.csv` do wypełnienia samemu (`zdanie;temat`, temat z
`router.yaml`). Zaimportuj odpowiedzi albo wypełnioną tabelę. Rozbiór poleceń wymaga
sędziego-modelu: ręcznie byłby po prostu samą etykietą.

Tłumaczenie [nowego języka](languages.md) działa tak samo: `tasks.jsonl` na zewnątrz, `--answers` z
powrotem.
