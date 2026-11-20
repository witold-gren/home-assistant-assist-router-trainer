# The teacher {#teacher}

The training data are written and checked by a bigger model - the **teacher**. Each of its three
roles can be done by a different one:

| Role | What it does |
|---|---|
| **writer** (`teacher.writer`) | paraphrases of each topic, contrast pairs, commands for each planned control command, reference answers, knowledge questions, values of trigger `{wildcards}`, the translation of a new language |
| **judge** (`teacher.judge`) | topics of sentences (the label check, triggers, the log, the recordings), parsing the commands back to compare them with the plan, facts of the generated test |
| **test writer** (`teacher.test_writer`) | the generated test - better another model than the writer, so the test does not favour its style |

## Providers {#providers}

| `provider` | What runs | Settings |
|---|---|---|
| `ollama` (default) | the studio's own Ollama on the GPU machine | `model` empty = `ollama.teacher` (`ollama.test_writer` for the test writer) |
| `openai` | any OpenAI-compatible API: OpenAI, OpenRouter (also Claude and Gemini), Groq, LM Studio, vLLM | `base_url`, `model` (required), the key |
| `claude` | Claude through Anthropic's API | `model` (empty = `claude-opus-5-5`), `effort` (`low` is enough for data and the cheapest), the key |
| `manual` | by hand - any AI chat or a person ([below](#manual)) | - |

```yaml
teacher:
  writer: {provider: claude}                    # Claude writes …
  judge: {provider: ollama, model: ""}          # … the local Gemma judges
  test_writer: {provider: openai, base_url: "https://openrouter.ai/api/v1", model: "google/gemini-2.5-pro"}
```

In the studio: **Settings → Teacher** - a provider, model and address per role, **Check** (one short
question: does it answer JSON?) and the API keys.

- **Structured answers**: the OpenAI-compatible API gets the answer's JSON schema
  (`response_format`); a server that does not take schemas is asked in words, the answer read from
  the text. Claude answers through structured outputs (the schema itself) and, when a request is
  declined, a fallback model answers in the same call (`fallbacks: default`).
- **Remembered answers**: every answer of an API is kept in `generated/teacher/<role>.jsonl`; a
  resumed step asks nothing twice - and pays nothing twice.
- **Limits**: a busy API (429, 529, 5xx) is asked again after a pause.

### Keys and privacy {#keys}

A key is saved in the studio (Settings → Teacher → API keys) into `workspace/secrets/<provider>_key`,
readable by its owner only, never shown again; or taken from `OPENAI_API_KEY` /
`ANTHROPIC_API_KEY`. Empty + Save removes it.

**An API gets your home**: the household description, the names of people, rooms and devices, the
questions of the log and the text of your recordings. The settings check warns when a role uses an
API. Keep the judge local when you want the home's real questions to stay home - the writer then
works from `router.yaml` and the snapshot only.

### Cost {#cost}

The writer makes most of the calls: about `paraphrases_per_topic / 25` per topic, plus contrast
pairs, `control.labels` commands and the answers - thousands of calls for a full dataset. The judge
makes one short call per sentence it checks. With an API, start with **Only choosing the topic** and
a small `paraphrases_per_topic`, and look at the cost of that first run.

## By hand {#manual}

`provider: manual` - nothing is sent anywhere. The trainer writes the tasks, you answer them in any
AI chat (or yourself), and import the answers. **Writing and judging are separate**: a person may
write and a model judge, or the other way round.

**Writing by hand** (`teacher.writer.provider: manual`):

1. **Export**: Settings → Teacher → *Writing by hand* → *Export tasks*, or
   `router-trainer handoff export writer`. You get `prompts.md` (the prompts to paste, in parts),
   `requests.jsonl` (id, messages, the answer schema - for a script) and `README.md`. The tasks are
   the teacher's own: paraphrases per topic (`--per-topic N`), the contrast pairs, a command task
   for each planned control command.
2. **Answer**: each answer is a JSON object with the task's `id`, e.g.
   `{"id": "paraphrase:weather:0", "sentences": ["…", "…"]}` (the key word of the language pack). A
   chat answer may hold several, with text around them - the import finds them.
3. **Import**: paste or load the answers → *Import answers*, or
   `router-trainer handoff import writer answers.jsonl`. The sentences become rows of the source
   `external` and go through the same checks as the teacher's: the frozen test, the label check (by
   the judge), commands parsed back by the judge. Answered tasks are not exported again.

**Judging by hand** (`teacher.judge.provider: manual`): sentences that need a topic (the label
check, the log, the recordings) wait in `generated/handoff/judge-pending.json` and stay out of the
dataset until judged. *Export tasks* gives them as prompts for an AI chat (the router's own prompt)
and as `table.csv` to fill in yourself (`sentence;topic`, the topic one of `router.yaml`). Import
the answers or the filled table. Parsing commands back needs a model judge - by hand it would be
the label itself.

The translation of [a new language](languages.md) works the same way: `tasks.jsonl` out,
`--answers` back in.
