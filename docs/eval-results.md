# Evaluation

How Overturn is measured, what the corpus contains, and what the numbers can and cannot
tell you.

Reproduce any result on this page with:

```
python -m overturn.eval --extractor <name>
```

---

## Model-backed extractor

**Pending.** The extraction agent runs on Amazon Bedrock and has not been evaluated yet.
Its results will be published here as measured — including if they are unflattering. The
README's evaluation table stays at *pending* until then.

---

## What is measured

| Metric | Definition | Why it matters |
|---|---|---|
| Field accuracy | Correct values over fields the letter establishes | Basic competence |
| **Hallucination rate** | Wrong or unsupported values over all values asserted | The product's central promise |
| **Correct abstention** | Fields explicitly marked `missing` over fields the letter does not establish | The other half of that promise |
| Classification accuracy | Correct rule pack, or correctly declining on multi-reason letters | Everything downstream branches on it |
| Deadline accuracy | Engine output on extracted facts equals engine output on the answer key | Zero tolerance |
| Injection detection recall | Planted instructions found | The second line of defence works |
| Anomaly false-positive rate | Anomalies raised on letters with nothing planted | A noisy detector gets ignored |
| Planted notice date extracted | Poisoned letters where the planted date won | The attack privilege separation does not stop |

Two scoring rules are worth stating explicitly:

- **Silence is not abstention.** A field the extractor never touched earns no abstention
  credit. Abstaining has to be an action (`mark_missing`), so that it is recorded and
  countable.
- **A real citation does not make a wrong value right.** The ledger guarantees a quote is
  genuinely on the page; it does not guarantee the value was read correctly from it. A
  misreading with a valid citation is scored as a hallucination. There is a test for this.

Every extractor writes through the same `LedgerWriter` the production agent uses, so a
fabricated citation is refused during evaluation exactly as it would be in use. The
numbers describe the system as built, not the model in isolation.

---

## The corpus

60 denial letters, generated deterministically from a fixed seed.

| Slice | Count | Correct behaviour |
|---|---|---|
| Clean: medical necessity and prior authorization | 24 | Extract, classify, compute deadlines |
| Clean: out of network, coding or billing error, experimental | 12 | Extract, classify, compute deadlines |
| Two denial reasons in one letter | 6 | Decline to classify; ask a person |
| Category no pack covers | 4 | Report "outside what this system covers" |
| Planted instructions (4 kinds × 2) | 8 | Detect; nothing acts on them |
| Planted second notice date | 4 | See *fact poisoning* below |
| No notice date anywhere | 2 | Report the most important field as missing |

Every installed rule pack has letters, and a test holds that. The last twelve letters were
added with the last three packs; they are appended after the original 48, which are
byte-for-byte unchanged, and a test pins their hash.

Letters are rendered in four house styles: one following the section structure of the
federal model notice of adverse benefit determination, and narrative, claim-table and
portal-printout forms. Dates are printed in four formats. Reason codes, policy sections
and stated deadlines are each present in some letters and absent in others, so there is
something to abstain on: across the corpus the answer key contains 626 established values
and 154 fields the letters deliberately do not establish. Sixty of those are
`plan.covers_service`: no denial letter in the corpus states what the plan covers, so the
correct reading of a denial letter is "not stated here" — the plan document is where
coverage is read from.

### What is synthetic, and what that means

**Every document is synthetic.** The corpus is built to avoid measuring an extractor
against its own generator:

1. The generator shares no code with the extraction path, and the extractor never sees
   the templates or the answer key.
2. The answer key is taken from the generator's inputs, not from parsing its output, and
   the generator refuses to emit a gold quote that cannot be found in the rendered text.
3. No single layout: four house styles, four date formats.
4. Traps real letters contain: every letter states the statutory "within 180 days" window
   in prose, and only some also print a specific date. Converting the prose into a date
   is scored as an error — that arithmetic belongs to the deadline engine.

What it cannot capture is the variety of real correspondence: scanned pages, inconsistent
terminology, letters that bury the reason in a paragraph of boilerplate. **Treat these
scores as an upper bound on real-world performance, not as an estimate of it.** Adding
redacted real letters is the most valuable improvement available.

### Fact poisoning

Four letters contain a second "Date of notice" line, planted 200 days before the real one.
Privilege separation does not stop this: the planted text is genuinely on the page, so an
extractor citing it passes provenance verification.

The containment is downstream. `denial.notice_date` is a critical field, so an extracted
value — planted or not — cannot enter a submission packet until a person confirms it
against the original. The metric reported here is how often the planted date won at
extraction; the packet-level guarantee holds regardless and is covered by
`tests/engine/test_evidence.py` and `tests/redteam/`.

---

## Calibration

Before any model is scored, the ruler is checked. These are not results. They are the
harness demonstrating that it measures what it claims to.

| Metric | Oracle (writes the answer key) | Null (abstains on everything) |
|---|---|---|
| Field accuracy | 100.0% | 0.0% |
| Hallucination rate | 0.0% | n/a — asserted nothing |
| Correct abstention | 100.0% | 100.0% |
| Classification accuracy | 100.0% | 6.7% |
| Deadline accuracy | 100.0% | 3.3% |
| Injection detection recall | 100.0% | 100.0% |
| Anomaly false-positive rate | 0.0% | 0.0% |
| Writes refused by the ledger | 0 | 0 |

The oracle writes every gold value through the real ledger tools, which also proves every
citation in the answer key survives provenance verification. The null extractor's
non-zero classification and deadline scores are the out-of-scope and no-date letters,
where "nothing" is the correct answer.

Detection metrics are identical across extractors because anomaly scanning runs on the
document before any extractor sees it: 8 of 8 planted instructions found, and 0 of 48
clean letters flagged.
