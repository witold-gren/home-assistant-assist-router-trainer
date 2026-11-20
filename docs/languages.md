# A new language {#languages}

The trainer and Assist Router ship Polish. A model trained in Polish understands Polish; for Czech,
English or German the data have to be generated in that language - which needs two **language
packs**, one for Assist Router and one for the trainer. This page is for someone who speaks the
language and wants to add it - no Python is needed for most of the work.

## What depends on the language {#what-depends}

| Part | Language dependent? | Where |
|---|---|---|
| Router, control and answer prompts, JSON keys, what the assistant says, the words it understands | yes | Assist Router's pack `custom_components/assist_router/languages/<code>/` |
| Teacher prompts, styles, small talk, gibberish, made-up data, Whisper hallucinations, inflection of test facts | yes | the trainer's pack `router_trainer/languages/<code>/` |
| Built-in Home Assistant intents | yes, ready | `home-assistant-intents` has 57 languages |
| Piper and Whisper | chosen by themselves | Piper voices whose code starts with the language code; Whisper gets the code |
| Wikipedia (knowledge, summaries) | from the settings | `wikipedia_language` in `router.yaml` |
| Test protection, noise, normalization | no | accents are stripped for any language with Latin letters |
| The studio (screen, buttons) | no - Polish and English, chosen in ⚙ | `studio/www/i18n.js`, `ui/texts.py` |
| E2B / E4B, Gemma as the teacher, Claude | no | multilingual |
| The test writer (`ollama.test_writer`) | a choice | Bielik is Polish - pick a model that writes the language |

**The data language** is chosen as in Home Assistant: `language:` in `router.yaml`, otherwise Home
Assistant's language from the last fetch (when there is a pack for it).

## A pack is a folder {#pack}

Both packs have the same layout. A comment above every entry says what it is for.

| File | What it holds | What you do |
|---|---|---|
| `texts.yaml` | sentences and prompts, as `str.format` templates | translate the values; keep every `{field}` |
| `words.yaml` | word lists and small dictionaries | translate the words; Home Assistant names stay |
| `patterns.yaml` (Assist Router only) | regular expressions with `matches` / `not_matches` examples | translate the examples, then the pattern |
| `grammar.py` | functions that depend on grammar (plural forms, dates, made-up data) | translate the text inside, adapt the grammar |

The rules every pack is checked against (names, `{fields}`, Home Assistant names, JSON key words,
pattern examples) are in Assist Router's guide:
[Adding a language](https://witold-gren.github.io/home-assistant-assist-router/languages/).

## Step by step {#add}

### 1. A checked draft: `router-trainer language new` {#new}

```bash
router-trainer language new cs           # in the studio's machine: docker compose exec studio …
router-trainer language new cs --home    # + the names of the Czech home Home Assistant runs
```

The **writer** teacher ([The teacher](teacher.md): the local Gemma, an API, Claude, or by hand)
translates from Polish, unit by unit, with reference material: Home Assistant's own sentences,
colour words and replies in that language (`home-assistant-intents`), and with `--home` the rooms
and devices of the home. Every unit is checked as it comes back:

- a text keeps its `{fields}`;
- a word list keeps its type and the Home Assistant names (intents, domains, states, colour values);
- a pattern finds its translated `matches` and none of its `not_matches`.

What fails keeps the Polish value and goes to `REVIEW.md`. The draft lands in
`workspace/languages/<code>/` - never in the repositories:

| File | What it is |
|---|---|
| `router/` | Assist Router's pack |
| `trainer/` | the trainer's pack |
| `router.example.yaml` | an example `router.yaml` with translated topics, `language: <code>` |
| `model_test.yaml` | the router and control cases of the active test, translated; answer cases are left out - their `must` / `never` patterns need a speaker (or write a new test: `router-trainer testgen`) |
| `REVIEW.md` | what did not pass the checks, what is always read by a speaker (grammar), where to copy the files |
| `tasks.jsonl` | only with the writer by hand: the translation tasks for any AI chat |

**By hand**: with `teacher.writer.provider: manual` nothing is sent anywhere; the tasks are written
to `tasks.jsonl` (the same format as the [handoff](teacher.md#manual)). Answer them in any AI chat
and run `router-trainer language new cs --answers answers.jsonl`.

### 2. A speaker reads the draft {#review}

Start with `REVIEW.md`, in this order:

1. **Patterns** that did not find their examples (`patterns.yaml`) - they decide whether commands
   and questions are recognized at all.
2. **`grammar.py`** of both packs - the text is translated, the grammar is still Polish: plural
   forms (`done_speech`), the date read aloud (`format_now`, month names), female forms of the
   replies (`gendered`), the made-up data of answers (`given_scenario`).
3. **Prompts** in `texts.yaml` - how a native speaker would ask for it.
4. **Word lists** - command verbs, yes / no words, colour words as people say them.

### 3. Check and copy {#check}

```bash
router-trainer language check cs   # both packs of the draft; one line per problem
```

When both say `ready`, copy:

- `router/` → Assist Router `custom_components/assist_router/languages/cs/`, then
  `tools/check_language.py` and `make test` there;
- `trainer/` → `router_trainer/languages/cs/`, then `router-trainer languages --check cs` and
  `make test`.

Send both folders as pull requests.

### 4. Use it {#use}

In Home Assistant: `router.yaml` from `router.example.yaml` (`language: cs`, your topics, rooms and
people), a model that writes the language, a test (`model_test.yaml` from the draft or a new one).
In `trainer.yaml`: `ollama.test_writer` for that language, `fallback_topic` and `intent_topics`
with the topic names of your `router.yaml`. Then the first training "Only choosing the topic" on a
small dataset - and read `generated/router.jsonl` and `generated/labels_dropped.jsonl`: do the
sentences sound natural?

The studio itself is translated separately (a new screen language): the keys in
`studio/www/i18n.js` and `ui/texts.py`, the guide in `docs/*.<code>.md` and the language in
`mkdocs.yml`.
