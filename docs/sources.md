# Sources

Every figure quoted in the README, and every timeframe hard-coded in the deadline engine,
is listed here with where it came from and when it was checked.

This file exists because of a specific weakness in the project's own claim to domain
knowledge. The thesis behind Overturn — that these files are lost on procedure rather than
on the merits — comes from the author's observation inside an arbitration institution.
That observation generalises across legal systems. **ACA appeal mechanics do not.** They
were learned from the sources below, and the engine is written so that each rule can be
traced back to one of them rather than to recollection.

**Verification:** every row below was checked on 2026-09-10 against the regulation text
(Cornell LII's copy of the eCFR) or the publisher's own page.

---

## Statutory timeframes used by the deadline engine

| Rule | Value | Runs from | Citation | Where it is used |
|---|---|---|---|---|
| Internal appeal filing window | at least 180 days | receipt of the adverse benefit determination | 29 CFR 2560.503-1(h)(3)(i), incorporated by 45 CFR 147.136(b) | `INTERNAL_FILING_DAYS` |
| Plan decision, urgent care appeal | 72 hours | the plan's receipt of the appeal | 29 CFR 2560.503-1(i)(2)(i) | `Regime.ACA_URGENT` |
| Plan decision, pre-service appeal | 30 days | the plan's receipt of the appeal | 29 CFR 2560.503-1(i)(2)(ii) | `Regime.ACA_INTERNAL_PRE_SERVICE` |
| Plan decision, post-service appeal | 60 days | the plan's receipt of the appeal | 29 CFR 2560.503-1(i)(2)(iii)(A) | `Regime.ACA_INTERNAL_POST_SERVICE` |
| External review request (federal process) | 4 months | receipt of the notice of adverse or final internal adverse determination | 45 CFR 147.136(d)(2)(i) | `Regime.ACA_EXTERNAL` |
| Standard external review decision | 45 days | the reviewer's receipt of the request | 45 CFR 147.136(d)(2)(iii)(B)(6) | not modelled as a deadline |
| Expedited external review decision | 72 hours | the reviewer's receipt of the request | 45 CFR 147.136(d)(3)(iv) | not modelled as a deadline |
| Deemed exhaustion | a plan that fails to strictly adhere to the rules may be treated as having exhausted its internal process | — | 45 CFR 147.136(b)(2)(ii)(F)(1) | the wording of the plan-response escalation |

### Where the engine deliberately errs

- **The filing window** runs from receipt of the notice. When the receipt date is unknown
  the engine uses the notice date, which is on or before receipt, so the computed deadline
  can only be earlier than the true one.
- **The plan's decision windows** run from the plan's receipt of the appeal. The engine
  counts from the filing date the advocate records, which is on or before receipt, so the
  computed date can only be earlier. The rule text shown beside the deadline says this.

### Why these are a floor and not the answer

- States regulate insurance and many extend these windows.
- Individual plans may grant more time than they are required to.
- Grandfathered plans, Medicare Advantage, Medicaid managed care, and non-health lines run
  different regimes. Only the ACA regimes above are modelled.

This is why `denial.stated_appeal_deadline` exists as a field and takes precedence over
every computation in the engine.

---

## Figures quoted in the README

| Claim | Figure | Source |
|---|---|---|
| In-network claims denied by HealthCare.gov insurers | about 19% (2024) | KFF, *Claims Denials and Appeals in ACA Marketplace Plans in 2024*, 24 March 2026 |
| Range of in-network denial rates across insurers | 3% to 36% (2024) | same |
| Denied in-network claims that consumers appealed | fewer than 1% (2024) | same |
| Internal appeals where the insurer reversed its denial | 34% (insurers upheld 66%) (2024) | same |
| Denials overturned by a state's independent external review | 655 of 1,353 eligible cases, about 48% (Pennsylvania, since 2024) | Pennsylvania Insurance Department, press release, 3 April 2026 |
| Medicare Advantage prior authorization denials appealed, and overturned on appeal | 11.5% appealed; more than eight in ten of those overturned (2024) | KFF, *Medicare Advantage Insurers Made Nearly 53 Million Prior Authorization Determinations in 2024*, 28 January 2026 |

Earlier drafts quoted "~34% of internal appeals overturned" alongside the 2023 denial rate,
"consumers prevail in ~45% of external reviews", and attributed the Medicare Advantage
figure to the HHS Office of Inspector General. Checking them showed the 34% is the 2024
figure (2023 was 44%), the 45% has no primary source we could find — KFF reports that
external appeal outcomes could not be calculated from the public data — and the Medicare
Advantage figure is KFF's analysis of CMS data. Those claims were corrected rather than
kept.

### Considered and not used

**"$262 billion in claims denied each year, 86% avoidable."** This comes from a Change
Healthcare analysis (2017) of claims submitted by *hospitals* in 2016, and describes
provider billing denials rather than denials faced by patients. It is not evidence about
the problem Overturn addresses, so it is not quoted.

---

## Corpus provenance

**Every document in the evaluation corpus is synthetic.** An earlier draft of this file
described a mix of adapted public templates and synthetic letters; that mix was never
built, and the description was corrected rather than left standing.

One of the four house styles follows the section structure of the federal model notice of
adverse benefit determination. It borrows the structure only — no text from a real notice
or a real insurer is used, and every insurer, provider and patient name is fictional.

How the corpus resists measuring an extractor against its own generator, and what it
cannot account for, is set out in `docs/eval-results.md`. Adding redacted real denial
letters is the most valuable single improvement available to the evaluation.

---

## Denial reason codes

Rule packs recognise payer reason codes from the X12 Claim Adjustment Reason Code (CARC)
list (x12.org/codes/claim-adjustment-reason-codes), checked 2026-09-10:

| Code | X12 description | Pack |
|---|---|---|
| CO-50 | These are non-covered services because this is not deemed a "medical necessity" by the payer | `medical_necessity` |
| CO-197 | Precertification/authorization/notification/pre-treatment absent | `prior_authorization` |
| CO-198 | Precertification/notification/authorization/pre-treatment exceeded | `prior_authorization` |
| CO-242 | Services not provided by network/primary care providers | `out_of_network` |
| CO-4 | The procedure code is inconsistent with the modifier used | `coding_error` |
| CO-11 | The diagnosis is inconsistent with the procedure | `coding_error` |
| CO-16 | Claim/service lacks information or has submission/billing error(s) | `coding_error` |
| CO-55 | Procedure/treatment/drug is deemed experimental/investigational by the payer | `experimental` |

Corrections made while checking:

- The first medical necessity pack also claimed CO-55 (experimental) and CO-167 (diagnosis
  not covered). Neither is a medical necessity denial; routing them there would have argued
  against a reason the plan did not give. Removed in `medical_necessity@1.1.0`.
- The first prior authorization pack claimed CO-15, which X12 deactivated on 2018-05-01.
  Removed in `prior_authorization@1.1.0`; a letter that still prints it is recognised by its
  wording instead. Some corpus letters print CO-15 on purpose, to keep that path tested.
- CO-22 (coordination of benefits) is recognised by no pack. Letters citing it are
  reported as outside the installed categories.
