# How the data is made {#data}

This page describes where the training examples come from and what happens to them on the way, step by step.
It is what you need to train a model for **another home**: other entities, rooms, automations and people. The
generators assume nothing about one home - everything home-specific comes from Home Assistant or from
`trainer.yaml`. The list of what to prepare is at the end: [A new home](#new-home).

The model learns three roles, each with its own data:

| Role | Input → output | Data file |
|---|---|---|
| **router** | question → topic of `router.yaml` | `generated/router.jsonl` |
| **control** | command → JSON of the parsed command (intent, room, device, value) | `generated/control.jsonl` |
| **answers** | question + home data → a short answer to be read aloud | `generated/answers.jsonl` |

With "Only choosing the topic" only the router is generated and trained.

Every dataset example is **exactly the chat Assist Router sends** (system prompt and user question, built with the
router code of the version your HA runs) plus the answer the model should give. So the small model learns the
format it will get at home.

## Stage 1. Fetching from Home Assistant {#fetch}

"Fetch from HA" in the studio (or `router-trainer fetch`, or the first step of automatic training) connects to
Home Assistant over a WebSocket with an **administrator's** token and calls Assist Router's read-only commands.
Nothing in HA is written or run.

`assist_router/training/export` (Assist Router 0.1.8+) returns at once:

| What | Where in HA | File in `workspace/inputs/` | For |
|---|---|---|---|
| `router.yaml` | `/config/assist/router.yaml` | `router.yaml` | topics, descriptions, examples, household - the base of everything |
| the test | `/config/assist/model_test.yaml` (+ `_data`) | `model_test.yaml`, `model_test_data.yaml` | the HA test ("ha"), never for training |
| the log | Assist Router's `unrecognized_commands.csv` | `unrecognized_commands.csv` | real questions of the household |
| automations | all with a `conversation` trigger, also from `packages/` | `ha_config/automations.yaml` | trigger sentences |
| own sentences | `/config/custom_sentences/<language>/*.yaml` | `ha_config/custom_sentences/` | own intents |
| version and language | the Assist Router integration | `ha_export.json` | fetching the router code of that version |

Then the trainer fetches **the Assist Router code of the version HA runs** from GitHub (`/data/router/<version>`).
Prompts, answer schemas and the command parser come from it - so the data always fit what runs at home.

**Voice recordings** (Assist Router 0.1.11+): when HA's `configuration.yaml` has

```yaml
assist_pipeline:
  debug_recording_dir: /share/assist_pipeline
```

HA saves every voice command as a WAV (`<device>/<pipeline>/<run>/01_stt….wav`). The commands
`assist_router/training/recordings` (the list) and `assist_router/training/recording_files` (the files in parts
of 4 MB) bring them to `inputs/recordings/` - only the ones not there yet. Wake word recordings (`00_wake.wav`)
are not fetched. `generate.router.recordings: false` switches it off. The recordings and their text stay on the
GPU machine.

## Stage 2. Home snapshot {#snapshot}

`snapshot` reads from HA (REST, the same token) the entities **exposed to Assist** with names and aliases, the
areas, floors, scripts and scenes - with the code the router repository's control test uses. Result:
`home/snapshot.json`. Device and room names in sentences and the plans of control commands come from it.

For a new home this is the most important place: the model learns only the names HA exposes to Assist. Good
aliases ("lampka" for "Lampa przy kanapie") go straight into the data.

## Stage 3. Test and freezing {#test}

The test is the only measure of a model, so **no test sentence gets into training**, not even slightly reworded.

- **The HA test** (`model_test.yaml`) or **a new test** (`testgen`): the test writer (`ollama.test_writer`, a
  model other than the teacher) labels real log questions and writes the missing questions, commands and
  Wikipedia questions; the judge (the teacher) checks every case. Details: [Step by step → Test](steps.md#test).
- `freeze` writes the test sentences to `holdout/holdout.json`. From then on every generated sentence is compared
  with them: after normalization (lower case, no accents or punctuation) an **identical** or **similar** one - by
  word stems (`holdout.word_similarity`, 0.8) or character trigrams (`holdout.char_similarity`, 0.85) - is
  dropped.

## Stage 4. Router data {#router}

Every row keeps its **source** (`source`), so the dataset card shows how much of what there is.

| Source | How it is made | Topic |
|---|---|---|
| `trigger` | hassil templates of your automations' `conversation` triggers expanded at random (`per_template` sentences per template); `{wildcards}` get values from `slot_values`, else the teacher's suggestions (saved to `generated/slot_values.json` for review) | the topic's reference sentence (`command` in `router.yaml`), `topic_overrides`, at last the teacher's choice (`generated/trigger_topics.json`) |
| `intent` | built-in HA intents (`home-assistant-intents` for the router language) with your device, area and floor names (`native_intents`) | commands → the topic with `control: true`; others by `intent_topics`, the rest → `fallback_topic` |
| `custom` | your `custom_sentences` from HA, the same way | as `intent`; an intent of your own `intent_script` - the teacher's choice or `topic_overrides` `intent:<name>` |
| `example` | the topics' examples of `router.yaml` | its topic |
| `external` | sentences written outside the trainer - in any AI chat or by a person - from the tasks of the [handoff](teacher.md#manual) | the task's topic - **after the label check** |
| `paraphrase` | the teacher writes `paraphrases_per_topic` sentences per topic in six styles (short, with context, with names, with speech recognition errors, starting with "a"/"listen", indirect), with a hint of the home's rooms and devices | its topic - **after the label check** (below) |
| `contrast` | sentences on both sides of the border of topics that get mixed up ([contrast pairs](steps.md#auto)) | after the label check |
| `knowledge` | questions about random titles of the Wikipedia of the router language (`knowledge`) | the topic with `search` |
| `chat`, `gibberish` | small talk of the language pack; gibberish from syllables, video subtitles and broken sentences (`gibberish`) | `fallback_topic`; the topic with `unclear: true` |
| `log` | real questions of the log, unlike the test | the teacher with the router prompt |
| `recording` | your recordings written by the home's Whisper; what Whisper "hears" in silence drops out (hallucination list of the language pack) | the teacher with the router prompt |
| `asr` | `asr_per_topic` natural questions per topic read by Piper (every voice of the language in turn) and written by Whisper; only the ones written differently stay | the topic of the original |

**Label check.** The teacher writes paraphrases seeing one topic at a time, so now and then it writes a sentence
`router.yaml` sends elsewhere. So every teacher sentence is read once more **with the router's own prompt** (all
topics and descriptions); a sentence that lands in another topic is dropped with its Whisper copies and the
paraphrases refill what is missing (`check_labels`). The dropped ones are in `generated/labels_dropped.jsonl` -
the best list of unclear topic descriptions in `router.yaml`.

**Who writes and who judges.** The writer teacher writes the sentences, the judge checks topics and
parses - each can be the local Gemma, an API, Claude or work by hand ([The teacher](teacher.md)).

**Speech.** Piper and Whisper are the services HA uses (Wyoming, ports 10200 and 10300 of the home Ollama's host,
or `generate.router.speech`). Without them both speech sources are skipped with a message.

## Stage 5. Control data {#control}

1. Python **plans a command** from the home snapshot: intent, room, device, value, colour, music, script, list
   (`control.labels` plans) - e.g. HassLightSet in the kitchen at 40 %.
2. The teacher writes `sentences_per_label` natural sentences that mean exactly that (correct inflection, several
   styles).
3. The teacher **parses every sentence** with Assist Router's parser prompt and schema, and the router's
   `parse_command` and `find_target` read the reply. A sentence stays only when the parse matches the plan and
   points at the planned device. That reply becomes the training answer - the label is checked twice and has
   exactly the home's format. Rejected: `generated/control_rejected.jsonl`.

The music of "play…" commands is `music` in `trainer.yaml` - for a new home list the artists and playlists you
listen to.

## Stage 6. Answer data {#answers}

- `given`: made-up data (pocket money, calendars, lessons, the car…) with facts computed in Python; the teacher's
  answer stays when it has the right facts and none of the wrong ones (the test's own check).
- `live`: your current HA data built exactly as the integration builds it (`topic_data`) for questions written
  for the topic; the form is checked (length, no markdown, no raw states such as `unavailable`).
- `wikipedia`: summaries of random articles (never the test's articles) with the router's summary prompt.

## Stage 7. The dataset {#dataset}

`build` puts everything into `datasets/<name>/`:

- test sentences are checked once more (the dropped ones are listed in the card);
- router topics: natural sentences first, then templates; at most `max_per_topic`, smaller ones padded to
  `min_per_topic` with noisy copies; `noise` (30 %) of sentences get speech recognition noise (lower case, no
  accents, typos, "JAkie");
- duplicates are removed, roles taken by `dataset.mix`;
- the `dev` part (eval loss) is chosen by a hash of the text (`dev_fraction`, 5 %) - the same sentence is always
  on the same side, also after rebuilding with more data;
- `card.json`: how many examples of which source and role.

All stages **resume**: what exists stays, and the answers of the teacher, Whisper and Piper are kept in
`generated/*.json`. Running again only adds what is missing.

## A new home - the steps {#new-home}

The trainer works for any home with Assist Router. For a new home:

1. **In Home Assistant**
    - install Assist Router (0.1.11+ for the recordings) and write the home's `router.yaml`: `household`,
      `people`, topics with descriptions and 3-5 examples; a topic with `control: true` (commands), one with
      `search` (knowledge), one with `unclear: true` (gibberish) and an "everything else" topic. The topic
      descriptions matter most - both the router at home and the label check use them;
    - expose to Assist the entities to be controlled and give them the aliases you use;
    - switch on `assist_pipeline: debug_recording_dir` to collect recordings (the longer the home lives, the more
      real speech);
    - create a long-lived token of an administrator user.
2. **In the studio**: connect Home Assistant, "Fetch from HA".
3. **`trainer.yaml`** (Settings in the studio):
    - `fallback_topic` and `intent_topics` - topic names of **your** `router.yaml` (the example has the Polish
      `inne` and `pogoda`);
    - `music` - your music;
    - `slot_values` - values of trigger `{wildcards}` the teacher cannot guess (the children's names, say).
4. **Trigger topics**: `router-trainer triggers` lists every trigger with its key `id#number`, its topic and how
   it got it (`override`, `reference`, `teacher`, `none`); `!!` marks a topic `router.yaml` does not have. Fix
   the wrong ones in `topic_overrides` - a state question and a command in one automation may go to different
   topics (`asystent_alarm#0: alarm`, `asystent_alarm#2: sterowanie`).
5. **The test**: a new home usually has no `model_test.yaml` - choose "new test" (`testgen`); the question log is
   empty at first, so the test writer writes the questions itself. Review the test in the studio.
6. **Automatic training** - "Only choosing the topic" first, E2B. After the evaluation read
   `generated/labels_dropped.jsonl` and the errors of the result; fix the topic descriptions and run again - the
   contrast pairs take the errors of the last evaluation by themselves.
7. After a few weeks of the home's life: "Fetch from HA" again (the log and the recordings have grown) and a new
   training.

No code needs to be written: everything home-specific is in `router.yaml`, HA and `trainer.yaml`. Code is written
only for **a new language** - see [A new language](languages.md).
