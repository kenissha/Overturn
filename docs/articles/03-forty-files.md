# Agents for Humans: Designing an agent for an advocate carrying forty files

*Overturn's interface and escalation design, and what a realistic workspace taught us
that the tests did not.*

Most agent demos have one user doing one task. Overturn's user is a patient advocate at a
nonprofit or hospital who fights insurance denials for other people. They carry dozens of
open files. Each has a deadline, missing documents and a person waiting. The job is triage
under time pressure.

That changed what "helpful" meant. An agent that produced more output would make things
worse. The design question became: **when may this system take a person's attention, and
what must it say when it does?**

## A closed list of reasons to interrupt

Overturn interrupts a person for four reasons, and no others:

1. **A document only a person can obtain is missing.** No agent can get a physician's
   letter of medical necessity.
2. **A judgment is required.** Was this service urgent? Which of two denial reasons does
   the appeal answer? Which of two conflicting sources is right? Is this critical fact
   correct?
3. **A deadline crossed a pressure threshold** — fourteen, seven or three days out.
4. **An incoming document is anomalous** — planted instructions, hidden text, a poor scan.

Everything else is logged, visible on demand, and interrupts no one. A clinical note that
has to be requested from a provider's office is work, not an interruption. The list is
published in the README, and it lives in one module — there is no general "notify the
user" path anywhere in the code.

Every question carries a *why this matters*, and the code enforces it. For example:

> **Was this service obtained in an urgent situation?**
> *Why this matters:* If it was urgent, a prior authorization exception may apply and the
> plan's response window drops from days to 72 hours. It changes both the argument and the
> clock, and no document on file settles it.

The reason is what lets the advocate decide whether to spend attention now. It also stops
the tool from sounding like it gives orders to the person it works for.

## Ask once

A background tick re-evaluates every open file every fifteen minutes, so files move
forward when nobody opens them. That is ninety-six evaluations a day. If the system asked
the same unanswered question on every tick, the advocate would turn it off — and a system
someone has turned off protects nobody.

So an escalation's identity comes from what it is about, not from when it was raised:

```python
def escalation_id(case_id: str, trigger: Trigger, subject: str) -> str:
    digest = hashlib.sha256(f"{case_id}|{int(trigger)}|{subject}".encode()).hexdigest()
    return f"esc_{digest[:12]}"
```

The same question on the ninety-sixth tick is the same escalation as on the first. Once
answered, it stays answered. The tick remembers what it has surfaced across restarts, so a
deadline crossing into a pressure band overnight produces exactly one new question.

## Today, not a table

The opening screen is not a table of forty rows. It shows at most three files that need a
person today, ordered by deadline pressure and then by how much is blocked. Each card has
the question and why it matters. Below them is one quiet line: *15 files are progressing in
the background.*

That line claims something: that the system is working when nobody is looking. So the
count has to be right.

## What a realistic workspace found

We wrote a demo seed that opens every letter of our evaluation corpus as a case, then
advances most of them as a person would — confirming facts, marking documents on file,
recording some as filed. It exists so the interface can be shown. It found three real bugs
that a few hundred unit tests had not:

- **The quiet count was wrong.** It was computed as *all files minus the three cards
  shown*, so thirty-five files that needed a person appeared as forty-five quiet ones. The
  count now means "files with nothing to ask", and a test holds the two numbers to the total.
- **Filed cases kept asking preparation questions.** A case whose appeal had already gone
  out still asked for an authorization call record. Once filed, only the clock and the
  documents can raise a question.
- **A met deadline still counted down.** After filing, the internal appeal deadline is met,
  not pending. The engine now records `met_on` on the deadline itself, and the queue, the
  gate and the timeline all read it from there.

Screenshots of the seeded workspace found more: a deadline strip drawing a zero-width
window, and the planted-instruction warning sitting below the fold. Unit tests check that
each piece is correct. A realistic workspace shows whether the product makes sense.

## The case view

The centre of the interface is a split view: the letter on the left exactly as the engine
read it, the ledger on the right. Hover a fact and the character span it was read from
lights up in the letter; hover the text and the fact lights up. That turns "the agent
does not hallucinate" from a claim into something you can check in two seconds.

A few deliberate choices:

- **Unknown values are empty boxes**, labelled *no source found* with the reason. Nothing
  is filled in to look complete.
- **Document text and quotes are monospace.** They are evidence, and should look like it.
- **Colour is reserved for deadline pressure and for escalations.** The rest is neutral, so
  red always means something.
- **There is no chat.** The agent asks, the person answers, and the answer lands in the
  ledger as `human_answered` or `human_verified`, with their name on it.
- **The draft says on its face that Overturn has not sent it.** Filing is recorded by a
  person — as a record, not a submission — and that starts the plan's response clock.

## What the advocate keeps

Overturn takes six of the seven things an advocate does on a file: read the denial, find
the policy basis, know what evidence the category needs, check what is on file, compute
the deadline, and draft the argument. The seventh — factual judgment, *was this urgent?* —
stays with the person, and the system's whole job at that point is to ask clearly and
explain why.

Overturn is MIT licensed: [github.com/kenissha/Overturn](https://github.com/kenissha/Overturn).

*Built for the AWS Agents for Humans Hackathon, Good Neighbor Agents track.*
