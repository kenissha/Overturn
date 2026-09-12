# Demo video — click-by-click shot list (4:40)

The companion to [video-script.md](video-script.md). That one explains the beats; this one
says exactly what to open, what to click and what to read aloud. Every line is short on
purpose: it is meant to be read, not performed.

## Before you record

```bash
python -m overturn.demo --reset --today 2026-10-04
OVERTURN_DATA_DIR=data/demo OVERTURN_TODAY=2026-10-04 \
  uvicorn --factory overturn.api.app:app_from_env --port 8000
cd web && npm run dev
```

- Browser at 1600x1000, zoom 100%, bookmarks bar hidden, no other tabs visible.
- Have these four addresses ready (paste, do not type, on camera):

| # | Address |
|---|---|
| 1 | `http://localhost:5173/#/` |
| 2 | `http://localhost:5173/#/case/case_01M26BGMATTJCFWXWE` |
| 3 | `http://localhost:5173/#/case/case_01M26BGGK24KEJZENW` |
| 4 | `http://localhost:5173/#/case/case_01M26BGK96F8RQAQ6J/draft` |

Case ids come from the seeded workspace. If you re-seed, they change: open **Today**, and
the three cards are the same three files.

Two sentences must be said out loud somewhere in the video, and both are in the script
below: the demo workspace is written from the evaluation answer key rather than by a
model, and the clock is pinned to 4 October 2026.

---

## Shot 1 — The problem (0:00–0:40)

**Screen:** address 1, the Today screen.

> "When a health insurer denies a claim, the denial is often wrong. Insurers reverse about
> a third of the denials that are appealed to them. But fewer than one percent of denied
> claims are ever appealed. These files are not lost on the merits. They are lost on
> procedure: a deadline passes, a document is missing, or the appeal answers the wrong
> reason.
>
> Overturn is built for patient advocates — people who fight denials for other people,
> forty files at a time. This is their morning."

## Shot 2 — The morning queue (0:40–1:15)

**Screen:** stay on Today. Move the cursor slowly over one card, then the quiet line.

> "Not a table of forty rows. Three files that need a person today. Each card carries the
> question, and why it matters. Underneath, one line says how many files are moving
> without anyone: nineteen are progressing in the background.
>
> Two things about this demo. The clock is pinned to October fourth, twenty twenty-six.
> And the facts in this workspace were written from the evaluation answer key, not by a
> model — the trace screen names the writer, and I will show it."

## Shot 3 — The letter and the ledger (1:15–2:15)

**Screen:** address 2.

Click nothing for a moment. Then **hover a fact on the right** — *Notice date* — and let
the viewer see the matching text light up in the letter on the left.

> "The letter is on the left, exactly as the system read it. The ledger is on the right.
> Every value carries the words it was read from. Hover a fact, and the exact characters
> it came from light up in the letter.
>
> This one is marked critical, and it says *read, unchecked*. A fact that changes the
> outcome cannot go into an appeal packet until a person confirms it against the original."

Scroll the ledger down to a field showing an empty box.

> "And this is the part I care about most. The letter does not give a reason code, so the
> system does not invent one. It draws an empty box that says: no source found. That empty
> box is the thing the advocate has to go and get."

## Shot 4 — Two documents that disagree (2:15–2:50)

**Screen:** same case. Scroll the ledger to **Plan covers service**.

> "This file has two documents: the denial letter, and the plan's own evidence of coverage.
> The letter says this service is excluded. The plan document says it is covered.
>
> Neither reading is thrown away. Both are kept, with the quote and the file each came
> from, and the advocate is asked which one the appeal should proceed on. A contradiction
> like this is often the strongest argument in the file."

## Shot 5 — A letter written to manipulate the agent (2:50–3:30)

**Screen:** address 3. The pink banner sits above the letter.

> "Now a letter with something planted in it. Page two asks that an action be taken
> without informing the member.
>
> The agent that reads letters holds exactly two tools: record a fact with a quote, or
> record that the letter does not say. It cannot send, close, approve or notify. So there
> was nothing for that instruction to do. The advocate is told, and shown the text, and
> can quarantine the document.
>
> Prompt injection here is answered with permissions, not with a sentence in the prompt."

## Shot 6 — The draft, and the trace (3:30–4:10)

**Screen:** address 4, the draft tab.

> "The appeal is assembled, not generated. Each paragraph is written only when every fact
> it names is established and every document it needs is on file. Anything missing is left
> out, and the draft says so. No sentence here was written by a model."

Click the **Trace** tab.

> "And every write the agent attempted is here, including the ones the ledger refused. The
> writer on this demo workspace is named *AnswerKey at demo, not a model* — that is the
> honesty check I mentioned."

## Shot 7 — What it measures (4:10–4:40)

**Screen:** the repository README on GitHub, scrolled to the evaluation table.

> "Measured on sixty synthetic denial letters with Claude Opus four point six on Amazon
> Bedrock: ninety-nine point seven percent field accuracy, a nought point three percent
> hallucination rate, and ninety-nine point four percent correct abstention.
>
> Four of those letters carry a second, planted notice date. The planted date won in none
> of them. All three mistakes the model made are published, with the letters that caused
> them.
>
> The model reads. Code decides. A person files. Overturn is open source, under the MIT
> licence."

---

## After recording

- Watch it once. Check that no real email address, key or unrelated tab is on screen.
- Upload to YouTube as **public**.
- Put the link in [submission.md](submission.md) under *Links*, and in the Devpost form.
