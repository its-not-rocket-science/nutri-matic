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
