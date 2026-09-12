# Where the build departs from the plan

This project started from a planning document, written before any code and kept out of
the repository. Most of it was built as written: the advocate as primary user (D-01), the
model deciding nothing (D-05), no fact without a source (D-06), trust zones enforced by
capability rather than by prompt (D-07), nothing sent on anyone's behalf (D-08), no legal
advice (D-09), rule packs as data (D-10), MIT (D-11).

Where the build differs, the reason is recorded here. The decisions the plan numbered
D-01 to D-11 are quoted by number so this page stands on its own.

## Agents

**One model-backed agent, not six.** The plan sketches IntakeAgent, ExtractionAgent,
PolicyCrossCheckAgent, DrafterAgent, TriageAgent and a NotificationTool, composed as a
Strands Graph. The build has one: the extraction agent.

| Planned | Built | Why |
|---|---|---|
| IntakeAgent | Deterministic ingest: normalisation, hashing, anomaly scan | Nothing in intake needs judgement. Text normalisation done by a model would be text the ledger cannot index into reliably. |
| PolicyCrossCheckAgent | The extraction agent reads plan documents with a different field list; the ledger records disagreements as conflicts | Cross-checking two documents is a comparison, and comparisons belong to code. The model reads each document on its own; when two readings differ, the ledger keeps both, with their quotes, and a person decides. |
| DrafterAgent (Layer C) | The engine assembles the appeal from the argument plan, one sentence per step | Every sentence a model writes is a place an unsupported claim can enter, which is the failure D-06 exists to prevent. An assembled letter is plainer. It is also checkable: each paragraph names the fact it rests on. The `drafting` model role is kept in `config/models.yaml`, marked reserved, for optional polish that would read the argument plan and never a document. |
| TriageAgent | The morning queue is ordered by code: deadline pressure, then how many questions block the file, then the soonest clock | "Which file needs someone today" is a function of dates and open escalations. D-05 says a model does not decide that, and the queue has to be right every morning, not usually. |
| NotificationTool | No outward-facing tools; the queue is the notification | D-08. The trusted zone in this version has nothing that reaches outside the application. |
| Strands Graph | A plain pipeline | With one model-backed step there is nothing for a graph to route. The zone boundary is enforced by the extraction agent's tool list, which is exactly two ledger writers and is pinned by a test. |

## Citations

**The model quotes; code finds the span.** The plan's ledger schema has the extractor
report character offsets (`char_span`). Models miscount characters, and an offset cannot be
checked by looking at it. The extraction tool instead takes the words the value was read
from; the ledger locates that quote on the stated page and records the span itself. A quote
that is not on the page is refused. Provenance still carries `char_span` — computed, not
claimed.

**Values are converted by code.** The model passes the value as written ("March 3, 2026");
the tool converts it to the field's type. Date arithmetic is never asked of the model:
converting "within 180 days" into a date is scored as an error, because that is the
deadline engine's job.

## Rule packs

**No expressions evaluated from pack files.** Pack conditions are declarative matches over
reason codes and ledger fields. A rule pack is data someone other than the author may
write; it should not be able to run code.

**Narrower than first drafted.** CO-50 alone selects medical necessity. CO-15 was removed
from prior authorization because X12 deactivated it on 2018-05-01 (a letter that still
prints it is recognised by its wording instead). CO-55 (experimental, now its own pack) and
CO-167 (diagnosis not covered) were taken out of medical necessity, where they had been
misfiled. A pack that declines is better than one that guesses: letters it does not
recognise go to a person.

## Metrics

**"Zero missed deadlines" is a goal, not a published result.** The plan lists it as a
success metric. It cannot be measured without a deployment and time. What is published
instead is measurable now: deadline accuracy on the corpus, and the deadline-pressure
trigger of the escalation gate, which puts a file in front of a person as a clock runs
down or when a clock cannot be computed — tested, rather than promised.

**Statistics were checked against primary sources.** The figures in the plan's problem
section were reverified before anything was published. Some changed, and one could not be
sourced and was dropped. The published figures and their sources are in
[sources.md](sources.md).

## Evaluation

**The circularity problem is addressed, not ignored.** An evaluation corpus written by the
same hand that writes the extractor measures little. The generator shares no code with the
extraction path, the answer key comes from the generator's inputs rather than its output,
and the corpus is published so anyone can test against it. Every letter is still
synthetic, and [eval-results.md](eval-results.md) says so first.

**Fact poisoning is contained downstream, and measured.** Privilege separation does not
stop a planted date that is genuinely on the page. The containment is that critical facts
cannot enter a packet until a person confirms them against the original. The red-team
corpus reports detection and containment separately, because they are different claims.

## Deployment

**Only the untrusted zone runs on AgentCore.** The runtime receives document text and
returns proposed facts with quotes. Those proposals are replayed through the local ledger,
which verifies every quote again before anything is recorded. A compromised or confused
remote agent can propose; it cannot write.

## Models

**Claude Opus 5 for every role, no sampling parameters.** The plan sketches a cheaper tier
for extraction. That is a cost decision to make against measured results, not in advance,
and it is one line in `config/models.yaml` when made. Opus 5 rejects `temperature` and
`top_p`, so behaviour is steered by the prompt and the tools.
