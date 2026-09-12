# Devpost submission — draft

Paste-ready text for the submission form. Every claim here is backed by something in the
repository; numbers that have not been measured are not quoted.

---

## Tagline

An appeal agent for patient advocates: every fact has a source, every deadline is
computed, and it asks a person only when a person is needed.

## Track

Good Neighbor Agents.

## Inspiration

When a health insurer denies a claim, the denial is often wrong: on HealthCare.gov plans
in 2024, insurers reversed a third of the denials appealed to them, and Pennsylvania's
independent reviewers have overturned about 48% of the denials they examined. Yet fewer
than 1% of denied claims are appealed. Not because they lack a case — because the
process is exhausting and deadlines pass. These files are lost on procedure, not on the
merits.

Patient advocates fight these denials for other people, dozens of files at a time, and
turn people away for lack of hours. Helping one advocate helps everyone on their list.

## What it does

Overturn works an advocate's denial files in the background.

- It reads each denial letter into a **fact ledger** where every value points at the
  exact characters it was read from. A value it cannot source is recorded as *missing*,
  with the reason, and shown as an empty box — never guessed.
- A **deterministic engine** — plain code, no model — classifies the denial against
  versioned rule packs, works out which facts and documents the appeal needs, computes
  every deadline, and assembles the appeal paragraph by paragraph from established facts.
- It interrupts a person for **four reasons only**: a document only they can obtain, a
  judgment only they can make, a deadline under pressure, or a document that is not what
  it seems. Each question says why it matters, and is asked once.
- The advocate answers, confirms the facts that change the outcome, and files. **Overturn
  never sends anything** and never gives legal advice.

## How we built it

- **Extraction agent**: Strands Agents SDK with Claude on Amazon Bedrock. It holds exactly
  two tools — record a fact by quoting it, or record that the letter is silent — bound to
  one document. The tool locates the quote on the page itself and refuses anything it
  cannot find.
- **Amazon Bedrock AgentCore**: the extraction agent is packaged as an AgentCore runtime.
  Only the untrusted zone runs there, and everything it proposes is verified again by the
  local ledger before it is recorded.
- **Deterministic engine**: Python and Pydantic — deadlines, five YAML rule packs,
  classification, evidence, anomaly detection, the escalation gate and argument planning.
- **Cross-document checks**: plan documents are read for what they cover. When two
  documents disagree, the ledger keeps both readings with their quotes as a conflict for
  the advocate — often the strongest argument in the file — and a document never
  overwrites what a person confirmed.
- **Interface**: React and TypeScript over a thin FastAPI layer, with a background tick
  that re-evaluates every file every fifteen minutes.
- **Tracing**: OpenTelemetry through Strands, one span per pipeline step, carrying
  identifiers and counts and never a value from a document.
- **Evaluation**: a synthetic corpus with an answer key, a harness calibrated before
  scoring, and a red-team suite that runs on every build.

## Challenges we ran into

- **Making provenance structural.** Asking a model to cite its sources is a request.
  Making the tool refuse unsourced values is a guarantee. Models turned out to be bad at
  character offsets and good at copying text, so the agent now quotes and the tool finds.
- **Prompt injection.** Rather than asking the model to ignore instructions in documents,
  the agent that reads documents holds no power worth hijacking. The residual risk —
  planted text read as a plausible fact — is contained by requiring a person to confirm
  critical fields, and we publish it rather than hide it.
- **Restraint.** An agent that asks the same question every fifteen minutes gets switched
  off. Escalations take their identity from what they are about, not when they were raised.
- **A realistic workspace found bugs the unit tests did not**: a miscounted "quiet" line,
  filed cases still asking preparation questions, and a reason code filed under the wrong
  denial category — which would have argued against a reason the plan never gave.

## Accomplishments that we're proud of

- A fact in the ledger can always be traced to a line in a letter, a deadline to a rule,
  and an omission in the draft to a missing fact or document.
- The capability surface of the untrusted zone is a test: if anyone adds a method to it,
  the build fails.
- The evaluation is honest about itself: the corpus is synthetic and says so, the harness
  is calibrated before any model is scored, and results are published as measured.

## What we learned

The most useful thing an agent can show a person is often what it does not know. The empty
box that says *the letter does not state this* is the part of the screen an advocate acts on.

## What's next

- Model-backed evaluation results, published whatever they show.
- Deploying the AgentCore runtime and running the demo against it.
- Redacted real denial letters in the evaluation corpus.
- OCR for scanned letters, and state-specific deadline rules.

## Built with

Python · Strands Agents · Amazon Bedrock · Amazon Bedrock AgentCore · Claude · Pydantic ·
FastAPI · React · TypeScript · Vite · OpenTelemetry

## Links

- Repository (MIT): https://github.com/kenissha/Overturn
- Demo video: *to add*
- Articles on builder.aws:
  - Solving prompt injection with permissions, not prompts: https://builder.aws.com/content/3JEIG7BsbHmltHiJGpvPAdImxsh/agents-for-humans-solving-prompt-injection-with-permissions-not-prompts
  - Designing an agent for an advocate carrying forty files: https://builder.aws.com/content/3JEJZjGBudaLVx99JpGPi0a3GXH/agents-for-humans-designing-an-agent-for-an-advocate-carrying-forty-files
  - Why our appeal agent never gets to decide: *to add*

## Before submitting

- [ ] Numbers in "What it does" and the video match the README at the time of submission
- [ ] The video says the demo workspace is written from the answer key, unless it shows
      the live agent
- [ ] The AgentCore sentence matches what is actually deployed
- [ ] Repository About shows the MIT license
