# Sources

Every figure quoted in the README, and every timeframe hard-coded in the deadline engine,
is listed here with where it came from.

This file exists because of a specific weakness in the project's own claim to domain
knowledge. The thesis behind Overturn — that these files are lost on procedure rather than
on the merits — comes from the author's observation inside an arbitration institution.
That observation generalises across legal systems. **ACA appeal mechanics do not.** They
were learned from the sources below, and the engine is written so that each rule can be
traced back to one of them rather than to recollection.

---

## Statutory timeframes used by the deadline engine

| Rule | Value | Where it is used |
|---|---|---|
| Internal appeal filing window | 180 days from receipt of the adverse benefit determination | `INTERNAL_FILING_DAYS` in `overturn/engine/deadlines.py` |
| Plan decision, pre-service claim | 30 days | `Regime.ACA_INTERNAL_PRE_SERVICE` |
| Plan decision, post-service claim | 60 days | `Regime.ACA_INTERNAL_POST_SERVICE` |
| Plan decision, urgent care claim | 72 hours | `Regime.ACA_URGENT` |
| External review request window | 4 months from receipt of the final adverse determination | `Regime.ACA_EXTERNAL` |
| Standard external review decision | 45 days | `Regime.ACA_EXTERNAL` |
| Expedited external review decision | 72 hours | not yet modelled as a calendar deadline |

**Primary sources to cite in the README and video:**

- 29 CFR § 2590.715-2719 — Internal claims and appeals and external review processes
  (Department of Labor)
- 45 CFR § 147.136 — the parallel HHS rule
- 29 CFR § 2560.503-1 — ERISA claims procedure regulation, from which the 30/60 day and
  72 hour decision windows derive
- healthcare.gov, *Appealing a health plan decision*
- CMS, *External Review* guidance

> **Verification status: to be confirmed against the primary text before submission.**
> Nothing in this table should be quoted publicly until each row has been checked against
> the regulation itself rather than a secondary summary. The engine already treats these
> as a floor, not as truth: a deadline stated in the notice always overrides them, and a
> computed fallback is marked `regime_default` in the ledger so the interface can show
> that it was inferred.

### Why these are a floor and not the answer

- States regulate insurance and many extend these windows. A state-law appeal window is
  frequently longer than the federal minimum.
- Individual plans may grant more time than they are required to.
- Grandfathered plans, self-funded ERISA plans, Medicare Advantage, Medicaid managed care,
  and non-health lines (auto, property) run different regimes entirely. Only the ACA
  regimes above are modelled.

This is the reason `denial.stated_appeal_deadline` exists as a field and takes precedence
over every computation in the engine.

---

## Figures quoted in the README

| Claim | Source to cite |
|---|---|
| ~19% of in-network claims denied on 2023 ACA marketplace plans; wide per-plan variation | KFF, *Claims Denials and Appeals in ACA Marketplace Plans* |
| ~34% of internal appeals result in a reversal | KFF, same study |
| Consumers prevail in ~45% of external reviews | KFF / CMS external review data |
| Over 80% of appealed Medicare Advantage prior-authorization denials are overturned | HHS Office of Inspector General |
| The large majority of denials are never appealed | KFF, same study |
| ~$262bn in denied claims annually, a large share considered avoidable | Industry estimate — **weakest citation in the set** |

> **Verification status: to be confirmed.** The dollar figure is an industry estimate
> rather than a government statistic and should either be cited to its original publisher
> with that framing made explicit, or dropped. A number that cannot survive a judge asking
> "where is that from?" costs more than it adds.

---

## Corpus provenance

**Every document in the evaluation corpus is synthetic.** An earlier draft of this file
described a mix of adapted public templates and synthetic letters; that mix was never
built, and the description has been corrected rather than left standing.

One of the four house styles follows the section structure of the federal model notice of
adverse benefit determination. It borrows the structure only — no text from a real notice
or a real insurer is used, and every insurer, provider and patient name is fictional.

How the corpus resists measuring an extractor against its own generator, and what it
cannot account for, is set out in `docs/eval-results.md`. Adding redacted real denial
letters is the most valuable single improvement available to the evaluation.

---

## Denial reason codes

Rule packs recognise payer reason codes from the X12 Claim Adjustment Reason Code (CARC)
list, published by X12 (x12.org). The codes the packs use:

| Code | Meaning | Pack |
|---|---|---|
| CO-50 | Not deemed a medical necessity by the payer | `medical_necessity` |
| CO-197, CO-198 | Precertification or authorization absent, or exceeded | `prior_authorization` |
| CO-15 | Authorization number missing, invalid or not applicable | `prior_authorization` |
| CO-242 | Services not provided by network or primary care providers | `out_of_network` |
| CO-4, CO-11, CO-16 | Modifier or diagnosis inconsistent with the procedure; claim lacks information or has billing errors | `coding_error` |
| CO-55 | Procedure, treatment or drug deemed experimental or investigational | `experimental` |

The first version of the medical necessity pack also claimed CO-55 and CO-167. CO-55 is the
experimental code and CO-167 means the diagnosis is not covered; neither is a medical
necessity denial, and routing them there would have argued against a reason the plan did
not give. Both were removed in `medical_necessity@1.1.0`.

> **Verification status: to be confirmed against the current CARC list before
> submission.** Codes are revised by X12 on a schedule. Phrase matching does not depend on
> them, so a stale code would fail to match rather than misclassify.
