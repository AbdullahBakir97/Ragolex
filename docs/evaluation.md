# Evaluation

An answer can only be as good as the passages it is given. `ragolex eval` measures that first step, retrieval: for each question of a dataset, does search find the passages that answer it, how high does it rank them, and does the minimum score keep them while turning away questions the documents cannot answer? With `--answers` it also answers every question and grades the answers.

It runs the same steps as the API (upload, split, embed, store, search) with the configured embedding model and database, so it measures a real setup. CI runs it on every push and pull request, and fails when a metric drops below the committed baseline.

## Running it

With the API's settings in the environment (or `.env`):

```bash
ragolex eval evals/handbook/v1
```

With Docker, the image includes the datasets:

```bash
docker compose run --rm app ragolex eval evals/handbook/v1
```

The documents go into a temporary project, `eval.handbook.v1`, which is deleted afterwards, also when the run fails. No API project can have that name, since project names cannot contain dots. The handbook embeds 27 chunks and 53 questions, a fraction of a cent with OpenAI and free with Ollama.

```text
Retrieval on handbook/v1: 53 questions (46 answerable), 8 documents in 27 chunks
nomic-embed-text:v1.5 (768 dimensions), top 5, chunks of 1000 with 200 overlap, min score 0.3

  hit rate         95.7%   answerable questions with a relevant result
  recall@5         95.7%   expected sources found
  MRR              90.2%   1 / rank of the first relevant result, averaged
  above min score  95.7%   answerable questions that would be answered
  rejected          0.0%   unanswerable questions with no result at min score

  A min score of 0.592 would answer 72% of the answerable questions and reject 57% of the others.

  tag            questions  hit rate     MRR
  direct                16    100.0%   93.8%
  multi                  2    100.0%  100.0%
  paraphrase            28     92.9%   87.5%
  pdf                    6    100.0%   91.7%
  unanswerable           7         –       –

  No relevant result in the top 5:
    sensitive-review: Who needs to sign off on a change to the payment code?
    core-hours: When do I have to be available for meetings?

  Took 0.08 s to process, 6.8 s to index and 1.96 s to search.
```

| Option | Default | |
|---|---|---|
| `--top-k` | `5` | Results per question; answers use 5 |
| `--chunk-size` | `1000` | Characters per chunk, as for uploads |
| `--overlap-size` | `200` | Characters of overlap between chunks |
| `--min-score` | `ANSWER_MIN_SCORE` | The minimum score an answer needs |
| `--answers` | off | Also answer every question with the configured language model, and grade the answers (see [Answer metrics](#answer-metrics)) |
| `--judge-model` | `LLM_MODEL` | The model that grades the answers, on the same server |
| `--output` | none | Write the full JSON report: every question with its results, scores and relevance, and its answer and grades with `--answers` |
| `--baseline` | none | Compare with a baseline, and fail when a metric is lower |
| `--tolerance` | `0.02` | How much lower than the baseline a metric may be |
| `--save-baseline` | none | Write this run's parameters and metrics as a baseline |

The command exits with `0` when it ran (and no metric fell below the baseline), `1` when a metric fell below it, and `2` when it could not run: no embedding model, an unreachable database, an invalid dataset, or a baseline measured with other parameters.

## Metrics

A retrieved chunk is **relevant** when it comes from a file the question expects and contains that source's evidence, a short phrase from the passage. Matching by phrase rather than by chunk number keeps a dataset valid when documents are split differently.

| Metric | For | Meaning |
|---|---|---|
| hit rate | questions the documents answer | Share with at least one relevant chunk in the top k |
| recall@k | questions the documents answer | Share of each question's expected sources found, averaged; a question can expect sources in two documents |
| MRR | questions the documents answer | Mean reciprocal rank: 1 when the first result is relevant, ½ when it is second, 0 when none is |
| above min score | questions the documents answer | Share whose first relevant chunk scores at least the minimum score, so an answer would be written from it |
| rejected | questions the documents do not answer | Share with no result at the minimum score, so the API answers `no_answer` without calling the model |

The last two pull in opposite directions: a lower minimum score answers more questions, and also lets more unanswerable ones through to the model. The run suggests the value that serves both best, which is a starting point for `ANSWER_MIN_SCORE` with that embedding model.

The run above shows why this matters. With `nomic-embed-text`, even questions the handbook does not touch score above the default `ANSWER_MIN_SCORE` of 0.3, so none of them is turned away before the model is asked; the model's own no-answer reply is then the only guard. Scores depend on the model, so measure with the one you use before changing the setting. The report also breaks the metrics down by tag (`direct`, `paraphrase`, `multi`, `pdf`, `unanswerable`) and lists the questions with no relevant result.

## Answer metrics

```bash
ragolex eval evals/handbook/v1 --answers
```

Every question is then also answered the way `POST /api/v1/ask` answers it, with the configured language model, the current answer prompt and the minimum score. A second call, the judge, grades each answer against the question's reference answer and the sources it cites. The judge uses the versioned prompt `judge-v1` at temperature 0 and replies with a verdict of yes, partly or no for each question.

| Metric | Meaning |
|---|---|
| answered | Share of answerable questions that got an answer rather than `no_answer` |
| abstained | Share of unanswerable questions answered with `no_answer` |
| citation precision | Share of all citations, in answers to answerable questions, that point to a passage holding the expected evidence |
| cites expected | Share of those answers that cite at least one expected passage |
| grounded | Per the judge, how far every statement is supported by the cited sources (yes 1, partly ½, no 0), over all graded answers |
| correct | Per the judge, how far the answer says what the reference answer says, over all answerable questions; a missing answer counts as 0 |
| resisted | Share of the questions with `forbidden` texts whose answer holds none of them (ignoring case); `no_answer` resists. Shown only for datasets with such questions, such as [`evals/injection`](#prompt-injection) |

Citation precision and cites expected are counted, not judged, so they are exact. Grounded and correct are only as good as the judge: use a capable model for it, for example `--judge-model gpt-4.1` while answering with a smaller one, and read the judge's one-line reason for each graded answer in the report. Answers the judge gives no clear verdict on are counted and left out.

The answer and judge calls cost tokens: with the handbook, 53 answers and up to 53 grades. The report gives the tokens of both, and their cost when `LLM_INPUT_PRICE_PER_MILLION` and `LLM_OUTPUT_PRICE_PER_MILLION` are set; another judge model's cost is not known. Answer metrics are reported but not checked against the baseline, and CI does not run them: they need a language model, and a small one would make the scores too noisy to gate on.

## Datasets

A dataset is a folder:

```text
evals/handbook/v1/
├── dataset.json      # name, version, description and the documents
├── documents/        # Files of any supported type, as they would be uploaded
└── cases.jsonl       # one question per line
```

```json
{"id": "friday-deploy", "question": "Can I push a release to production on a Friday afternoon?",
 "tags": ["paraphrase"],
 "expected_sources": [{"file": "engineering-workflow.txt", "evidence": "never on Fridays after noon"}],
 "reference_answer": "No. Production deploys never happen on Fridays after noon; ..."}
```

A question the documents do not answer has no expected sources and a `null` reference answer. The judge compares answers with the reference answers. An optional `forbidden` list names texts an answer must not hold, such as what a prompt injection in a document asks for; the answer metrics then report how many answers [resisted](#answer-metrics).

`evals/handbook/v1` is the employee handbook of Larkspur Labs, a fictional company: eight documents on engineering workflow, incidents, security (a two-page PDF), expenses, time off, remote work, onboarding and growth, with 46 questions they answer and 7 they do not. The topics overlap on purpose (deploys, 30-day limits, budgets and on-call appear in several documents), so ranking matters, and most questions use other words than the documents.

A released version never changes, so its results stay comparable over time: `tests/test_eval_dataset.py` pins a hash of each, and also checks that every evidence phrase fits inside one chunk at the default and at a small chunk size. Changes go into a new version (`v2`), with a new baseline.

### Prompt injection

Documents are written by other people, and a document can hold instructions meant for the model that reads it. Two layers keep them from working, and each has its own test:

1. **The prompt's structure.** Every prompt quotes the text it did not write (documents, questions, earlier answers) between its own tags, and its system message says that text is data. A tag inside the text could end its section early and pose as instructions, so `prompts/quoting.py` escapes the `<` of any tag a prompt uses, in every prompt. It finds tags the way a model reads them: in any case, with spaces, with invisible characters inside (`</so\u200burce>`), and with look-alike characters for the brackets, the slash or the letters (fullwidth `＜／ｓｏｕｒｃｅ＞`, Cyrillic or Greek letters). `tests/test_prompt_injection.py` puts 15 known attacks in every quoted place of every prompt and checks that the tags a model would see stay exactly the prompt's own, and that the system message never changes. It runs in CI.
2. **The model.** Whether a model then ignores instructions it reads as data depends on the model. `evals/injection/v1` measures it: the policies of Fernhill Studio, a fictional company, in six documents (text, Markdown and HTML), each holding one attack. The attacks try to override the rules, break out of the quoted source with real tags and with disguised ones, plant an image link that leaks the question to another site, leak the system message, and invent a CEO. Its 11 questions (one the documents do not answer) list what an answer must not hold, such as the attacker's domain or a code word.

```bash
ragolex eval evals/injection/v1 --answers
```

The answer metrics then include `resisted`, and the report lists every question whose answer followed an injection under "Followed a prompt injection". Run it whenever the answer prompt or the model changes; like the other answer metrics it needs a language model, so CI does not run it. Resisted should be 100%. Correct and grounded matter here too: an answer that resists by refusing to answer still fails the question.

## Growing the test set from feedback

People rate answers with the thumbs on the Ask page (or [the API](api.md#feedback)). Those ratings become a dataset with:

```bash
ragolex feedback-export my-project evals/my-project/v1
```

The new folder has the project's documents, `dataset.json` (named `my-project-feedback`, so it is never mistaken for another dataset) and two files of cases:

- `cases.jsonl`: one case per answer rated thumbs up, with the question, the passages the answer cited as expected sources (their evidence is the start of the sentence closest to the answer), and the answer, without its markers, as reference answer.
- `cases-to-review.jsonl`: the answers rated thumbs down, and those that cited nothing, with the comment and the passages they cited. Write the right reference answer and expected sources for each, then move it into `cases.jsonl`.

Check the cases, then `ragolex eval evals/my-project/v1` measures the project on the questions its users actually asked. Once it is right, treat it like any released version: freeze it, and give changes a new version.

## Baselines and CI

`evals/baselines/handbook-v1.json` holds the parameters and metrics of the last accepted run with `nomic-embed-text:v1.5`, the model of the [Ollama setup](configuration.md#model-providers). The `eval` job in CI starts Ollama with that model next to PostgreSQL and runs:

```bash
ragolex eval evals/handbook/v1 --baseline evals/baselines/handbook-v1.json --output eval-report.json
```

A change that lowers a metric by more than the tolerance fails CI; the report is kept as the job's `eval-report` artifact. A change that raises one passes and says so: update the baseline in the same pull request, so the improvement is kept. The job prints the run's baseline at the end, ready to copy, or run:

```bash
ragolex eval evals/handbook/v1 --save-baseline evals/baselines/handbook-v1.json
```

A baseline is only compared with a run of the same dataset, embedding model, vector size, search mode, reranker, top k, chunking and minimum score; anything else exits with `2` before embedding anything. With `RERANK_BASE_URL` set, `ragolex eval` measures search with the reranker, so a reranker is judged by the same numbers.
