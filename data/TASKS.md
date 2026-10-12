# Proposed LegalBench tasks

Status: **approved** (`approved: true` in `data/tasks.yaml`).

Source: Hugging Face `nguha/legalbench` at commit `daec8237410a`, `test` split. Licenses are read from each task's card in the LegalBench repository at commit `b46bf4ffae90` and were re-checked by `model-diff propose-tasks` on 2026-10-12.

All 5 proposed tasks carry licenses that permit commercial use (CC BY 4.0, MIT). Tasks under non-commercial licenses were screened out because this harness will later run commercially; CC BY tasks require attribution in the write-up.

## Proposed tasks

| Task | Domain | Labels | Flag label(s) | Test split | Planned sample | Sampling | License |
|---|---|---|---|---|---|---|---|
| `insurance_policy_interpretation` | Insurance | 3 | Yes | 133 | 133 | random | CC BY 4.0 |
| `sara_entailment` | Tax | 2 | Entailment | 272 | 200 | random | MIT |
| `privacy_policy_qa` | Privacy compliance | 2 | Relevant | 10923 | 200 | random | MIT |
| `telemarketing_sales_rule` | Consumer finance | 2 | Yes | 47 | 47 | random | CC BY 4.0 |
| `unfair_tos` | Consumer protection | 9 | any label except Other | 3813 | 200 | stratified | CC BY 4.0 |

### Justifications

- **`insurance_policy_interpretation`**: Decides whether a described claim is covered by a policy clause, the core call in claims handling, with an explicit "ambiguous" answer that shows whether a model commits or hedges.
- **`sara_entailment`**: Applies excerpts of the US Internal Revenue Code to a fact pattern and decides whether a statement about the tax treatment follows, which tests statutory application rather than recall.
- **`privacy_policy_qa`**: Decides whether a privacy-policy clause answers a user's question about a data practice, the step behind privacy-notice review and data-subject request triage.
- **`telemarketing_sales_rule`**: Applies the deceptive-practice provisions of the US Telemarketing Sales Rule (16 C.F.R. 310.3(a)(1)-(2)) to sales fact patterns and decides whether a violation occurred, a direct consumer-protection compliance call.
- **`unfair_tos`**: Sorts consumer terms-of-service clauses into eight categories of potentially unfair term (arbitration, unilateral change, liability limits, and so on) or Other, as in an unfair-terms review.

### Details

**`insurance_policy_interpretation`** · prompt family `insurance_coverage`

- Labels (dataset codes A=Yes, B=No, C=Ambiguous): Yes, No, Ambiguous
- Test-split gold labels: Yes 47, No 27, Ambiguous 59
- Input: Policy + Claim; mean 530 characters
- License: [CC BY 4.0](https://github.com/HazyResearch/legalbench/tree/b46bf4ffae90524b2b72aaa30e7745fe9db64481/tasks/insurance_policy_interpretation), matches the task card

**`sara_entailment`** · prompt family `tax_statute_entailment`

- Labels: Entailment, Contradiction
- Test-split gold labels: Entailment 136, Contradiction 136
- Input: Statute + Facts + Statement; mean 407 characters
- License: [MIT](https://github.com/HazyResearch/legalbench/tree/b46bf4ffae90524b2b72aaa30e7745fe9db64481/tasks/sara_entailment), matches the task card

**`privacy_policy_qa`** · prompt family `privacy_policy`

- Labels: Relevant, Irrelevant
- Test-split gold labels: Relevant 5449, Irrelevant 5474
- Input: Question + Clause; mean 244 characters
- License: [MIT](https://github.com/HazyResearch/legalbench/tree/b46bf4ffae90524b2b72aaa30e7745fe9db64481/tasks/privacy_policy_qa), matches the task card

**`telemarketing_sales_rule`** · prompt family `consumer_protection_rule`

- Labels: Yes, No
- Test-split gold labels: Yes 28, No 19
- Input: Facts; mean 354 characters
- License: [CC BY 4.0](https://github.com/HazyResearch/legalbench/tree/b46bf4ffae90524b2b72aaa30e7745fe9db64481/tasks/telemarketing_sales_rule), matches the task card

**`unfair_tos`** · prompt family `unfair_contract_terms`

- Labels: Arbitration, Unilateral change, Content removal, Jurisdiction, Choice of law, Limitation of liability, Unilateral termination, Contract by using, Other
- Test-split gold labels: Arbitration 15, Unilateral change 53, Content removal 25, Jurisdiction 32, Choice of law 28, Limitation of liability 98, Unilateral termination 70, Contract by using 38, Other 3454
- Input: Clause; mean 191 characters
- License: [CC BY 4.0](https://github.com/HazyResearch/legalbench/tree/b46bf4ffae90524b2b72aaa30e7745fe9db64481/tasks/unfair_tos), matches the task card

## Sample plan

`cases_per_task: 200` and `seed: 42` give **780 cases**. Tasks with fewer test cases than that are used whole. Each case runs 3 times on each model, so the run makes 4680 subject calls before latency probes and judge calls. `model-diff dry-run` prices this exactly before any paid call.

- `insurance_policy_interpretation` (133 cases) and `telemarketing_sales_rule` (47 cases) are used whole and are small. Per-task confidence intervals there will be wide, and per-task changes should be read as indicative.
- `unfair_tos` is sampled stratified, with equal shares per label, because 91% of its test split is `Other`. Its flag rate describes the sample, not the natural mix.
- Case inputs quote public source text, which can include website names. `data/cases.jsonl` and `runs/` are gitignored and regenerate deterministically.

## Screened out

The keyword screen (see `model-diff propose-tasks`) matched 28 tasks. `sara_entailment` did not match the screen and was added by hand; its justification above gives the domain. These matches are not proposed:

| Candidate | License (task card) | Reason |
|---|---|---|
| `canada_tax_court_outcomes` | CC BY-NC 4.0 | Non-commercial license, inherited from the court's terms for the source decisions. |
| `consumer_contracts_qa` | CC BY-NC 4.0 | Non-commercial license; the harness is meant for later commercial use. |
| `contract_nli_permissible_acquirement_of_similar_information` | CC BY 4.0 | Non-disclosure-agreement clause entailment; not in the named domains. |
| `cuad_anti-assignment` | CC By 4.0 | Commercial-contract clause detection over long agreements naming real counterparties; not a compliance determination. |
| `cuad_exclusivity` | CC By 4.0 | Commercial-contract clause detection over long agreements naming real counterparties; not a compliance determination. |
| `cuad_insurance` | CC By 4.0 | Commercial-contract clause detection over long agreements naming real counterparties; not a compliance determination. |
| `cuad_most_favored_nation` | CC By 4.0 | Commercial-contract clause detection over long agreements naming real counterparties; not a compliance determination. |
| `cuad_non-transferable_license` | CC By 4.0 | Commercial-contract clause detection over long agreements naming real counterparties; not a compliance determination. |
| `cuad_post-termination_services` | CC By 4.0 | Commercial-contract clause detection over long agreements naming real counterparties; not a compliance determination. |
| `cuad_source_code_escrow` | CC By 4.0 | Commercial-contract clause detection over long agreements naming real counterparties; not a compliance determination. |
| (identifier withheld: it is a company name) | CC BY 4.0 | Leveraged-loan covenant classification; permissively licensed and on topic, but its task identifier would put a company name in this repo. |
| `learned_hands_business` | CC BY-NC-SA 4.0 | Non-commercial share-alike license; also lay issue-spotting rather than a compliance determination. |
| `learned_hands_consumer` | CC BY-NC-SA 4.0 | Non-commercial share-alike license; also lay issue-spotting rather than a compliance determination. |
| `learned_hands_education` | CC BY-NC-SA 4.0 | Non-commercial share-alike license; also lay issue-spotting rather than a compliance determination. |
| `learned_hands_estates` | CC BY-NC-SA 4.0 | Non-commercial share-alike license; also lay issue-spotting rather than a compliance determination. |
| `maud_financial_point_of_view_is_the_sole_consideration` | CC By 4.0 | Merger-agreement deal-point questions with per-question answer sets; corporate transactions rather than compliance. |
| `maud_general_economic_and_financial_conditions_subject_to_disproportionate_impact_modifier` | CC By 4.0 | Merger-agreement deal-point questions with per-question answer sets; corporate transactions rather than compliance. |
| `opp115_data_retention` | Creative Commons Attribution-NonCommercial License | Non-commercial license (all OPP-115 privacy tasks). |
| `opp115_data_security` | Creative Commons Attribution-NonCommercial License | Non-commercial license (all OPP-115 privacy tasks). |
| `opp115_first_party_collection_use` | Creative Commons Attribution-NonCommercial License | Non-commercial license (all OPP-115 privacy tasks). |
| `opp115_policy_change` | Creative Commons Attribution-NonCommercial License | Non-commercial license (all OPP-115 privacy tasks). |
| `opp115_third_party_sharing_collection` | Creative Commons Attribution-NonCommercial License | Non-commercial license (all OPP-115 privacy tasks). |
| `privacy_policy_entailment` | CC BY-NC 3.0 | Non-commercial license. |
| `supply_chain_disclosure_disclosed_verification` | CC by 4.0 | Supply-chain anti-trafficking disclosures; outside the named domains. |
