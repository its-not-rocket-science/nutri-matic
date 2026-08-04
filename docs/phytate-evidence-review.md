# Phytate evidence & licensing review

Scoped by Prompt 1 of the phytate/mineral-bioavailability extension (see
`prompts.txt`). This is a pre-work document only — no schema or code
changes. **Do not proceed to Prompt 2 until a human has reviewed the
licensing section below and resolved the open question it flags.**

Per the extension's terminology rule: this document and the feature it
scopes describe phytate's effect on mineral bioavailability, not an
"anti-nutrient." Phytate also has documented antioxidant activity: framing
it as purely negative would be inaccurate and is out of scope for how this
app communicates.

## 1. Licence / redistribution terms — UNRESOLVED, needs direct human follow-up

The target dataset is FAO/INFOODS/IZiNCG's **PhyFoodComp** (version 1.0),
hosted as an Excel download via the FAO INFOODS "tables and databases"
page and catalogued in FAO's Open Knowledge repository. I could not
retrieve a PhyFoodComp-specific licence statement: FAO's Open Knowledge
item page and the direct bitstream URL both returned HTTP 403 to
automated fetches, and neither the INFOODS tables-and-databases page nor
the IZiNCG blog post announcing the database states a licence for this
specific dataset.

What I could confirm, from FAO's general statistical-database terms
(`fao.org/contact-us/terms/db-terms-of-use`):

- FAO's default for corporate statistical databases is **CC BY 4.0**,
  *"unless specified otherwise in their metadata or webpage."*
- That default explicitly **prohibits use "for or in conjunction with the
  promotion of a commercial enterprise and/or its product(s) or
  services"** — a real constraint given this app's tiered/commercial
  ambitions (see `docs/tiered-commercial-model.md`); CC BY 4.0's own
  attribution terms do not on their own permit that use.
- FAO states some datasets carry **third-party content with different,
  more restrictive terms**, and puts the burden on the reuser to check.
  PhyFoodComp is a plausible candidate for this: it was compiled by
  extracting values from >250 published journal articles (see §2), which
  raises exactly the kind of third-party-content question FAO's terms
  warn about — the compiled *database* and the underlying *published
  measurements* are not obviously covered by the same licence.
- FAO's blanket move to CC BY 4.0 "Open Access" is dated to 2024;
  pre-2024 FAO repository items have historically used more restrictive
  licences (e.g. CC BY-NC-SA 3.0 IGO). PhyFoodComp1.0's release predates
  2024 (the methodology paper is 2019; the dataset item appears to date
  to around 2021), so it is not safe to assume the current default
  applies retroactively without checking the item's own metadata.

**Action required before Prompt 2 starts:** a human needs to either (a)
open the FAO Open Knowledge item page directly in a browser (it blocked
automated fetching here) and read its Rights/Licence metadata field, or
(b) email `copyright@fao.org` referencing the PhyFoodComp1.0 item and ask
directly whether redistribution of derived/normalised values inside an
open-source, commercially-licensed application is permitted, and under
what attribution terms. Do not populate the schema from Prompt 2 with
real PhyFoodComp values until this is answered — a NonCommercial or
third-party-restricted licence would block the ingestion step (Prompt 3)
entirely as currently scoped, or at minimum require gating the feature
out of paid tiers.

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
   dataset artifact's own (still-unresolved, see §1) licence.

2. **FAO/INFOODS/IZiNCG. Global food composition database for phytate,
   version 1.0 (PhyFoodComp1.0).** FAO, Rome. Accessed via
   `fao.org/infoods/infoods/tables-and-databases`. — the dataset artifact
   itself, as distinct from the methods paper above; this is the citation
   Prompt 2's `source_dataset_name`/`source_dataset_version` fields should
   point to. Exact publication date to confirm once the licence question
   in §1 is resolved and the file is actually in hand.

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
- **Licence (Prompt 1 item 1): not resolved.** This is a blocking
  open question, not a formality — FAO's general terms include a
  commercial-use restriction that may be directly incompatible with this
  app's commercial tiers, and PhyFoodComp's own item-level licence
  metadata was not accessible to confirm or rule this out. Get a
  human to check the FAO item page directly and/or get a written answer
  from FAO before Prompt 2 begins.
