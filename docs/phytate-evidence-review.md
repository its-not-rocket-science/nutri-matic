# Phytate evidence & licensing review

Scoped by Prompt 1 of the phytate/mineral-bioavailability extension (see
`prompts.txt`). This is a pre-work document only — no schema or code
changes. **Do not populate real PhyFoodComp data (Prompt 3) into a paid
tier until the commercial-use request in §1 has had a written answer
from FAO.**

Per the extension's terminology rule: this document and the feature it
scopes describe phytate's effect on mineral bioavailability, not an
"anti-nutrient." Phytate also has documented antioxidant activity: framing
it as purely negative would be inaccurate and is out of scope for how this
app communicates.

## 1. Licence / redistribution terms — CONFIRMED non-commercial; commercial use needs a separate FAO request

The target dataset is FAO/INFOODS/IZiNCG's **PhyFoodComp** (version 1.0),
distributed as an Excel workbook (`PhyFoodComp_1.0.xlsx`) directly from
FAO's INFOODS "tables and databases" page. The FAO Open Knowledge
catalogue page for the same item returned HTTP 403 to automated fetches
throughout this review, but the workbook itself is a plain, unauthenticated
download and carries its own copyright statement — the actual answer,
not the catalogue page, is what settles this.

**The workbook's own "Introduction and copyright" sheet embeds a
copyright/disclaimer notice as an image** (`xl/media/image1.png` inside
the `.xlsx`, positioned directly under that sheet's text — not visible
via a normal cell-text read, only by unzipping the `.xlsx` and opening
the image directly). In full:

> The designations employed and the presentation of material in this
> information product do not imply the expression of any opinion
> whatsoever on the part of the Food and Agriculture Organization of the
> United Nations (FAO)... The views expressed in this information product
> are those of the author(s) and do not necessarily reflect the views or
> policies of FAO.
>
> ISBN 978-92-5-109790-8
>
> © FAO, 2018
>
> FAO encourages the use, reproduction and dissemination of material in
> this information product. Except where otherwise indicated, material
> may be copied, downloaded and printed for private study, research and
> teaching purposes, **or for use in non-commercial products or
> services**, provided that appropriate acknowledgement of FAO as the
> source and copyright holder is given and that FAO's endorsement of
> users' views, products or services is not implied in any way.
>
> **All requests for translation and adaptation rights and for resale and
> other commercial use rights should be made via
> www.fao.org/contact-us/licence-request or addressed to
> copyright@fao.org.**

This is a standard FAO non-commercial notice, not CC BY 4.0 — confirms
the concern this section originally flagged as unresolved (FAO's general
terms restrict commercial-enterprise use; this item-specific notice is
even more direct about it) rather than resolving it in the app's favour.
Non-commercial use — free tier, research/methodology-page use, this
app's own development — is unambiguously covered ("appropriate
acknowledgement of FAO" required, see the citation format in §4).
**Use inside this app's paid tiers is not covered by this notice as
written** and needs a separate written answer from FAO under their
commercial-licence-request process.

**Status:** the licence-clarification email already sent to
`copyright@fao.org` (see conversation history) covers this — it asks
directly whether commercial-tier use is permitted and on what terms.
Until FAO replies, treat phytate data as **non-commercial-tier only**:
fine to build, test, and ship in the app's free tier once real ingestion
(Prompt 3) is complete — the file itself is now in hand (see the
download above), so that's no longer blocked — but gate it out of any
paid tier until a written commercial-use answer arrives.

## 2. What PhyFoodComp actually contains

Source: Dahdouh et al. 2019 (full citation in §4), the paper describing
PhyFoodComp's construction, cross-checked against the IZiNCG announcement.

- **Size and structure:** 3,377 food entries/recipes across 19 food
  groups and subgroups. 39% raw foods, 61% processed. By food group:
  cereals ~35%, legumes ~27%, vegetables ~11%, remainder spread across
  the other 16 groups — coverage is heavily weighted toward
  cereals/legumes, thin elsewhere. Compiled from a literature search of
  over 250 source references.
- **Cultivar/variety:** recorded where the source literature reported it;
  the paper notes "English and scientific names are... presented as
  found in the original literature," i.e. granularity is whatever the
  underlying study gave, not standardised across entries.
- **Processing state:** recorded, spanning raw through ultra-processed,
  with free-text comment fields carrying additional processing detail
  (e.g. soaking, fermentation, milling) where the source specified it.
- **Analytical method:** recorded per value via INFOODS tagnames
  distinguishing method families — e.g. indirect colorimetric/
  precipitation methods (tag family `PHYTCPPI`) vs. anion-exchange
  (`PHYTCPP`) vs. HPLC-based methods. This matters: different analytical
  methods for phytate are known to disagree, so method should be
  retained alongside the value, not discarded — reinforces the schema
  requirement in Prompt 2 to keep an `analytical_method` field.
- **Reporting basis — resolved, not actually ambiguous:** PhyFoodComp
  normalises all published values to **per 100g edible portion (EP), wet
  ("as consumed") basis**, at the database-compilation stage. Where a
  source study reported dry-matter values, PhyFoodComp's compilers
  converted them to EP using the study's own reported water content. This
  means: (a) PhyFoodComp itself is uniformly EP/wet-basis, so Prompt 3's
  ingestion does not need to detect a per-entry basis flag from
  PhyFoodComp — but (b) the *conversion itself* is a derived value
  (original-published-value + assumed/reported water content →
  converted value), which is exactly the "original value as published,
  plus normalised value, kept separately" requirement Prompt 2 already
  specifies. Ingestion should treat PhyFoodComp's reported EP value as
  the "normalised" value for schema purposes and, where the paper's
  supplementary data exposes it, retain the pre-conversion figure too —
  worth checking when the actual spreadsheet is in hand at Prompt 3,
  since the underlying per-row dry/wet provenance may not survive into
  the public release column set.

## 3. Known gaps and quality concerns (stated by the database's own authors)

- **High rejection rate:** 72% of initially identified candidate papers
  were excluded during quality screening — the authors were selective,
  which is good for reliability but means the literature base is
  materially smaller than a first search would suggest.
- **Uneven coverage:** some food groups remain thin or empty; coverage
  skews to cereals and legumes (consistent with phytate's greatest public
  health relevance being cereal/legume-based diets) at the expense of
  other food groups this app covers.
- **Cross-study noise:** the authors explicitly warn that differences in
  variety, storage time, and processing conditions between studies "can
  lead to inconclusive or even confusing and nonsense results" when
  values are compared across entries — supports the ground rules'
  instruction to default new PhyFoodComp-to-FDC matches to "regional" or
  "analogue" confidence rather than "exact."
  Related repo pattern: [[phytate-match-confidence]] (Prompt 3 will
  establish this; not yet written).
- **Method-comparability gap:** no certified reference material exists
  for lower inositol-phosphate forms (IP4 and below), which the authors
  say has limited adoption of HPLC methods for those forms specifically —
  i.e. even within the "analytical method" field, not all methods are
  equally validated against a ground truth.

## 4. Load-bearing citations (annotated, for the in-app methodology page)

Mirrors how DIAAS/PDCAAS sourcing is documented today (see
`backend/app/digestibility_reference.py`'s inline per-entry citations and
`docs/stock-recipes.md`'s methodology references) — short, annotated,
not a link dump.

1. **Dahdouh S, Grande F, Espinosa SN, Vincent A, Gibson R, Bailey K,
   King J, Rittenschober D, Charrondière UR (2019). "Development of the
   FAO/INFOODS/IZINCG Global Food Composition Database for Phytate."
   *Journal of Food Composition and Analysis* 78:42–48.
   https://doi.org/10.1016/j.jfca.2019.01.023** — the primary methods
   paper for PhyFoodComp itself: how foods were selected, how values were
   normalised to EP, and the quality-screening process in §3 above. This
   is the citation for the dataset's construction, distinct from the
   dataset artifact's own (non-commercial, see §1) licence.

2. **FAO/IZiNCG (2018). FAO/INFOODS/IZiNCG Global Food Composition
   Database for Phytate, Version 1.0 - PhyFoodComp 1.0. Rome, Italy.**
   ISBN 978-92-5-109790-8. Prepared by Sergio Dahdouh, Fernanda Grande,
   Sarah Nájera Espinosa, Morgane Fialon, Anna Vincent, Rosalind Gibson,
   Janet King, Doris Rittenschober & U. Ruth Charrondière. Downloaded
   directly from
   `fao.org/fileadmin/templates/food_composition/documents/PhyFoodComp_1.0.xlsx`
   (linked from `fao.org/infoods/infoods/tables-and-databases`) —
   citation and ISBN confirmed from the workbook's own "Introduction and
   copyright" sheet (see §1), not just the announcement page. This is the
   dataset artifact itself, as distinct from the methods paper above, and
   the citation Prompt 2's `source_dataset_name`/`source_dataset_version`
   fields should point to.

3. **Hotz C, Brown KH, eds (2004). "Assessment of the risk of zinc
   deficiency in populations and options for its control." International
   Zinc Nutrition Consultative Group (IZiNCG) Technical Document #1.**
   *Food and Nutrition Bulletin* 25(1 Suppl 2):S99–S203. — establishes the
   phytate:zinc molar-ratio bands (>15 = low predicted zinc
   bioavailability) that Prompt 4's descriptive indicator language should
   cite when it labels a ratio "high," rather than inventing a threshold.
   Foundational, IZiNCG's own reference — directly relevant since IZiNCG
   is a co-author of PhyFoodComp.

4. **Hurrell R, Egli I (2010). "Iron bioavailability and dietary
   reference values." *American Journal of Clinical Nutrition*
   91(5):1461S–1467S. https://doi.org/10.3945/ajcn.2010.28674F** — the
   standard reference for phytate:iron molar-ratio interpretation
   (ratio <1 associated with materially improved iron absorption),
   analogous role to citation 3 but for iron. Needed because Prompt 4
   scopes both phytate:zinc and phytate:mineral ratios generally, not
   zinc alone.

Citations 3 and 4 are the accepted molar-ratio *interpretation* thresholds
in the literature, not part of PhyFoodComp itself — flagging this
distinction explicitly since Prompt 4's UI copy needs to attribute the
"high/moderate/low" labelling to the right source, not imply FAO/IZiNCG's
PhyFoodComp defines those bands (it reports values; these two papers
supply the interpretive cutoffs).

## 5. review_3 (branded, low-confidence bucket) — sampling methodology & result

Per the phytate-review protocol's step 4: a reproducible random sample
(fixed seed, `sampled_for_review=YES` column in
`docs/phytate-review/review_3_branded_low_confidence.csv`) of **120 rows**
out of the full **752-row** branded/low-confidence bucket was reviewed by
hand, one row at a time. Sample size was chosen to give roughly a
±8–9 percentage-point margin on the estimated error rate at 95%
confidence in the worst case, per the protocol's original design (sized
against the 748-row bucket this pool was originally exported at; the
752-row regenerated export is close enough not to warrant a re-sample).

**Result: 77 reject, 42 approve, 1 deferred** (a duplicate row already
reviewed in `review_4_special_cases.csv`) — a **64.7% reject rate**
(77/119 judged rows). At 95% confidence that's 64.7% ± 8.6 percentage
points (56.1–73.3%), consistent with the ±8–9pp design target; applying
a finite-population correction for sampling 119 of 748 tightens that
slightly to roughly ±7.9pp.

**Confidence in the untouched ~628 rows: low.** A majority-reject rate
this high means the pipeline's confidence-threshold-only acceptance rule
is *more often wrong than right* for this specific bucket — candidates
here are dominated by coincidental word-overlap mismatches (a legume
matched to an unrelated snack/soup/condiment sharing one word with its
name; several outright bizarre brand mismatches, e.g. a denim-clothing
company's name matched to a bean snack, an auto-parts company's name
matched to salsa) rather than genuine near-misses. This is a materially
worse hit rate than review_1's ambiguous bucket (which ran closer to a
roughly even split once auto-flagged and classifier-caught mismatches
were removed). **Recommendation: do not let the remaining ~628
branded/low-confidence rows reach production via the confidence
threshold alone — either review the full bucket by hand, or treat this
bucket's candidates as `unresolved` by default until reviewed.** This
finding should also inform Prompt 3's matching-rule work: branded-food
fuzzy matching at this confidence tier appears to be picking up
brand-name/product-name text overlap without any real category
correspondence far more often than not.

## 6. Compound-tag handling — code check (phytate-review protocol step 6)

Read `backend/app/ingest_phytate.py` (`ingest_rows`, `RawObservation`),
`backend/app/phyfoodcomp_adapter.py` (`load_phyfoodcomp_workbook`,
`_PHYTATE_TAGNAMES`), and `CompoundObservation` in `backend/app/models.py`
end to end. Three questions, three checked (not assumed) answers:

**1. No averaging across different tags for the same food — confirmed.**
`load_phyfoodcomp_workbook` loops over all 16 `_PHYTATE_TAGNAMES` per food
row (`phyfoodcomp_adapter.py:183-206`) and appends one `RawObservation`
per *populated* tag cell, each carrying its own `value` and
`compound_fraction=tagname`. `ingest_rows` then inserts one
`CompoundObservation` row per `RawObservation`
(`ingest_phytate.py:386-392`), keyed by
`(compound, source_dataset_name, source_dataset_version,
source_row_identifier)` — and `source_row_identifier` is built as
`f"{row_identifier}:{tagname}"` (`phyfoodcomp_adapter.py:204`), so the tag
is baked into the uniqueness key itself. Nowhere in either file is a
`sum()`, `+=`, or mean/average computed across tags — confirmed by
absence, not just by not finding a bug. This matches every multi-tag food
seen throughout the phytate-review CSVs (e.g. `16010086:IP5`,
`16010086:IP5_A_IP6`, `16010086:IP6` as three distinct rows for one food).

**2. Phosphorus-based tags (PPI/PPD/PP-) — NOT converted, but clearly
labelled and stored separately, which is the documented fallback the
protocol allows.** `original_value` is stored verbatim
(`ingest_phytate.py:369`, "never altered" per its own column comment in
`models.py:1031-1033`) — no ×3.55-type phytate-phosphorus→phytic-acid
molecular conversion factor is applied anywhere. The model *has*
`normalised_value`/`normalised_unit`/`normalised_basis`/
`normalisation_method` columns built for exactly this kind of derived
conversion, but they are never populated by this ingestion path — the
`fields` dict passed to both insert and update in `ingest_rows`
(`ingest_phytate.py:366-384`) has no `normalised_*` keys at all, and
`phyfoodcomp_adapter.py`'s own docstring (line 29) explains why: it only
implemented normalisation for the wet/dry-*basis* conversion PhyFoodComp
already resolved at compilation time, not the phosphorus/phytic-acid unit
conversion. What the schema *does* guarantee: each phosphorus tag gets
its own self-documenting `analytical_method` text ("Phytate phosphorus,
determined by indirect precipitation", etc. —
`phyfoodcomp_adapter.py:71-73`), distinct from the phytic-acid tags'
wording ("Phytic acid, determined by..."), and its own `compound_fraction`
value (`PPI`/`PPD`/`PP-`) — so a phosphorus-basis row is unambiguous and
never silently mixed with a phytic-acid-basis row. **This satisfies the
protocol's explicit fallback ("or are stored separately, clearly
labelled, if not converted") but not the primary ask** — a future
consumer must know to apply the phosphorus→phytic-acid conversion itself
(or explicitly choose not to compare phosphorus-tag rows against
phytic-acid-tag rows) since the database will not do it for them.

**3. IP3-IP6/IP5_A_IP6/IP4_A_IP5_A_IP6/IPSUM — not summed, and each is
distinctly labelled as to what it already represents — confirmed.** All
six inositol-phosphate tagnames go through the exact same per-tag loop as
check 1 — `IP5_A_IP6` and `IP4_A_IP5_A_IP6` are *pre-summed* values as
published by the source (their `analytical_method` text says so
explicitly: "summed" — `phyfoodcomp_adapter.py:78-80`), stored as their
own independent rows, never added on top of the individual `IP3`-`IP6`
rows to build a second total. No aggregation code exists in either file.

**Forward-looking risk, not a bug in the code that exists today:** there
is currently no downstream consumer of `CompoundObservation` at all — a
repo-wide search found only the model, this ingestion script, and the
adapter referencing it; no router, no display/API code reads this table
yet (Prompt 4's ratio/display work hasn't been built). That means the
"isn't summed in a way that double-counts" property is true today only
because *nothing sums anything yet*. The real double-counting and
phosphorus-conversion risk lands on whatever Prompt 4 code eventually
picks "the" phytate value for a food to show in the app or compute a
phytate:mineral molar ratio with — it must not naively sum `IP3+IP4+IP5+
IP6+IP5_A_IP6+IPSUM` (triple/quadruple-counting the overlapping
fractions), and it must not compare a `PP-`/`PPI`/`PPD` row directly
against a `PHYTC*` row without applying the phosphorus→phytic-acid
conversion first. Flagging this explicitly for whoever writes that code,
since the ingestion layer being correct is necessary but not sufficient —
this check does not extend past ingestion because nothing past ingestion
exists to check yet.

## 7. review_6 (accepted matches) — result, FULL BUCKET (updated from sample)

**Update: the initial 211-row stratified sample below was followed up
with a full review of the remaining 638 accepted rows** (in
`docs/phytate-review/review_6b_accepted_remainder.csv`), so **all 849
accepted rows have now been individually reviewed**, not just the
sample. Final result across all 849:

**504 reject, 297 approve, 48 replace — a 59.4% reject rate.** This
confirms the sample's finding was not a statistical fluke skewed by an
unlucky draw — the majority of this dataset's previously-accepted,
already-in-production-eligible matches are wrong, checked exhaustively,
not estimated.

The remainder-review surfaced the same failure patterns as the sample
(recurring word-coincidence "garbage bucket" candidates absorbing many
unrelated foods, false-cognate species names, silently-dropped
prep/processing state, unconfirmed ripeness/maturity/fat-content/color
assumptions baked into a candidate name) plus a few new ones worth
naming: the arbitrary-grain-default infant-flour bug recurred here too
(43 more rows, replaced to the mixed-grain generic for consistency with
review_5); several rows matched to **"Adidas Ag ORGANIC REFINED COCONUT
OIL"** for complex multi-ingredient dishes that only happened to mention
coconut oil as one minor ingredient (the sportswear company's coconut-oil
private-label product, an obviously wrong and almost certainly
pipeline-glitch match); and repeated instances of a source's own explicit
attribute (ripe/unripe, seeded/seedless, a specific color) directly
contradicting the same attribute on the matched candidate.

**Original sample writeup follows, superseded in scope (see above) but
kept for the stratification methodology and reasoning trail:**

## 7a. review_6 (accepted matches, stratified sample) — original result

Per phytate-review-protocol.txt step 5: `docs/phytate-review/export_accepted.py`
(new script, written this session — see its docstring) exported every
observation with `match_relationship != 'needs_review'` — the rows the
ingestion pipeline was confident enough to accept without flagging for
human review, and which can currently reach production untouched. **849
such rows exist.** Per the protocol's stratified design: all 86 rows
whose description contains a cultivar/variety/processing/coagulant
qualifier were taken outright (`sample_stratum=high_risk_keyword`), plus
a fixed-seed random sample of 125 from the remaining 763
(`sample_stratum=random_sample`) — 211 rows total, in
`docs/phytate-review/review_6_accepted_sample.csv`, all individually
reviewed by hand.

**Result: 151 reject, 55 approve, 5 replace — a 71.6% reject rate.**
Split by stratum: **88.4% reject among the high-risk rows** (as
expected — these are exactly the descriptions most likely to have had
their distinguishing detail silently discarded), and **60.0% reject even
in the plain random sample** — meaning a majority of this dataset's
*accepted, already-in-production-eligible* matches are wrong even
without targeting the highest-risk rows. This is a **worse** rate than
review_3's low-confidence-branded bucket (64.7% reject) and far worse
than review_1's ambiguous bucket, despite these being the rows the
pipeline was most confident about.

Recurring failure patterns found (several confirmed systemic, not
one-off, by recurring across multiple unrelated source rows in this
211-row sample alone):
- **A small number of candidates acting as "garbage buckets"** that
  wrongly absorb many unrelated foods purely on shared vocabulary: "Seeds,
  watermelon seed kernels, dried" matched to Sesbania, soybean, lentil,
  and roselle (21 rows in this sample alone); "Seeds, breadfruit seeds,
  roasted" matched to African oil bean, Achi, and Ofo (three unrelated
  West African seeds); "Cornsalad, raw" and "Fonio, grain, dry, raw" both
  wrongly absorbing plain "Corn"/"Maize" rows (10 rows combined).
- **False-cognate species names**: "Milletia" (a legume tree) vs millet
  grain, "Manila tamarind" vs true tamarind, "Bajra" (pearl millet) vs
  bananas, "Rajmah" (kidney bean) vs blackberries, "Red gram" (pigeon
  pea) vs grapes — common/vernacular food names that share a word or
  sound with something completely unrelated.
- **Coagulant mismatches in tofu** (the exact concern review_4's
  TOFU_COAGULANT tag exists for): CaCl2 matched to a nigari-prepared
  candidate, MgCl2 matched to a calcium-sulfate-prepared candidate — real
  chemistry differences with a direct effect on the food's mineral
  content, the thing this whole feature exists to describe accurately.
- **Silently dropped prep/processing state** with a real compositional
  effect: raw vs dried vs roasted vs fermented vs extruded vs pearled —
  each pair confirmed materially changes phytate content, not just
  wording.
- **Unconfirmed assumptions bundled into the candidate name**: "peeled"
  where the source says nothing about peeling (or explicitly contradicts
  it), a specific coagulant/fat-content/ripeness/maturity-stage assumed
  without source support.

**This changed the overall picture materially.** The protocol's own
concern going in was that the 799(→849)-row accepted bucket was "the
single most important gap" because rejected/uncertain rows can't reach
production but these already can — this sample confirmed that concern was
correct, and worse than expected: this bucket's error rate was not lower
than the flagged buckets, it was higher. Following up, **the remaining
638 rows were then reviewed in full** (see §7 above) rather than left at
sample-only confidence — every one of the 849 accepted rows now has a
verdict.

## 8. Cross-file consistency check — 6 real conflicts found and resolved

`docs/phytate-review/check_consistency.py` (new script, written this
session) audits every review_*.csv file for structural consistency and
cross-file duplication. First run found 6 real conflicts: the same
`row_identifier` + candidate pair independently reviewed in both
`review_1_ambiguous.csv` (this session's automated/heuristic pass) and
`review_4_special_cases.csv` (a genuine pre-session human sign-off by
Paul S, dated 06/08/2026) — with **opposite verdicts**. All 6 root-caused
to the review_4 verdict being correct and review_1's being wrong,
exposing two real bugs in this session's automation:

1. **The word-overlap mismatch classifier doesn't know some real food
   correspondences share no vocabulary.** "Bean starch, vermicelli" was
   auto-rejected against "LUXURY VERMICELLI" because "bean"/"starch"
   share no token with "vermicelli" — but bean-starch vermicelli
   (cellophane/glass noodles) is a real, common product; the classifier
   has no notion of this kind of ingredient-to-product-name gap.
2. **The `PLANT_TO_ANIMAL_SUSPECT` auto_flag keyword heuristic
   false-positives in two related ways**: (a) it flagged
   "Soybean, curd cheese" as an animal product because "cheese" is in
   its `ANIMAL_KEYWORDS` list, not accounting for soy products that
   borrow dairy-analog naming ("soy milk", "curd cheese"); (b) it
   flagged "Spanish fish, large" → "Fish, mackerel, spanish, raw" as a
   plant-to-animal mismatch because "mackerel" (an animal keyword) isn't
   literally in the source text, even though the source is already an
   animal product ("fish") — the heuristic can't distinguish
   generic-vs-specific-within-the-same-domain from a genuine
   category mismatch.

Fixed: all 6 review_1 rows now defer to review_4's existing verdict
(see each row's `review_notes` for the pointer). Neither bug was fixed
at the classifier-code level (would require reasoning knowledge —
ingredient-to-product mappings, dairy-analog-naming awareness — a
keyword/token heuristic can't cheaply have); both are now documented
here as known limitations of the automated passes, worth keeping in mind
if the same heuristics get reused or extended for a future ingestion
run. The checker is safe to re-run at any time
(`python check_consistency.py --dir .` from `docs/phytate-review/`) and
should be run again after any further edits to these files.

## Summary for the human reviewer

- Dataset content, structure, and reporting-basis questions (Prompt 1
  items 2–3): resolved, documented above.
- Citation list (Prompt 1 item 4): drafted above, ready for the
  methodology page once Prompt 4 ships.
- **Licence (Prompt 1 item 1): confirmed non-commercial-only, from the
  PhyFoodComp1.0 workbook's own embedded copyright notice** (§1) —
  free tier / research / methodology-page use is fine with FAO
  attribution; paid-tier use needs a written commercial-licence answer
  from FAO, requested via the email already sent to `copyright@fao.org`.
  Build and ship to the free tier only until that reply arrives.
