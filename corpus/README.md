# Evaluation corpus

Every letter in the evaluation corpus, as files.

- `samples/<id>.txt` — the letter. Pages are separated by form feeds, which is exactly what
  the upload endpoint (`POST /api/cases/{id}/documents`) accepts, so any of these can be
  uploaded through the interface as a real file. Letters that plant invisible characters
  keep them.
- `samples/<id>.json` — its answer key: every scored field with its value and the quote it
  can be read from (or `null` where the letter deliberately does not say), the expected
  rule pack, and any anomalies that must be detected.

**These files are generated.** The source of truth is `overturn/eval/corpus.py`; regenerate
with `python -m overturn.eval.export`, and a test fails if the two drift apart.

**Every letter is synthetic.** Insurers, providers and members are fictional. See
`docs/eval-results.md` for the corpus composition and what synthetic letters can and
cannot tell you.

A handful worth opening:

| Letter | What it tests |
|---|---|
| `s001` | an ordinary medical necessity denial in the federal model-notice layout |
| `s025`–`s030` | two denial reasons in one letter — the classifier must decline |
| `s031`–`s034` | not a denial Overturn handles — it must say so rather than guess |
| `s035`, `s039` | instructions hidden in invisible characters |
| `s038`, `s042` | a planted `SYSTEM:` line |
| `s043`–`s046` | a second, planted notice date — the ledger must not pick one |
| `s047`, `s048` | no notice date at all — the deadline must be asked, not assumed |
| `s049`–`s060` | out-of-network, coding error and experimental denials |
