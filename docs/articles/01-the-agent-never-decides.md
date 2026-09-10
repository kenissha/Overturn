# Agents for Humans: Why our appeal agent never gets to decide

*Building Overturn, an insurance-denial appeal agent for patient advocates, on Strands
Agents and Amazon Bedrock.*

When a health insurer denies a claim, the denial is often wrong. On 2023 ACA marketplace
plans, about a third of internal appeals reversed the decision, and consumers won roughly
45% of external reviews. Yet almost nobody appeals.

The reason is rarely that people lack a case. Appeals are lost on procedure: a deadline
passes, the wrong document goes in, or the letter argues against a reason the insurer
never gave. A patient advocate — the person whose job is to fight these — might carry forty
files a week and turn people away for lack of time.

Overturn takes the mechanical part of that work: reading the denial, finding what is
missing, watching the clocks and assembling the appeal. This post is about the one design
rule the rest of it depends on:

> **The model reads. Code decides. A person files.**

## Three layers, one source of truth

```
LAYER A — Grounded extraction        (model, untrusted zone)
Reads one document. Records facts it can quote, or records that the letter is silent.
        |
   FACT LEDGER   every value carries document, page and character span
        |
LAYER B — Deterministic engine       (plain Python, no model)
Denial category, required evidence, deadlines, escalation, the appeal's argument.
        |
THE ADVOCATE
Answers what only a person can answer. Confirms what matters. Files.
```

The model has exactly one job: turn a denial letter into structured facts. Everything that
could lose a file — which deadline applies, what the appeal needs, whether it is ready,
when to interrupt someone — is ordinary code with ordinary tests.

That is not modesty about what models can do. It is about what kind of mistake you can
live with. A wrong deadline is a lost appeal. If deadline arithmetic lives in a prompt,
every wrong answer is a sampling artefact you cannot reproduce. If it lives in code, a
wrong answer is a bug with a failing test.

## Provenance is enforced by the tool, not requested in the prompt

The extraction agent is built with the Strands Agents SDK and holds two tools:

```python
@tool(name="write_fact")
def write_fact(field: str, value: str, page: int, quote: str, confidence: float) -> str:
    """Record one fact the document states, with the exact text that states it."""
    return str(writer.write_fact_by_quote(field, value, doc_id, page, quote, confidence))

@tool(name="mark_missing")
def mark_missing(field: str, reason: str) -> str:
    """Record that the document does not state this field."""
    return str(writer.mark_missing(field, reason))
```

Three details carry the weight.

**The agent quotes; the tool finds.** Early on the tool asked the model for character
offsets. Models copy text well and count characters badly, so now the model supplies the
quote and the page, and the tool locates the quote on that page. If the quote is not
there, nothing is written and the refusal goes back to the agent as a readable message.
The guarantee got stronger and the agent got more reliable at the same time.

**The document is bound when the tool is built.** There is no `doc_id` parameter. The agent
cannot cite a document it was not given.

**Values are converted by code.** "August 1, 2026" and "08/01/2026" both become
`2026-08-01` in a parser. Date handling is the first step of date arithmetic, and we do not
hand date arithmetic to a model.

Under the tool sits a Pydantic model that will not construct a fact carrying a value
without a source. A test states the claim directly:

```python
def test_a_value_without_a_source_is_refused():
    """The claim: a model cannot record a value it cannot point at."""
    with pytest.raises(ProvenanceRequired):
        make(provenance=None)
```

## "Missing" is a result, not a gap

Most systems represent an unknown value as an absent key, and then something downstream
fills it with a guess. In Overturn, absence is a recorded state with a reason:

| Status | Meaning |
|---|---|
| `extracted` | Read from a document with a verified citation |
| `human_verified` | A person confirmed it against the original |
| `missing` | No source found — deliberately not invented |
| `regime_default` | A statutory default, never presented as read from the letter |

Abstaining has its own tool, so "the letter does not say" is an explicit, audited action.
That also makes it measurable: the evaluation harness scores *correct abstention*, and an
extractor that stays silent gets no credit for it.

In the interface a missing value is drawn as an empty box with the reason beside it. It
is the most useful thing on the screen, because it is the thing the advocate has to go
and get.

## What the deterministic layer knows that a model would guess

A few rules from the engine show why this layer is code:

- **A date printed in the letter beats the statutory default.** Federal timeframes are a
  floor; states and plans extend them. When the engine falls back to a default it says so,
  and the interface draws that deadline dashed rather than solid.
- **The clock runs from receipt, not from the notice date.** If the receipt date is
  unknown the engine uses the notice date, which is on or before receipt and so can only
  make the deadline *earlier*. There is a test called
  `test_the_fallback_can_only_shorten_the_window`.
- **Compute what is knowable, block what is not.** A missing fact blocks only the
  deadlines that depend on it, and the advocate is told which fact would unblock it.
- **Decline when unsure.** A letter that cites two denial reasons is a trap: appealing the
  wrong one loses the file. When two rule packs score within a margin of each other, the
  classifier selects nothing and asks a person.

## The appeal is assembled, not generated

Denial categories are versioned YAML rule packs. Each declares how to recognise the
category, which facts and documents an appeal needs, and the paragraphs it may contain:

```yaml
- id: necessity_argument
  claim: >-
    The treating physician has documented the medical necessity of this service in the
    attached letter of medical necessity.
  requires_evidence:
    - letter_of_medical_necessity
```

A paragraph is written only when every fact it names is established and every document
it relies on is on file. Otherwise it is left out, and the draft says what is missing.
Placeholders are filled from the ledger, so no sentence in the draft was written by a model.

Packs contain no executable code. An early design used Python expressions for conditional
paragraphs; that would have put an `eval()` at the end of a pipeline whose premise is that
untrusted text never reaches execution. Conditions are declarative now.

## What this costs, honestly

The demo is less flashy than an agent that writes the whole appeal in one go. That is the
point. What we gave up in fluency we got back as properties we can state and test: every
value can be traced to a line in a letter, every deadline to a rule, and every omission
is explained.

Two limits we state rather than hide. Our evaluation corpus is synthetic, so its scores
are an upper bound on real-world performance, not an estimate of it. And model-backed
extraction numbers will be published in the repository when measured — including if they
are unflattering.

Overturn is open source under the MIT license: [github.com/kenissha/Overturn](https://github.com/kenissha/Overturn).

*Built for the AWS Agents for Humans Hackathon, Good Neighbor Agents track.*
